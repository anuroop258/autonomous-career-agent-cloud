import asyncio
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import Page, BrowserContext, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parents[2]
PLATFORM_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from jd_matcher import JDMatcher
from storage import app, db, seen
from platforms.common.application_flow import ApplicationFlow

BASE = "https://www.shine.com"
DASHBOARD = f"{BASE}/dashboard"


class ShineAgent:
    """Deterministic Shine native-Apply adapter based on the supplied UI flow."""

    def __init__(self, root_dir: Path = ROOT, platform_dir: Path = PLATFORM_DIR):
        self.root_dir = Path(root_dir)
        self.platform_dir = Path(platform_dir)
        self.config = json.loads((self.platform_dir / "role_config.json").read_text(encoding="utf-8"))
        self.target_direct_applications = int(self.config.get("target_direct_applications", 10))
        self.max_search_pages_per_role = int(self.config.get("max_search_pages_per_role", 5))
        self.max_total_candidates = int(self.config.get("max_total_candidates", 1000))
        self.preferred_locations = [str(x).strip() for x in self.config.get("preferred_locations", []) if str(x).strip()]
        self.roles = [str(x).strip() for x in self.config.get("primary", []) if str(x).strip()]
        self.db = db()
        self.matcher = JDMatcher(self.root_dir)
        self.direct_applications = 0
        self.processed_candidates = 0
        self.skipped_candidates = 0
        self.errors = 0
        self._seen_this_run = set()

    async def run(self, context: BrowserContext, target: str | None = None):
        page = await self._get_shine_page(context)
        if target:
            await page.goto(target, wait_until="domcontentloaded")
            await page.wait_for_timeout(1200)
            await self._process_current_or_results(context, page)
            return

        for role in self.roles:
            if self.direct_applications >= self.target_direct_applications:
                break
            if self.processed_candidates >= self.max_total_candidates:
                break
            try:
                await self._search_role(page, role)
                await self._process_current_or_results(context, page)
            except Exception as exc:
                self.errors += 1
                print(f"SHINE ROLE ERROR [{role}]: {type(exc).__name__}: {exc}")

    async def _get_shine_page(self, context: BrowserContext) -> Page:
        for page in context.pages:
            if page.is_closed():
                continue
            if "shine.com" in (page.url or "").lower():
                return page
        page = await context.new_page()
        await page.goto(DASHBOARD, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)
        return page

    async def _search_role(self, page: Page, role: str):
        if "shine.com" not in (page.url or "").lower():
            await page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(800)

        role_box = page.locator('input[placeholder="Enter Skills/Roles"]').first
        if not await role_box.count():
            role_box = page.locator('input[placeholder*="Skills/Roles" i]').first

        # Results pages can keep the search form collapsed behind Edit search.
        # Re-open that form before falling back to the dashboard.
        if not await role_box.count() or not await role_box.is_visible():
            edit = page.get_by_role("button", name=re.compile(r"^Edit search$", re.I)).first
            if not await edit.count():
                edit = page.get_by_text(re.compile(r"^Edit search$", re.I)).first
            try:
                if await edit.count() and await edit.is_visible():
                    await edit.click(timeout=5000)
                    await page.wait_for_timeout(500)
            except Exception:
                pass
            role_box = page.locator('input[placeholder="Enter Skills/Roles"]').first
            if not await role_box.count():
                role_box = page.locator('input[placeholder*="Skills/Roles" i]').first

        if not await role_box.count():
            await page.goto(DASHBOARD, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(800)
            role_box = page.locator('input[placeholder="Enter Skills/Roles"]').first
            if not await role_box.count():
                role_box = page.locator('input[placeholder*="Skills/Roles" i]').first
        if not await role_box.count():
            raise RuntimeError("Shine search role field not found after dashboard/Edit search recovery.")

        await role_box.fill(role)
        await self._select_fresher_experience(page)

        if self.preferred_locations:
            location_box = page.locator('input[placeholder*="Location" i]').first
            if await location_box.count() and await location_box.is_visible():
                await location_box.fill(self.preferred_locations[0])

        search_button = page.get_by_role("button", name=re.compile(r"^Search$", re.I)).first
        if not await search_button.count():
            search_button = page.locator("button").filter(has_text=re.compile(r"^Search$", re.I)).first
        if not await search_button.count():
            raise RuntimeError("Shine Search button not found.")
        await search_button.click(timeout=10000)
        await page.wait_for_timeout(1600)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        print(f"SHINE SEARCH: {role} -> {page.url}")

    async def _select_fresher_experience(self, page: Page) -> bool:
        """Ensure Shine's search experience filter is set to the exact ``0 Yr`` option.

        Shine has rendered this as a custom dropdown in the supplied UI capture;
        some site variants may expose it as a native <select>. Never choose by
        option index, because the option order can change.
        """
        # Prefer a native select when the page exposes one.
        selects = page.locator("select")
        for index in range(await selects.count()):
            select = selects.nth(index)
            try:
                labels = await select.locator("option").all_text_contents()
                exact_zero = next((label.strip() for label in labels if re.fullmatch(r"0\s*Yr", label.strip(), re.I)), None)
                if exact_zero is not None:
                    await select.select_option(label=exact_zero, timeout=3000)
                    print("SHINE EXPERIENCE FILTER: selected 0 Yr (native select)")
                    return True
            except Exception:
                continue

        # Custom dropdown: the selected value is the trigger; its popup option
        # is another exact ``0 Yr`` text node. If popup already open, use it.
        option = page.get_by_role("option", name=re.compile(r"^0\s*Yr$", re.I)).first
        try:
            if await option.count() and await option.is_visible():
                await option.click(timeout=3000)
                print("SHINE EXPERIENCE FILTER: selected 0 Yr (custom option)")
                return True
        except Exception:
            pass

        exact_zero = page.get_by_text(re.compile(r"^0\s*Yr$", re.I)).filter(visible=True)
        try:
            count = await exact_zero.count()
            if count == 0:
                print("SHINE EXPERIENCE FILTER: control not found; left filter unchanged")
                return False
            if count == 1:
                # Usually the currently displayed value opens the dropdown.
                await exact_zero.first.click(timeout=3000)
                await page.wait_for_timeout(150)
                exact_zero = page.get_by_text(re.compile(r"^0\s*Yr$", re.I)).filter(visible=True)
                count = await exact_zero.count()
            # With the popup open, the later exact match is the menu item;
            # do not toggle the currently selected field value.
            if count >= 2:
                await exact_zero.nth(count - 1).click(timeout=3000)
            print("SHINE EXPERIENCE FILTER: 0 Yr is selected/confirmed")
            return True
        except Exception as exc:
            print(f"SHINE EXPERIENCE FILTER: could not confirm 0 Yr: {type(exc).__name__}: {exc}")
            return False

    async def _process_current_or_results(self, context: BrowserContext, page: Page):
        if self._is_job_detail(page.url):
            await self._process_job_page(page)
            return

        visited_pages: set[str] = set()
        for page_index in range(1, self.max_search_pages_per_role + 1):
            page_key = self._canonical(page.url)
            if page_key in visited_pages:
                print(f"SHINE PAGINATION STOP: repeated search page {page.url}")
                break
            visited_pages.add(page_key)
            print(f"SHINE SEARCH PAGE {page_index}/{self.max_search_pages_per_role}: {page.url}")

            candidates = await self._collect_job_candidates(page)
            if not candidates:
                await page.wait_for_timeout(1000)
                candidates = await self._collect_job_candidates(page)

            print(
                f"SHINE RESULT EXPERIENCE PREFILTER: discovered={len(candidates)} "
                f"open_candidates={sum(1 for item in candidates if item['eligible_experience'])} "
                f"skipped={sum(1 for item in candidates if not item['eligible_experience'])}"
            )

            for candidate in candidates:
                url = candidate["url"]
                if not candidate["eligible_experience"]:
                    self.skipped_candidates += 1
                    print(
                        f"SHINE RESULT SKIP BEFORE OPEN: {candidate.get('card_text') or candidate.get('title') or url} "
                        f"-> result card experience={candidate.get('experience') or 'unknown'}"
                    )
                    continue
                if self.direct_applications >= self.target_direct_applications or self.processed_candidates >= self.max_total_candidates:
                    break
                key = self._canonical(url)
                if key in self._seen_this_run:
                    continue
                self._seen_this_run.add(key)
                if seen(self.db, url):
                    self.skipped_candidates += 1
                    print(f"SHINE DB DEDUP -> already processed: {url}")
                    continue

                job_page = await context.new_page()
                keep_open = False
                try:
                    await job_page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await job_page.wait_for_timeout(700)
                    keep_open = bool(await self._process_job_page(job_page))
                except Exception as exc:
                    self.errors += 1
                    print(f"SHINE JOB ERROR [{url}]: {type(exc).__name__}: {exc}")
                finally:
                    if not keep_open and not job_page.is_closed():
                        await job_page.close()

            if self.direct_applications >= self.target_direct_applications or self.processed_candidates >= self.max_total_candidates:
                break
            next_url = await self._next_search_page_url(page)
            if not next_url:
                print("SHINE PAGINATION END: no Next page target")
                break
            next_key = self._canonical(next_url)
            if next_key in visited_pages:
                print(f"SHINE PAGINATION STOP: Next page already visited {next_url}")
                break
            print(f"SHINE NEXT PAGE: {next_url}")
            await page.goto(next_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1000)

    async def _next_search_page_url(self, page: Page) -> str | None:
        candidates = [
            page.locator('a[rel="next"]').first,
            page.locator('a[aria-label="Next page"]').first,
            page.get_by_role("link", name=re.compile(r"^Next(?: page)?$", re.I)).first,
            page.locator('a[class*="pagination_is-nav"]').filter(has_text=re.compile(r"^Next$", re.I)).first,
        ]
        for loc in candidates:
            try:
                if await loc.count() and await loc.is_visible():
                    href = await loc.get_attribute("href")
                    if href:
                        return str(href) if str(href).startswith("http") else f"{BASE}{href}"
            except Exception:
                continue
        return None

    async def _process_job_page(self, page: Page) -> bool:
        url = self._canonical(page.url)
        if "shine.com" not in page.url.lower():
            return False
        title = await self._first_text(page, ["h1", "h2", "[data-testid*='title' i]"])
        company = await self._company_text(page, title)
        body = await page.locator("body").inner_text(timeout=5000)
        location = self._extract_location(body)
        experience = self._extract_experience(body)
        description = self._extract_description(body)
        if not title:
            title = self._title_from_url(page.url)
        if not title:
            raise RuntimeError("Shine job title could not be extracted.")

        if await self._is_applied(page):
            self.processed_candidates += 1
            app(self.db, page.url, title, "already_applied", company, location, description, None, False, [])
            print(f"SHINE ALREADY APPLIED: {title}")
            return False

        match = self.matcher.match(title, f"{experience}\n{location}\n{description}\n{body}")
        print(f"SHINE JD MATCH: {match.get('score')}/{match.get('threshold')} | eligible={match.get('eligible')}")
        if not match.get("eligible"):
            self.processed_candidates += 1
            self.skipped_candidates += 1
            app(self.db, page.url, title, "low_match", company, location, description, match.get("score"), False, match.get("matched_skills", []))
            return False

        resume_path = None
        try:
            from resume_integration import build_tailored_resume
            resume_path = build_tailored_resume(
                profile_path=str(self.root_dir / "profile.json"), title=title, jd_text=body,
                platform="shine", job_url=url, company=company
            )
        except Exception as exc:
            print(f"SHINE RESUME TAILORING WARNING: {type(exc).__name__}: {exc}")

        # Detect external/company-site Apply before native Apply.
        external_control = await ApplicationFlow.find_apply(page, external_only=True)
        if not bool(self.config.get("allow_external_company_apply", True)):
            external_control = None
        control = external_control or await ApplicationFlow.find_apply(page, native_only=True)
        if control is None:
            self.processed_candidates += 1
            self.errors += 1
            app(self.db, page.url, title, "apply_not_found", company, location, description, match.get("score"), True, match.get("matched_skills", []))
            print(f"SHINE APPLY NOT FOUND: {title}")
            return False

        pages_before = set(page.context.pages)
        try:
            await control.scroll_into_view_if_needed()
            await control.click(timeout=10000)
        except Exception as exc:
            self.processed_candidates += 1
            self.errors += 1
            app(self.db, page.url, title, "apply_click_failed", company, location, description, match.get("score"), True, match.get("matched_skills", []))
            print(f"SHINE APPLY CLICK FAILED: {type(exc).__name__}: {exc}")
            return True

        # Resolve whether Apply navigated to a new company/ATS page.
        active = page
        external = bool(external_control)
        if external:
            active = await ApplicationFlow.wait_for_destination(
                page.context, page, pages_before, ("shine.com",), timeout_ms=60000
            )
            if active is None:
                status = "external_apply_not_reached"
            else:
                try:
                    result = await ApplicationFlow.run_company_site_form(
                        active, str(self.root_dir / "profile.json"),
                        str(resume_path) if resume_path else None,
                        dry_run=True,
                    )
                    state = str((result or {}).get("status", "FAILED")).upper()
                    status = {
                        "SUBMITTED": "external_submitted", "SUCCESS": "external_submitted",
                        "APPLIED": "external_submitted", "READY_TO_SUBMIT": "external_filled",
                        "EXTERNAL_FILLED": "external_filled", "CAPTCHA_REQUIRED": "external_blocked",
                        "HUMAN_INTERVENTION": "external_blocked", "SECURITY_CHECK": "external_blocked",
                        "LOGIN_REQUIRED": "external_blocked",
                    }.get(state, "external_partial")
                except Exception as exc:
                    print(f"SHINE EXTERNAL ENGINE ERROR: {type(exc).__name__}: {exc}")
                    status = "external_error"
        else:
            # Native Shine Apply can render a modal or replace the detail surface.
            if await self._wait_for_applied(page, attempts=20):
                status = "applied"
            elif await ApplicationFlow.wait_for_application_surface(active, timeout_ms=25000):
                try:
                    result = await ApplicationFlow.run_company_site_form(
                        active, str(self.root_dir / "profile.json"),
                        str(resume_path) if resume_path else None,
                        dry_run=True,
                    )
                    state = str((result or {}).get("status", "FAILED")).upper()
                    status = "ready_to_submit" if state in {"READY_TO_SUBMIT", "EXTERNAL_FILLED"} else "application_error"
                except Exception as exc:
                    print(f"SHINE NATIVE FORM ENGINE ERROR: {type(exc).__name__}: {exc}")
                    status = "application_error"
            else:
                status = "submission_unconfirmed"

        self.processed_candidates += 1
        app(self.db, page.url, title, status, company, location, description, match.get("score"), True, match.get("matched_skills", []))
        if status in {"applied", "external_submitted"}:
            self.direct_applications += 1
            print(f"SHINE APPLY CONFIRMED: {title} -> {status}")
        else:
            self.errors += 1
            print(f"SHINE APPLY STATUS: {title} -> {status}")
        return True

    async def _collect_job_candidates(self, page: Page) -> list[dict]:
        """Collect result-card metadata and prefilter fresher eligibility before opening any job tab."""
        anchors = page.locator("a[href*='/jobs/']")
        raw = await anchors.evaluate_all(
            r"""els => els.map(a => {
                let node = a;
                let cardText = (a.innerText || '').trim();
                let experience = '';
                for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
                    const expNodes = Array.from(node.querySelectorAll('.job-card-line-text, [class*="job-card-line-text"]'));
                    const exp = expNodes.map(x => (x.innerText || x.textContent || '').trim())
                        .find(t => /(?:freshers?|\d+(?:\.\d+)?\s*(?:to|-|–|—)\s*\d+(?:\.\d+)?\s*(?:yrs?|years?)|\d+(?:\.\d+)?\s*(?:yrs?|years?))/i.test(t));
                    if (exp) {
                        experience = exp;
                        cardText = (node.innerText || node.textContent || '').trim();
                        break;
                    }
                }
                return { href: a.href || '', title: (a.innerText || '').trim(), experience, cardText };
            }).filter(x => x.href)"""
        )
        out = []
        seen_keys = set()
        for item in raw:
            href = str(item.get("href") or "").strip()
            if not self._is_shine_job_url(href):
                continue
            key = self._canonical(href)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            experience = str(item.get("experience") or "").strip()
            out.append({
                "url": href,
                "title": str(item.get("title") or "").strip(),
                "experience": experience,
                "card_text": " ".join(str(item.get("cardText") or "").split()),
                "eligible_experience": self._is_fresher_experience_eligible(experience),
            })
        return out

    async def _collect_job_urls(self, page: Page) -> list[str]:
        """Compatibility wrapper retained for callers/tests; returns only prefiltered URLs."""
        return [item["url"] for item in await self._collect_job_candidates(page) if item["eligible_experience"]]

    @classmethod
    def _parse_experience_range(cls, text: str) -> tuple[float, float] | None:
        value = re.sub(r"\s+", " ", (text or "").strip())
        if not value:
            return None
        if re.search(r"\bfreshers?\b", value, re.I):
            return (0.0, 0.0)
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:to|-|–|—)\s*(\d+(?:\.\d+)?)\s*(?:yrs?|years?)\b", value, re.I)
        if m:
            return (float(m.group(1)), float(m.group(2)))
        m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:yrs?|years?)\b", value, re.I)
        if m:
            n = float(m.group(1))
            return (n, n)
        if re.fullmatch(r"0\s*yr", value, re.I):
            return (0.0, 0.0)
        return None

    @classmethod
    def _is_fresher_experience_eligible(cls, text: str, max_years: int = 3) -> bool:
        parsed = cls._parse_experience_range(text)
        if parsed is None:
            return False
        minimum, maximum = parsed
        return minimum == 0 and maximum <= float(max_years)

    @staticmethod
    def _is_shine_job_url(url: str) -> bool:
        """Return True for Shine job-detail URLs, including the job-id segment."""
        return bool(
            re.match(
                r"^https?://(?:www\.)?shine\.com/jobs/[^/?#]+/[^/?#]+(?:/[^/?#]+)?/?(?:\?.*)?$",
                url or "",
                re.I,
            )
        )

    async def _click_apply(self, page: Page) -> bool:
        candidates = [
            page.get_by_role("button", name=re.compile(r"^Apply$", re.I)).first,
            page.locator("button").filter(has_text=re.compile(r"^Apply$", re.I)).first,
            page.locator("a").filter(has_text=re.compile(r"^Apply$", re.I)).first,
        ]
        for loc in candidates:
            try:
                if await loc.count() and await loc.is_visible():
                    await loc.scroll_into_view_if_needed()
                    await loc.click()
                    await page.wait_for_timeout(1200)
                    return True
            except Exception:
                continue
        return False

    async def _wait_for_applied(self, page: Page, attempts: int = 8) -> bool:
        for _ in range(attempts):
            if await self._is_applied(page):
                return True
            await page.wait_for_timeout(500)
        return False

    async def _is_applied(self, page: Page) -> bool:
        selectors = [
            page.get_by_role("button", name=re.compile(r"^Applied$", re.I)).first,
            page.locator("button").filter(has_text=re.compile(r"^Applied$", re.I)).first,
            page.get_by_text(re.compile(r"^Applied$", re.I)).first,
        ]
        for loc in selectors:
            try:
                if await loc.count() and await loc.is_visible():
                    return True
            except Exception:
                pass
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
        text = await self._first_text(page, ["a[href*='/company/']", "[class*='company' i]", "h1 + *"])
        if text and text.strip().lower() != title.strip().lower():
            return text.strip()
        return ""

    @staticmethod
    def _extract_experience(body: str) -> str:
        m = re.search(r"\b\d+\s*(?:to|-|–)\s*\d+\s*(?:Yrs?|Years?)\b", body, re.I)
        return m.group(0) if m else ""

    @staticmethod
    def _extract_location(body: str) -> str:
        for line in body.splitlines():
            value = line.strip()
            if value and re.fullmatch(r"[A-Za-z .&'/-]{2,40}", value) and value.lower() not in {"job details", "key highlights", "job description"}:
                if any(tok in value.lower() for tok in ("bengaluru", "bangalore", "hyderabad", "chennai", "mumbai", "delhi", "pune", "kolkata", "noida", "gurgaon", "gurugram", "thoothukudi")):
                    return value
        return ""

    @staticmethod
    def _extract_description(body: str) -> str:
        marker = re.search(r"JOB DESCRIPTION", body, re.I)
        if marker:
            tail = body[marker.end():]
            return tail[:12000].strip()
        return body[:12000].strip()

    @staticmethod
    def _title_from_url(url: str) -> str:
        m = re.search(r"/jobs/([^/?#]+)/", url, re.I)
        if not m:
            return ""
        return m.group(1).replace("-", " ").strip().title()

    @staticmethod
    def _is_job_detail(url: str) -> bool:
        return bool(re.search(r"shine\.com/jobs/[^/?#]+/", url or "", re.I))

    @staticmethod
    def _canonical(url: str) -> str:
        value = (url or "").split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()
        return value
