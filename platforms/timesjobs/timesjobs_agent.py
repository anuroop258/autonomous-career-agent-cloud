from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

ROOT = Path(__file__).resolve().parents[2]
PLATFORM_DIR = Path(__file__).resolve().parent
for value in (ROOT, PLATFORM_DIR):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from jd_matcher import JDMatcher  # noqa: E402
from storage import app, db, seen  # noqa: E402
from company_website_agent import CompanyWebsiteAgent  # noqa: E402
from platforms.common.application_flow import ApplicationFlow

BASE = "https://www.timesjobs.com"
HOME = f"{BASE}/myHome"


class TimesJobsAgent:
    """Backend-only TimesJobs adapter derived from the supplied TimesJobs UI flow."""

    def __init__(self, root_dir: Path = ROOT, platform_dir: Path = PLATFORM_DIR):
        self.root_dir = Path(root_dir)
        self.platform_dir = Path(platform_dir)
        self.config = json.loads((self.platform_dir / "role_config.json").read_text(encoding="utf-8"))
        self.target_applications = int(self.config.get("target_applications", 10))
        self.max_search_pages_per_role = int(self.config.get("max_search_pages_per_role", 5))
        self.max_total_candidates = int(self.config.get("max_total_candidates", 1000))
        self.preferred_locations = [str(x).strip() for x in self.config.get("preferred_locations", []) if str(x).strip()]
        self.roles = [str(x).strip() for x in self.config.get("primary", []) if str(x).strip()]
        self.allow_external = bool(self.config.get("allow_external_company_apply", True))
        self.db = db()
        self.matcher = JDMatcher(self.root_dir)
        self.applied = 0
        self.processed = 0
        self.skipped = 0
        self.errors = 0
        self._seen_this_run: set[str] = set()

    async def run(self, context: BrowserContext, target: str | None = None):
        page = await self._get_timesjobs_page(context)
        if target:
            await page.goto(target, wait_until="domcontentloaded")
            await page.wait_for_timeout(1200)
            await self._process_current_or_results(context, page)
            return

        # The recorded UI starts at /myHome. Search roles are entered in the visible
        # "Enter Skills, Designation, etc" field after opening the site search panel.
        for role in self.roles:
            if self.applied >= self.target_applications or self.processed >= self.max_total_candidates:
                break
            try:
                await self._search_role(page, role)
                await self._process_current_or_results(context, page)
            except Exception as exc:
                self.errors += 1
                print(f"TIMESJOBS ROLE ERROR [{role}]: {type(exc).__name__}: {exc}")

    async def _get_timesjobs_page(self, context: BrowserContext) -> Page:
        for page in context.pages:
            if page.is_closed():
                continue
            if "timesjobs.com" in (page.url or "").lower():
                return page
        page = await context.new_page()
        await page.goto(HOME, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)
        return page

    async def _accept_cookies(self, page: Page):
        for loc in (
            page.get_by_role("button", name=re.compile(r"^OK$", re.I)).first,
            page.get_by_text(re.compile(r"^OK$", re.I)).first,
        ):
            try:
                if await loc.count() and await loc.is_visible():
                    await loc.click()
                    await page.wait_for_timeout(250)
                    return
            except Exception:
                pass

    async def _open_search_panel(self, page: Page):
        # TimesJobs shows the search surface in a lightbox/overlay from My Home.
        fields = page.get_by_placeholder(re.compile(r"Enter Skills, Designation, etc", re.I)).first
        if await fields.count() and await fields.is_visible():
            return
        for loc in (
            page.get_by_role("button", name=re.compile(r"^Search$", re.I)).first,
            page.locator("input[placeholder*='Search' i]").first,
            page.locator("a").filter(has_text=re.compile(r"^Search$", re.I)).first,
        ):
            try:
                if await loc.count() and await loc.is_visible():
                    await loc.click()
                    await page.wait_for_timeout(500)
                    if await fields.count() and await fields.is_visible():
                        return
            except Exception:
                continue

    async def _search_role(self, page: Page, role: str):
        if "timesjobs.com" not in (page.url or "").lower():
            await page.goto(HOME, wait_until="domcontentloaded")
            await page.wait_for_timeout(800)
        await self._accept_cookies(page)
        await self._open_search_panel(page)

        role_box = page.get_by_placeholder(re.compile(r"Enter Skills, Designation, etc", re.I)).first
        if not await role_box.count():
            raise RuntimeError("TimesJobs skill/designation search field not found.")
        await role_box.fill(role)

        if self.preferred_locations:
            location_box = page.get_by_placeholder(re.compile(r"Enter locations?", re.I)).first
            if await location_box.count():
                await location_box.fill(self.preferred_locations[0])

        # Leave experience at the site's default unless a selectable control is available.
        find_button = page.get_by_role("button", name=re.compile(r"Let's Find", re.I)).first
        if not await find_button.count():
            find_button = page.locator("button").filter(has_text=re.compile(r"Let's Find", re.I)).first
        if not await find_button.count():
            raise RuntimeError("TimesJobs 'Let's Find' button not found.")
        await find_button.click()
        await page.wait_for_timeout(1600)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        print(f"TIMESJOBS SEARCH: {role} -> {page.url}")

    async def _process_current_or_results(self, context: BrowserContext, page: Page):
        if self._is_job_detail(page.url):
            await self._process_job_page(context, page)
            return

        for page_number in range(1, self.max_search_pages_per_role + 1):
            await self._process_current_results_page(context, page, page_number)

            if self.applied >= self.target_applications or self.processed >= self.max_total_candidates:
                print(
                    f"TIMESJOBS PAGINATION STOP: candidate/application cap reached "
                    f"on page {page_number}"
                )
                break

            moved = await self._click_next_search_page(page)
            if not moved:
                print(
                    f"TIMESJOBS PAGINATION END: no usable Next page after page {page_number}"
                )
                break

            print(f"TIMESJOBS PAGINATION: moved to page {page_number + 1}")

    async def _process_current_results_page(
        self, context: BrowserContext, page: Page, page_number: int
    ):
        urls = await self._collect_job_urls(page)
        if not urls:
            await page.wait_for_timeout(1200)
            urls = await self._collect_job_urls(page)
        print(
            f"TIMESJOBS RESULTS PAGE {page_number}: "
            f"{len(urls)} job links discovered"
        )

        # V40 contract: keep one dedicated TimesJobs job-detail tab for the
        # candidate loop instead of allocating one persistent tab per URL.
        # If an application flow converts that tab into an application surface,
        # preserve it and allocate a replacement dedicated job tab only for the
        # remaining candidates. External popups remain independently owned.
        job_page = await context.new_page()
        preserved_application_pages: list[Page] = []
        try:
            for url in urls:
                if self.applied >= self.target_applications or self.processed >= self.max_total_candidates:
                    break
                key = self._canonical(url)
                if key in self._seen_this_run:
                    continue
                self._seen_this_run.add(key)
                if seen(self.db, url):
                    self.skipped += 1
                    print(f"TIMESJOBS DB DEDUP -> already processed: {url}")
                    continue

                if job_page.is_closed():
                    job_page = await context.new_page()
                keep_open = False
                try:
                    await job_page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await job_page.wait_for_timeout(700)
                    keep_open = await self._process_job_page(context, job_page)
                except Exception as exc:
                    self.errors += 1
                    print(f"TIMESJOBS JOB ERROR [{url}]: {type(exc).__name__}: {exc}")
                finally:
                    # Reuse the TimesJobs job-detail tab whenever it remains a
                    # TimesJobs page. If an application occupies the tab, preserve
                    # that state and allocate exactly one replacement for the loop.
                    try:
                        current_url = (job_page.url or "").lower()
                    except Exception:
                        current_url = ""
                    still_timesjobs = "timesjobs.com" in current_url
                    if keep_open and not still_timesjobs and not job_page.is_closed():
                        preserved_application_pages.append(job_page)
                        job_page = await context.new_page()
        finally:
            if not job_page.is_closed():
                await job_page.close()

    async def _search_page_fingerprint(self, page: Page) -> tuple[str, ...]:
        """Capture current result URLs so pagination can be verified even when
        the current page has no eligible jobs."""
        try:
            values = await page.locator("a[href*='/job-detail/']").evaluate_all(
                "els => els.map(a => a.href || '').filter(Boolean)"
            )
        except Exception:
            return ()
        return tuple(dict.fromkeys(self._canonical(str(value)) for value in values if value))

    async def _click_next_search_page(self, page: Page, timeout_ms: int = 12000) -> bool:
        """Advance using the real TimesJobs pagination button and verify new results."""
        before_url = page.url
        before_fingerprint = await self._search_page_fingerprint(page)

        candidates = (
            page.locator("button.pagination-next").first,
            page.locator("button[class*='pagination-next']").first,
            page.get_by_role("button", name=re.compile(r"next", re.I)).first,
        )
        next_button = None
        for loc in candidates:
            try:
                if await loc.count() and await loc.is_visible():
                    next_button = loc
                    break
            except Exception:
                continue

        if next_button is None:
            return False

        try:
            if await next_button.is_disabled():
                return False
        except Exception:
            pass

        try:
            await next_button.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass

        try:
            await next_button.click(timeout=8000)
        except PlaywrightTimeoutError:
            try:
                await next_button.evaluate("element => element.click()")
            except Exception:
                return False
        except Exception:
            try:
                await next_button.evaluate("element => element.click()")
            except Exception:
                return False

        deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000.0)
        while asyncio.get_running_loop().time() < deadline:
            await page.wait_for_timeout(500)
            try:
                current_fingerprint = await self._search_page_fingerprint(page)
                current_url = page.url
                if current_fingerprint and current_fingerprint != before_fingerprint:
                    return True
                if current_url != before_url and current_fingerprint != before_fingerprint:
                    return True
            except Exception:
                pass

        print("TIMESJOBS PAGINATION WARNING: Next button clicked but results did not change")
        return False

    async def _process_job_page(self, context: BrowserContext, page: Page) -> bool:
        url = self._canonical(page.url)
        if "timesjobs.com" not in url:
            return False

        await self._accept_cookies(page)
        title = await self._first_text(page, ["h1", "h2", "[class*='jobtitle' i]", "[class*='job-title' i]"])
        company = await self._company_text(page, title)
        body = await page.locator("body").inner_text(timeout=7000)
        location = self._extract_location(body)
        experience = self._extract_experience(body)
        description = self._extract_description(body)
        if not title:
            title = self._title_from_url(page.url)
        if not title:
            raise RuntimeError("TimesJobs job title could not be extracted.")

        # TimesJobs can expose Apply on the job page even when the actual form is external.
        applied = await self._is_applied(page)
        if applied:
            self.processed += 1
            app(self.db, page.url, title, "already_applied", company, location, description, None, False, [])
            print(f"TIMESJOBS ALREADY APPLIED: {title}")
            return False

        match = self.matcher.match(title, f"{experience}\n{location}\n{description}\n{body}")
        if not match.get("eligible"):
            self.processed += 1
            self.skipped += 1
            app(self.db, page.url, title, "low_match", company, location, description, match.get("score"), False, match.get("matched_skills", []))
            print(f"TIMESJOBS SKIP: {title} score={match.get('score')} reasons={match.get('rejection_reasons')}")
            return False

        print(f"TIMESJOBS ELIGIBLE: {title} score={match.get('score')} track={match.get('match_track')}")
        resume_path = None
        try:
            from resume_integration import build_tailored_resume
            resume_path = build_tailored_resume(
                profile_path=str(self.platform_dir.parent.parent / "profile.json"),
                title=title, jd_text=body, platform="timesjobs", job_url=url, company=company
            )
        except Exception as exc:
            print(f"TIMESJOBS RESUME TAILORING WARNING: {type(exc).__name__}: {exc}")
        result = await self._apply_timesjobs(context, page, title, resume_path=resume_path)
        status = result["status"]
        self.processed += 1
        app(self.db, page.url, title, status, company, location, description, match.get("score"), True, match.get("matched_skills", []))
        if status in {"applied", "external_submitted"}:
            self.applied += 1
            print(f"TIMESJOBS APPLIED: {title} -> {status}")
        else:
            self.errors += 1
            print(f"TIMESJOBS APPLY STATUS: {title} -> {status}")
        return status in {"applied", "external_submitted", "external_filled", "ready_to_submit", "external_blocked", "external_partial", "external_error", "application_error", "submission_unconfirmed"}

    async def _apply_timesjobs(self, context: BrowserContext, page: Page, title: str, resume_path: str | None = None) -> dict:
        external_control = await ApplicationFlow.find_apply(page, external_only=True)
        is_external = external_control is not None
        if external_control is None:
            external_control = await ApplicationFlow.find_apply(page, native_only=True)
        if external_control is None:
            return {"status": "apply_not_found"}

        label = await ApplicationFlow.label(page, external_control)
        pages_before = set(context.pages)
        try:
            await external_control.scroll_into_view_if_needed()
            await external_control.click(timeout=10000)
        except Exception as exc:
            print(f"TIMESJOBS APPLY CLICK ERROR [{title}]: {type(exc).__name__}: {exc}")
            return {"status": "apply_click_failed"}

        if is_external:
            active = await ApplicationFlow.wait_for_destination(
                context, page, pages_before, ("timesjobs.com",), timeout_ms=60000
            )
            if active is None:
                return {"status": "external_apply_not_reached"}
            if not self.allow_external:
                return {"status": "external_blocked"}
            print(f"TIMESJOBS EXTERNAL APPLY: {active.url}")
            try:
                # Current project default is supervised/dry-run; the page remains open
                # when final submission is not confirmed.
                dry_run = str(os.environ.get("TIMESJOBS_DRY_RUN", "true")).strip().lower() not in {"0", "false", "no"}
                profile_path = str(self.platform_dir / "profile.json")
                result = await ApplicationFlow.run_company_site_form(active, profile_path, resume_path, dry_run=dry_run)
            except Exception as exc:
                print(f"TIMESJOBS EXTERNAL ENGINE ERROR: {type(exc).__name__}: {exc}")
                return {"status": "external_error"}
            state = str((result or {}).get("status", "FAILED")).upper()
            if state in {"SUBMITTED", "SUCCESS", "APPLIED"} and not dry_run:
                return {"status": "external_submitted"}
            if state in {"READY_TO_SUBMIT", "EXTERNAL_FILLED"} or dry_run:
                return {"status": "external_filled"}
            if state in {"CAPTCHA_REQUIRED", "HUMAN_INTERVENTION", "SECURITY_CHECK", "LOGIN_REQUIRED"}:
                return {"status": "external_blocked"}
            return {"status": "external_partial"}

        if await self._wait_for_applied(page, attempts=20):
            return {"status": "applied"}
        if await ApplicationFlow.wait_for_application_surface(page, timeout_ms=25000):
            try:
                dry_run = str(os.environ.get("TIMESJOBS_DRY_RUN", "true")).strip().lower() not in {"0", "false", "no"}
                profile_path = str(self.platform_dir / "profile.json")
                result = await ApplicationFlow.run_company_site_form(page, profile_path, resume_path, dry_run=dry_run)
                state = str((result or {}).get("status", "FAILED")).upper()
                if state in {"READY_TO_SUBMIT", "EXTERNAL_FILLED"} or dry_run:
                    return {"status": "ready_to_submit"}
            except Exception as exc:
                print(f"TIMESJOBS NATIVE FORM ENGINE ERROR: {type(exc).__name__}: {exc}")
                return {"status": "application_error"}
        return {"status": "submission_unconfirmed"}

    async def _collect_job_urls(self, page: Page) -> list[str]:
        hrefs = await page.locator("a[href*='/job-detail/']").evaluate_all(
            "els => els.map(a => a.href).filter(Boolean)"
        )
        out: list[str] = []
        seen_local: set[str] = set()
        for href in hrefs:
            if "timesjobs.com" not in href.lower():
                continue
            key = self._canonical(href)
            if not re.search(r"timesjobs\.com/job-detail/[^/?#]+", key, re.I):
                continue
            if key not in seen_local:
                seen_local.add(key)
                out.append(href)
        return out

    async def _is_applied(self, page: Page) -> bool:
        for loc in (
            page.get_by_role("button", name=re.compile(r"^Applied$", re.I)).first,
            page.get_by_text(re.compile(r"^Applied$", re.I)).first,
        ):
            try:
                if await loc.count() and await loc.is_visible():
                    return True
            except Exception:
                pass
        return False

    async def _wait_for_applied(self, page: Page, attempts: int = 8) -> bool:
        for _ in range(attempts):
            if await self._is_applied(page):
                return True
            await page.wait_for_timeout(500)
        return False

    async def _first_text(self, page: Page, selectors: list[str]) -> str:
        for selector in selectors:
            loc = page.locator(selector).first
            try:
                if await loc.count():
                    text = (await loc.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    async def _company_text(self, page: Page, title: str) -> str:
        text = await self._first_text(page, ["[class*='company' i]", "a[href*='company' i]", "h1 + *"])
        if text and text.strip().lower() != title.strip().lower():
            return text.strip()
        return ""

    @staticmethod
    def _extract_experience(body: str) -> str:
        patterns = [
            r"\b\d+\s*(?:to|-|–)\s*\d+\s*(?:Yrs?|Years?)\b",
            r"\bExperience\s*:\s*[^\n]+",
        ]
        for pattern in patterns:
            m = re.search(pattern, body, re.I)
            if m:
                return m.group(0)
        return ""

    @staticmethod
    def _extract_location(body: str) -> str:
        lines = [x.strip() for x in body.splitlines() if x.strip()]
        for line in lines:
            if any(token in line.lower() for token in (
                "hyderabad", "secunderabad", "bengaluru", "bangalore", "chennai", "mumbai",
                "delhi", "pune", "kolkata", "noida", "greater noida", "gurgaon", "gurugram"
            )) and len(line) < 180:
                return line
        return ""

    @staticmethod
    def _extract_description(body: str) -> str:
        m = re.search(r"JOB DESCRIPTION", body, re.I)
        if m:
            return body[m.end(): m.end() + 15000].strip()
        return body[:15000].strip()

    @staticmethod
    def _title_from_url(url: str) -> str:
        m = re.search(r"/job-detail/([^/?#]+)", url, re.I)
        return m.group(1).replace("-", " ").strip().title() if m else ""

    @staticmethod
    def _is_job_detail(url: str) -> bool:
        return bool(re.search(r"timesjobs\.com/job-detail/[^/?#]+", url or "", re.I))

    @staticmethod
    def _canonical(url: str) -> str:
        return (url or "").split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()
