from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jd_matcher import JDMatcher
from src.application.common.profile_reasoner import ProfileReasoner
from storage import db, seen, app, qa
from src.application.common.company_website_agent import CompanyWebsiteAgent

BASE = "https://www.linkedin.com"



class LinkedInAgent:
    """LinkedIn adapter using the same deterministic flow as the Naukri agent."""

    def __init__(self):
        self.base_dir = Path(__file__).resolve().parent
        self.cfg = self._load_json(self.base_dir / "linkedin_config.json", {})
        self.profile = self._load_json(self.base_dir / "profile.json", {})
        self.con = db()
        self.matcher = JDMatcher(str(self.base_dir))
        self.reasoner = ProfileReasoner()

        self.dry_run = os.getenv("LINKEDIN_DRY_RUN", "true").lower() not in {"0", "false", "no", "off"}
        self.target_applications = int(self.cfg.get("target_native_applications", 20))
        self.max_pages = int(self.cfg.get("max_search_pages", 10))
        self.max_candidates = int(self.cfg.get("max_total_candidates", 1000))
        self.seen_urls: set[str] = set()
        self.native_applications = 0
        self.external_filled = 0
        self.external_submitted = 0
        self.low_match = 0
        self.errors = 0
        self._search_page = None
        self.current_resume_path = None
        self._current_question_control = None
        self._current_question_kind = ""

    @staticmethod
    def _load_json(path: Path, default: dict) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    def fingerprint(self, url: str) -> str:
        return (url or "").split("?", 1)[0].split("#", 1)[0].rstrip("/").lower()

    async def record(self, url: str, title: str, status: str, company: str = "", description: str = "", match: dict | None = None):
        try:
            match = match or {}
            app(
                self.con,
                self.fingerprint(url),
                title,
                status,
                company=company,
                description=description,
                match_score=match.get("score"),
                eligible=match.get("eligible"),
                matched_skills=match.get("matched_skills") or [],
            )
        except Exception as exc:
            print(f"  DB RECORD WARNING: {exc}")

    async def wait_stable(self, page: Page):
        try:
            await page.wait_for_timeout(900)
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass

    async def is_logged_in(self, page: Page) -> bool:
        try:
            body = re.sub(r"\s+", " ", await page.locator("body").inner_text(timeout=5000)).lower()
            if any(x in body for x in ("sign in", "join linkedin", "new to linkedin?")):
                return False
            return any(x in body for x in ("my jobs", "jobs", "messaging", "notifications", "me"))
        except Exception:
            return False

    async def detect_blocker(self, page: Page) -> bool:
        try:
            body = (await page.locator("body").inner_text(timeout=5000)).lower()
            return any(x in body for x in (
                "captcha", "security verification", "verify you are human",
                "unusual activity", "challenge", "confirm you are not a robot"
            ))
        except Exception:
            return False

    async def collect_job_urls(self, page: Page) -> list[str]:
        """Collect canonical job URLs only from LinkedIn search-result cards.

        Do not scan the whole page: LinkedIn can render a separate
        "Jobs you may be interested in" recommendation rail containing real
        /jobs/view links that are not part of the current search result set.
        """
        found: list[str] = []

        result_anchor_selectors = (
            "li.jobs-search-results__list-item a[href*='/jobs/view/']",
            ".jobs-search-results-list a[href*='/jobs/view/']",
            "[data-occludable-job-id] a[href*='/jobs/view/']",
            "li[data-occludable-job-id] a[href*='/jobs/view/']",
            "div.job-card-container a[href*='/jobs/view/']",
        )

        async def collect_from_result_cards() -> None:
            for selector in result_anchor_selectors:
                try:
                    anchors = await page.locator(selector).evaluate_all(
                        "els => els.map(a => a.href || '')"
                    )
                except Exception:
                    anchors = []
                for raw in anchors:
                    href = self._canonical_job_url(raw or "")
                    if href and href not in found:
                        found.append(href)
                if found:
                    return

            # Last DOM-scoped fallback: accept links whose ancestor is a known
            # search-result container, but never arbitrary page-wide /jobs/view links.
            try:
                anchors = await page.locator("a[href*='/jobs/view/']").evaluate_all(
                    """els => els.filter(a => a.closest(
                        'li.jobs-search-results__list-item,
                         .jobs-search-results-list,
                         [data-occludable-job-id],
                         li[data-occludable-job-id],
                         div.job-card-container'
                    )).map(a => a.href || '')"""
                )
            except Exception:
                anchors = []
            for raw in anchors:
                href = self._canonical_job_url(raw or "")
                if href and href not in found:
                    found.append(href)

        try:
            await page.wait_for_timeout(1200)
            await collect_from_result_cards()
        except Exception as exc:
            print(f"  JOB URL COLLECTION WARNING: {exc}")

        # LinkedIn may lazy-load the result cards; scroll and retry once.
        if not found:
            try:
                await page.mouse.wheel(0, 1800)
                await page.wait_for_timeout(1200)
                await collect_from_result_cards()
            except Exception:
                pass
        return found

    async def _no_search_results_page(self, page: Page) -> bool:
        """Return True only when LinkedIn explicitly shows an empty search state."""
        try:
            body = re.sub(r"\s+", " ", await page.locator("body").inner_text(timeout=5000)).lower()
        except Exception:
            return False
        return any(
            marker in body
            for marker in (
                "no matching jobs found",
                "no jobs found",
                "we couldn't find any jobs",
                "we couldn't find any results",
            )
        )

    @staticmethod
    def _is_resume_picker_text(text: str) -> bool:
        """Recognize LinkedIn resume-picker/file UI text, not application questions."""
        normalized = re.sub(r"\s+", " ", str(text or "")).strip().lower()
        if not normalized:
            return False
        return bool(
            re.match(r"^(select|choose|upload|attach)(?: your)?\s+(?:a\s+)?(?:resume|cv)\b", normalized)
            or re.search(r"\.(?:pdf|docx?|rtf)(?:$|\s)", normalized)
            or any(
                phrase in normalized
                for phrase in (
                    "selected resume",
                    "resume selected",
                    "change resume",
                    "replace resume",
                    "upload resume",
                    "choose resume",
                    "attach resume",
                    "select cv",
                    "upload cv",
                )
            )
        )

    @staticmethod
    def _canonical_job_url(url: str) -> str | None:
        """Accept only LinkedIn /jobs/view/<numeric-id> URLs."""
        m = re.search(r"https?://(?:www\.)?linkedin\.com/jobs/view/(\d+)", (url or "").strip(), re.I)
        if not m:
            return None
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}"

    async def _is_real_job_page(self, page: Page) -> bool:
        """Reject deleted/expired/nonexistent job pages before any Apply interaction."""
        try:
            if not self._canonical_job_url(page.url):
                return False
            body = re.sub(r"\s+", " ", await page.locator("body").inner_text(timeout=5000)).lower()
            invalid_markers = (
                "page not found", "this page doesn't exist",
                "this job is no longer available", "job is no longer available",
                "the job you are looking for is no longer available",
                "this job has expired", "no longer accepting applications",
            )
            if any(marker in body for marker in invalid_markers):
                return False
            title, company, jd = await self.extract_job(page)
            if not title or title.lower() in {"linkedin", "jobs"}:
                return False
            if not company and len(jd) < 80:
                return False
            return True
        except Exception:
            return False

    async def live_applied_state(self, page: Page) -> bool:
        """Strong live signals only; database history is deliberately ignored."""
        try:
            controls = page.locator("button:visible, a:visible, [role='button']:visible")
            for i in range(min(await controls.count(), 160)):
                el = controls.nth(i)
                vals = []
                for attr in (None, "aria-label", "title"):
                    try:
                        v = await el.inner_text() if attr is None else await el.get_attribute(attr)
                    except Exception:
                        v = ""
                    if v:
                        vals.append(re.sub(r"\s+", " ", str(v)).strip().lower())
                if any(v in {"applied", "already applied", "application submitted", "applied successfully"} for v in vals):
                    return True
            body = re.sub(r"\s+", " ", await page.locator("body").inner_text(timeout=5000)).lower()
            return any(x in body for x in (
                "you applied", "application submitted", "already applied",
                "you've applied", "your application was submitted"
            ))
        except Exception:
            return False

    async def extract_job(self, page: Page) -> tuple[str, str, str]:
        title = ""
        company = ""
        jd = ""
        for sel in ("h1", "h1.t-24", "h1.jobs-unified-top-card__job-title"):
            try:
                if await page.locator(sel).count():
                    title = (await page.locator(sel).first.inner_text()).strip()
                    if title:
                        break
            except Exception:
                pass
        for sel in (
            ".job-details-jobs-unified-top-card__company-name a",
            ".jobs-unified-top-card__company-name a",
            ".jobs-unified-top-card__company-name",
            "a[href*='/company/']:visible",
            "[data-view-name*='job-details-top-card-company' i]",
            "[data-testid*='company' i]:visible",
            "[itemprop='hiringOrganization'] [itemprop='name']:visible",
        ):
            try:
                loc = page.locator(sel)
                for i in range(min(await loc.count(), 10)):
                    candidate = (await loc.nth(i).inner_text(timeout=1500)).strip()
                    if candidate and len(candidate) <= 160 and candidate.lower() not in {'linkedin', 'jobs'}:
                        company = candidate
                        break
                if company:
                    break
            except Exception:
                pass
        if not company:
            try:
                scripts = page.locator("script[type='application/ld+json']")
                for i in range(min(await scripts.count(), 15)):
                    raw = (await scripts.nth(i).text_content() or "").strip()
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        typ = item.get("@type")
                        types = typ if isinstance(typ, list) else [typ]
                        if not any(str(t).lower() == "jobposting" for t in types if t):
                            continue
                        org = item.get("hiringOrganization") or item.get("organization") or {}
                        if isinstance(org, dict):
                            candidate = re.sub(r"\s+", " ", str(org.get("name") or "")).strip()
                            if candidate and candidate.lower() not in {"linkedin", "jobs"} and len(candidate) <= 160:
                                company = candidate
                                break
                    if company:
                        break
            except Exception:
                pass
        if not company:
            try:
                anchors = await page.locator("a[href*='/company/']").evaluate_all(
                    "els => els.map(a => (a.innerText || '').trim()).filter(Boolean).slice(0,10)"
                )
                for candidate in anchors:
                    if candidate and len(candidate) <= 160 and candidate.lower() not in {'linkedin', 'jobs'}:
                        company = candidate
                        break
            except Exception:
                pass
        for sel in (".jobs-description__content", ".jobs-box__html-content", "#job-details", ".jobs-description-content__text"):
            try:
                if await page.locator(sel).count():
                    jd = (await page.locator(sel).first.inner_text(timeout=5000)).strip()
                    if jd:
                        break
            except Exception:
                pass
        if not jd:
            try:
                jd = (await page.locator("body").inner_text(timeout=5000)).strip()
            except Exception:
                jd = ""
        if not title:
            try:
                title = (await page.title()).split("|")[0].strip()
            except Exception:
                title = page.url
        return title, company, jd

    async def detect_apply_route(self, page: Page) -> str:
        """Detect LinkedIn native Easy Apply before external Apply."""
        try:
            native_selectors = (
                "button.jobs-apply-button",
                "button[aria-label^='LinkedIn Apply to' i]",
                "[role='button'][aria-label^='LinkedIn Apply to' i]",
                "button[aria-label*='Easy Apply' i]",
                "button[data-control-name*='easy' i]",
                "button[data-testid*='easy' i]",
                "[role='button'][aria-label*='Easy Apply' i]",
                "[role='button'][data-control-name*='easy' i]",
                "[role='button'][data-testid*='easy' i]",
                "a[href*='easy-apply' i]",
                "a[aria-label*='Easy Apply' i]",
            )
            for selector in native_selectors:
                loc = page.locator(selector).filter(visible=True)
                if await loc.count():
                    return "easy_apply"

            controls = page.locator("button:visible, a:visible, [role='button']:visible")
            external_markers = (
                "apply on company site", "apply on employer site", "company website",
                "apply externally", "external application", "employer site"
            )
            for i in range(min(await controls.count(), 160)):
                el = controls.nth(i)
                try:
                    text = re.sub(r"\s+", " ", await el.inner_text()).strip().lower()
                    aria = (await el.get_attribute("aria-label") or "").lower()
                    title = (await el.get_attribute("title") or "").lower()
                    href = (await el.get_attribute("href") or "").lower()
                    desc = " ".join((text, aria, title, href))
                    if re.search(r"\beasy\s*apply\b", desc):
                        return "easy_apply"
                    if any(m in desc for m in external_markers):
                        return "external"
                except Exception:
                    pass
        except Exception:
            pass
        return "unsupported"

    async def click_easy_apply(self, page: Page) -> bool:
        """Reliably click LinkedIn's native Easy Apply CTA.

        Route detection is performed immediately before this function.  Once
        LinkedIn has classified the job as native Easy Apply, this function
        aggressively resolves the current CTA after LinkedIn re-renders the
        top-card button.  It supports the DOM variants seen in current
        LinkedIn builds:
          - button.jobs-apply-button
          - LinkedIn Apply to <role> aria-labels
          - Easy Apply text/ARIA
          - native Apply text inside the jobs-apply button
          - tracking/data attributes on the jobs apply control

        A successful native click is considered authoritative; modal detection
        is only diagnostic and must never turn a successful click into
        ``apply_not_found``.
        """
        selectors = [
            "button.jobs-apply-button",
            "[data-tracking-control-name*='jobs_apply' i]",
            "[data-control-name*='jobs_apply' i]",
            "button[aria-label^='LinkedIn Apply to' i]",
            "[role='button'][aria-label^='LinkedIn Apply to' i]",
            "button[aria-label*='Easy Apply' i]",
            "[role='button'][aria-label*='Easy Apply' i]",
            "button[data-control-name*='easy' i]",
            "button[data-testid*='easy' i]",
            "[role='button'][data-control-name*='easy' i]",
            "[role='button'][data-testid*='easy' i]",
            "button:has-text('Easy Apply')",
            "[role='button']:has-text('Easy Apply')",
            "a[href*='easy-apply' i]",
        ]

        async def _try_click(el) -> bool:
            try:
                if not await el.is_visible() or await el.is_disabled():
                    return False
            except Exception:
                return False
            try:
                await el.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass

            # Normal Playwright click first.
            for force, timeout in ((False, 8000), (True, 4000)):
                try:
                    await el.click(timeout=timeout, force=force)
                    return True
                except Exception:
                    pass

            # LinkedIn frequently overlays/replaces the button between
            # detection and click.  Dispatch a real DOM click as a final
            # recovery path on the exact already-classified native element.
            try:
                await el.dispatch_event("click")
                return True
            except Exception:
                pass
            try:
                await el.evaluate("(el) => el.click()")
                return True
            except Exception:
                return False

        # Re-resolve after a short settle period so a React/SPA re-render does
        # not leave us with a stale Locator.
        for delay in (0, 500, 1000):
            if delay:
                await page.wait_for_timeout(delay)
            for selector in selectors:
                try:
                    loc = page.locator(selector)
                    count = await loc.count()
                except Exception:
                    continue
                for i in range(min(count, 12)):
                    try:
                        if await _try_click(loc.nth(i)):
                            await page.wait_for_timeout(800)
                            return True
                    except Exception:
                        continue

        # Semantic fallback: inspect visible controls and only accept an
        # unambiguous native CTA. Plain "Apply" is accepted here because the
        # caller has already classified this job as native Easy Apply.
        try:
            controls = page.locator("button:visible, [role='button']:visible, a:visible")
            count = await controls.count()
        except Exception:
            return False

        for i in range(min(count, 250)):
            try:
                el = controls.nth(i)
                if not await el.is_visible() or await el.is_disabled():
                    continue
                text = re.sub(r"\s+", " ", await el.inner_text()).strip()
                aria = re.sub(r"\s+", " ", (await el.get_attribute("aria-label") or "")).strip()
                title = re.sub(r"\s+", " ", (await el.get_attribute("title") or "")).strip()
                cls = (await el.get_attribute("class") or "").lower()
                data_track = (await el.get_attribute("data-tracking-control-name") or "").lower()
                data_control = (await el.get_attribute("data-control-name") or "").lower()
                desc = " ".join((text, aria, title, cls, data_track, data_control))

                native_label = (
                    re.fullmatch(r"easy\s+apply", text or "", re.I)
                    or re.search(r"\beasy\s+apply\b", aria, re.I)
                    or re.match(r"linkedin\s+apply\s+to\b", aria, re.I)
                    or "jobs-apply-button" in cls
                    or "jobs_apply" in data_track
                    or "jobs_apply" in data_control
                    or re.fullmatch(r"apply(?:\s+now)?", text or "", re.I)
                       and ("jobs" in cls or "linkedin" in aria.lower() or "apply" in data_track or "apply" in data_control)
                )
                if not native_label:
                    continue

                # Prefer exact button/role elements.  Do not use generic text
                # containers if a real clickable parent can be found.
                target = el
                try:
                    parent = el.locator("xpath=ancestor-or-self::*[self::button or @role='button'][1]")
                    if await parent.count():
                        target = parent.first
                except Exception:
                    pass

                if await _try_click(target):
                    await page.wait_for_timeout(800)
                    return True
            except Exception:
                continue

        return False

    async def _wait_for_easy_apply_surface(self, page: Page, timeout_ms: int = 10000) -> bool:
        """Wait for LinkedIn's Easy Apply modal/form to actually render after the CTA click."""
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        selectors = (
            ".jobs-easy-apply-modal:visible",
            "div[role='dialog']:visible",
            "[aria-modal='true']:visible",
        )
        while time.monotonic() < deadline:
            try:
                for selector in selectors:
                    loc = page.locator(selector)
                    if await loc.count():
                        print("  EASY APPLY UI: modal/dialog detected")
                        return True
            except Exception:
                pass
            try:
                body = (await page.locator("body").inner_text(timeout=1000)).lower()
                if any(x in body for x in (
                    "contact info", "resume", "additional questions",
                    "review your application", "submit application"
                )):
                    print("  EASY APPLY UI: native application content detected")
                    return True
            except Exception:
                pass
            await page.wait_for_timeout(250)
        print("  EASY APPLY UI: modal not detected; continuing with native flow recovery")
        return False

    async def _detect_native_apply_type(self, page: Page) -> str:
        """Classify the active LinkedIn native Easy Apply modal.

        Native variants covered:
        - easy_apply_single_step: Submit Application is already available.
        - easy_apply_multi_step: Next/Continue/Review advances through steps/questions.
        """
        try:
            root = page.locator(".jobs-easy-apply-modal:visible, div[role='dialog']:visible").last
            if await root.count() == 0:
                root = page.locator("body")
            submit = root.get_by_role("button", name=re.compile(r"submit application|submit|send application", re.I))
            for i in range(await submit.count()):
                if await submit.nth(i).is_visible():
                    return "easy_apply_single_step"
            next_btn = root.get_by_role("button", name=re.compile(r"^next$|^continue$|^review$", re.I))
            for i in range(await next_btn.count()):
                if await next_btn.nth(i).is_visible():
                    return "easy_apply_multi_step"
            body = re.sub(r"\s+", " ", await root.inner_text()).lower()
            if any(x in body for x in ("upload resume", "selected resume", "upload a resume", "additional questions")):
                return "easy_apply_multi_step"
        except Exception:
            pass
        return "easy_apply_unknown"

    async def _leave_native_tab_open(self, page: Page, reason: str) -> None:
        """Stop safely on an unresolved native question and leave the modal/tab open."""
        try:
            print(f"  NATIVE APPLY TAB LEFT OPEN: reason={reason}")
            print(f"  NATIVE APPLY TYPE: {await self._detect_native_apply_type(page)}")
            await page.bring_to_front()
        except Exception:
            pass

    async def _visible_question(self, page: Page) -> str:
        """Return the current question from the active Easy Apply control.

        Control-first extraction avoids using an unrelated h3/marketing label
        elsewhere in the dialog as the question. The associated option labels
        are stored for the same control group for answer validation/filling.
        """
        self._last_question_options = []
        self._current_question_control = None
        self._current_question_kind = ""
        root = page.locator(".jobs-easy-apply-modal:visible, div[role='dialog']:visible").last
        if await root.count() == 0:
            root = page.locator("body")

        controls = root.locator(
            "input:visible, textarea:visible, select:visible, [contenteditable='true']:visible, "
            "[role='textbox']:visible, [role='combobox']:visible, [role='radio']:visible, [role='checkbox']:visible"
        )
        best = None
        for i in range(await controls.count()):
            el = controls.nth(i)
            try:
                typ = (await el.get_attribute("type") or "").lower()
                if typ in {"hidden", "submit", "button", "file", "image"} or await el.is_disabled():
                    continue
                value = ""
                try:
                    value = await el.input_value()
                except Exception:
                    pass

                # Skip controls that are already answered/selected. LinkedIn
                # keeps checked Yes/No controls visible on later multi-question
                # steps; treating the checked radio as the current question can
                # starve the real unanswered text inputs behind it.
                if typ in {"radio", "checkbox"}:
                    try:
                        if await el.is_checked():
                            continue
                    except Exception:
                        pass
                    try:
                        aria_checked = (await el.get_attribute("aria-checked") or "").lower()
                        if aria_checked == "true":
                            continue
                    except Exception:
                        pass

                if value and typ not in {"radio", "checkbox"}:
                    continue
                text = await el.evaluate("""e => {
                    const clean = x => (x || '').replace(/\\s+/g, ' ').trim();
                    const chunks = [];
                    if (e.id) { const l=document.querySelector(`label[for=\"${CSS.escape(e.id)}\"]`); if(l) chunks.push(clean(l.innerText||l.textContent)); }
                    if (e.labels) [...e.labels].forEach(l => chunks.push(clean(l.innerText||l.textContent)));
                    const field = e.closest('fieldset,[role=\"group\"],[role=\"radiogroup\"],div');
                    if (field) {
                      const legend = field.querySelector('legend,[data-test-form-element-label],[aria-labelledby]');
                      if (legend && legend !== e) chunks.push(clean(legend.innerText||legend.textContent||legend.getAttribute('aria-label')));
                    }
                    chunks.push(clean(e.getAttribute('aria-label')));
                    chunks.push(clean(e.getAttribute('placeholder')));
                    return chunks.filter(Boolean).find(x => x.length > 1) || '';
                }""")
                if not text:
                    continue
                q = re.sub(r"\s+", " ", text).strip()
                if self._is_resume_picker_text(q):
                    continue
                score = 10
                if any(x in q.lower() for x in ("linkedin", "github", "email", "phone", "experience", "salary", "relocate")):
                    score += 10
                if typ in {"radio", "checkbox"}:
                    score += 2
                if best is None or score > best[0]:
                    best = (score, el, q)
            except Exception:
                continue

        if best is not None:
            _, control, question = best
            self._current_question_control = control
            self._current_question_kind = (await control.get_attribute("type") or await control.get_attribute("role") or "").lower()
            # Scope answer options to the same semantic group/control.
            try:
                group = control.locator("xpath=ancestor::fieldset[1]")
                if await group.count() == 0:
                    group = control.locator("xpath=ancestor::*[@role='radiogroup'][1]")
                if await group.count() == 0:
                    group = control.locator("xpath=ancestor::*[@role='group'][1]")
                option_labels = []
                if await group.count():
                    option_labels = await group.first.locator("label:visible,[role='radio']:visible,[role='option']:visible").all_inner_texts()
                if not option_labels and (await control.get_attribute("role") or "") == "combobox":
                    option_labels = await root.locator("[role='option']:visible").all_inner_texts()
                self._last_question_options = [
                    re.sub(r"\s+", " ", x).strip() for x in option_labels if re.sub(r"\s+", " ", x).strip()
                    and re.sub(r"\s+", " ", x).strip().lower() not in {"save", "continue", "next", "submit", "review"}
                ]
            except Exception:
                self._last_question_options = []
            return question

        # Conservative fallback: only labels inside the active dialog.
        selectors = ["label:visible", "legend:visible", "[data-test-form-element-label]:visible"]
        for sel in selectors:
            try:
                loc = root.locator(sel)
                for i in range(await loc.count()):
                    txt = re.sub(r"\s+", " ", await loc.nth(i).inner_text()).strip()
                    if txt and 2 < len(txt) < 300 and not self._is_resume_picker_text(txt):
                        return txt
            except Exception:
                pass
        return ""

    async def _linkedin_resume_picker_active(self, page: Page) -> bool:
        """Return True only when the visible Easy Apply UI is actually on the resume step.

        LinkedIn can keep a hidden ``input[type=file]`` mounted after advancing to
        later pages. That input must never be treated as an active resume picker.
        """
        try:
            root = page.locator(".jobs-easy-apply-modal:visible, div[role='dialog']:visible, [aria-modal='true']:visible").last
            if await root.count() == 0:
                root = page.locator("body")

            # A visible Upload/Choose/Attach Resume control is the strongest signal.
            upload_text = re.compile(r"^\s*(upload|choose|attach)(?:\s+a)?\s+(?:resume|cv)\s*$", re.I)
            for selector in ("button:visible", "[role='button']:visible", "a:visible", "label:visible"):
                loc = root.locator(selector)
                for i in range(min(await loc.count(), 80)):
                    try:
                        text = re.sub(r"\s+", " ", await loc.nth(i).inner_text()).strip()
                        if upload_text.search(text):
                            return True
                    except Exception:
                        pass

            # Do not use the resume filename appearing anywhere in the modal as a
            # resume-step signal. LinkedIn can keep the selected filename mounted
            # after advancing to later pages, which would falsely re-enter the
            # upload path.
        except Exception:
            pass
        return False

    async def _upload_linkedin_resume(self, page: Page) -> bool:
        """Upload and select the exact job-specific resume by filename."""
        resume_path = str(self.current_resume_path or "").strip()
        if not resume_path or not Path(resume_path).is_file():
            print("  RESUME NOT FOUND: job-specific tailored resume is unavailable; refusing generic resume.pdf fallback.")
            return False

        source = Path(resume_path).resolve()
        page_url = getattr(page, "url", "") or ""
        if page_url:
            try:
                import hashlib, shutil
                upload_dir = self.base_dir / "webapp" / "runtime" / "external_resume_uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                job_token = hashlib.sha256(page_url.encode("utf-8", "ignore")).hexdigest()[:10]
                digest = hashlib.sha256(source.read_bytes()).hexdigest()[:10]
                upload_path = upload_dir / f"Anuroop_Kudire_{digest}_{job_token}_tailored_resume{source.suffix.lower()}"
                if source != upload_path and ((not upload_path.exists()) or upload_path.stat().st_size != source.stat().st_size):
                    shutil.copy2(source, upload_path)
                resume_path = str(upload_path)
            except Exception as exc:
                print(f"  RESUME UPLOAD COPY WARNING: {type(exc).__name__}: {exc}")

        expected = Path(resume_path).name.strip()
        expected_norm = expected.lower()

        async def scopes():
            out=[page]
            try: out.extend(list(page.frames))
            except Exception: pass
            return out

        async def select_named(scope):
            for selector in ("[role='radio'][aria-label]", "[role='radio']", "label", "[aria-label]"):
                try:
                    loc=scope.locator(selector); count=min(await loc.count(),160)
                except Exception: continue
                for i in range(count):
                    el=loc.nth(i)
                    try:
                        if not await el.is_visible(timeout=300): continue
                    except Exception: continue
                    vals=[]
                    for attr in ("aria-label","title","data-testid"):
                        try: v=await el.get_attribute(attr)
                        except Exception: v=None
                        if v: vals.append(v)
                    try: vals.append(await el.inner_text())
                    except Exception: pass
                    text=re.sub(r"\s+"," "," ".join(vals)).strip().lower()
                    if expected_norm not in text: continue
                    try: await el.scroll_into_view_if_needed()
                    except Exception: pass
                    try: await el.click(timeout=3000, force=True)
                    except Exception: continue
                    try:
                        if await el.get_attribute("aria-checked") == "true": return True
                    except Exception: pass
                    try:
                        if (await el.get_attribute("type") or "").lower()=="radio" and await el.is_checked(): return True
                    except Exception: pass
                    return True
            return False

        for scope in await scopes():
            if await select_named(scope):
                print(f"  RESUME SELECTED BY NAME: {expected}")
                return True

        # A few LinkedIn builds expose the file input directly, even though
        # the UI button is the normal path. Use it only as a compatibility
        # fallback and still verify the exact filename.
        for scope in await scopes():
            try:
                inputs = scope.locator("input[type='file']")
                count = min(await inputs.count(), 10)
            except Exception:
                count = 0
            for i in range(count):
                el = inputs.nth(i)
                try:
                    await el.set_input_files(resume_path)
                    names = await el.evaluate("el => el.files ? Array.from(el.files).map(f => f.name) : []")
                    norm_names = [str(x.get("name") if isinstance(x, dict) else x) for x in (names or [])]
                    if expected in norm_names:
                        print(f"  RESUME SELECTED: {expected}")
                        return True
                except Exception:
                    continue

        controls=[]
        for scope in await scopes():
            try:
                loc=scope.get_by_text("Upload resume", exact=True)
                for i in range(min(await loc.count(),20)): controls.append(loc.nth(i))
            except Exception: pass
            try:
                loc=scope.locator("button:visible").filter(has_text=re.compile(r"^\s*Upload resume\s*$",re.I))
                for i in range(min(await loc.count(),20)): controls.append(loc.nth(i))
            except Exception: pass

        for control in controls:
            try: await control.scroll_into_view_if_needed()
            except Exception: pass
            attached=False
            try:
                async with page.expect_file_chooser(timeout=6000) as info:
                    await control.click(timeout=6000, force=True)
                chooser=await info.value
                await chooser.set_files(resume_path)
                attached=True
            except Exception:
                try: await control.click(timeout=4000, force=True)
                except Exception: pass
                await page.wait_for_timeout(500)
                for scope in await scopes():
                    try:
                        inputs=scope.locator("input[type='file']")
                        for i in range(min(await inputs.count(),10)):
                            el=inputs.nth(i); await el.set_input_files(resume_path)
                            names=await el.evaluate("el => el.files ? Array.from(el.files).map(f=>f.name) : []")
                            if expected in names: attached=True; break
                    except Exception: pass
                    if attached: break
            if not attached: continue

            for _ in range(40):
                verified=False
                for scope in await scopes():
                    try:
                        inputs=scope.locator("input[type='file']")
                        for i in range(min(await inputs.count(),10)):
                            names=await inputs.nth(i).evaluate("el => el.files ? Array.from(el.files).map(f=>f.name) : []")
                            if expected in names: verified=True; break
                    except Exception: pass
                    if verified: break
                selected=False
                for scope in await scopes():
                    try:
                        if await select_named(scope): selected=True; break
                    except Exception: pass
                if verified and selected:
                    print(f"  RESUME SELECTED: {expected}")
                    return True
                await page.wait_for_timeout(250)

        print(f"  RESUME UPLOAD FAILED: exact filename not selected: {expected}")
        return False

    async def _resolve(self, question: str, options: list[str]) -> tuple[Any, str, str]:
        context = {
            "job_role": self.profile.get("application_job_role"),
            "field_semantic": self._normalize_easy_apply_semantic(question),
            "widget": "easy_apply",
            "visible_options": options,
        }
        result = await asyncio.to_thread(self.reasoner.reason, question, options, context)
        if not result:
            return None, None, "unknown"
        return result.get("answer"), result.get("field"), result.get("kind", "text")

    @staticmethod
    def _normalize_easy_apply_semantic(question: str) -> str:
        q = re.sub(r"[^a-z0-9]+", " ", str(question or "").lower()).strip()
        if q == "headline" or "professional headline" in q:
            return "headline"
        if q in {"summary", "professional summary", "profile summary"} or "tell us about yourself" in q:
            return "summary"
        if "cover letter" in q or "application letter" in q:
            return "cover_letter"
        if "relevant experience" in q:
            return "relevant_experience"
        if "strength" in q:
            return "strengths"
        if "why this role" in q or "why do you want" in q or "motivat" in q:
            return "motivation"
        return "unknown"

    async def _fill_control(self, page: Page, answer: Any, question: str, options: list[str]) -> bool:
        """Fill only the control semantically associated with the current question."""
        if answer is None:
            return False
        text_answer = ", ".join(map(str, answer)) if isinstance(answer, (list, tuple)) else str(answer)
        q = re.sub(r"\s+", " ", question or "").strip().lower()

        # Prefer the exact control that produced the current question. This avoids
        # selecting a previously-filled field when several LinkedIn inputs are
        # mounted together on the same Easy Apply step.
        direct = self._current_question_control
        if direct is not None:
            try:
                if await direct.is_visible() and not await direct.is_disabled():
                    typ = (await direct.get_attribute("type") or "").lower()
                    role = (await direct.get_attribute("role") or "").lower()
                    if typ not in {"file", "submit", "button", "hidden"}:
                        if typ in {"radio", "checkbox"} or role in {"radio", "checkbox"}:
                            if options:
                                for opt in options:
                                    if self._option_match(text_answer, opt):
                                        target = direct.locator("xpath=ancestor::*[@role='radiogroup' or @role='group' or self::fieldset][1]")
                                        if await target.count():
                                            matches = target.first.locator("label:visible,[role='radio']:visible,[role='checkbox']:visible,[role='option']:visible")
                                            for j in range(await matches.count()):
                                                m = matches.nth(j)
                                                if self._option_match(text_answer, re.sub(r"\s+", " ", await m.inner_text()).strip()):
                                                    await m.click(force=True)
                                                    return True
                            await direct.click(force=True)
                            return True
                        if typ == "select" or role == "combobox":
                            if options:
                                target = self._best_option(text_answer, options)
                                if target and typ == "select":
                                    await direct.select_option(label=target)
                                    return await self._verify_select(direct, target)
                            if role == "combobox":
                                await direct.click(force=True)
                                if await self._click_visible_option(page, text_answer):
                                    return True
                        else:
                            existing = ""
                            try:
                                existing = await direct.input_value()
                            except Exception:
                                try:
                                    existing = await direct.inner_text()
                                except Exception:
                                    existing = ""
                            if not str(existing).strip():
                                await direct.fill(text_answer)
                                value = await direct.input_value() if await direct.get_attribute("contenteditable") != "true" else await direct.inner_text()
                                return re.sub(r"\s+", " ", str(value)).strip() == re.sub(r"\s+", " ", text_answer).strip()
            except Exception:
                pass

        async def relevance(el) -> int:
            try:
                meta = await el.evaluate("""e => {
                    const clean = x => (x || '').replace(/\\s+/g, ' ').trim();
                    const bits = [e.getAttribute('name'), e.getAttribute('id'), e.getAttribute('aria-label'),
                                  e.getAttribute('placeholder'), e.getAttribute('aria-labelledby'), e.getAttribute('title')];
                    if (e.labels) [...e.labels].forEach(l => bits.push(l.innerText || l.textContent));
                    let n = e;
                    for (let i=0; i<4 && n; i++, n=n.parentElement) bits.push(n.innerText || n.textContent);
                    return bits.filter(Boolean).map(clean).join(' ').slice(0,1800);
                }""")
            except Exception:
                meta = ""
            qwords = set(re.findall(r"[a-z0-9]+", q))
            mwords = set(re.findall(r"[a-z0-9]+", meta.lower()))
            score = len(qwords & mwords)
            strong = {
                "linkedin": ("linkedin",), "github": ("github",),
                "email": ("email",), "phone": ("phone", "mobile"),
                "postal": ("postal", "zip", "pin"), "experience": ("experience", "years"),
                "salary": ("salary", "ctc", "compensation"), "location": ("location", "city", "state"),
                "python": ("python",), "relocate": ("relocate", "relocation"),
            }
            for token, aliases in strong.items():
                if token in q and any(a in meta.lower() for a in aliases):
                    score += 20
            return score

        # Native selects: rank by question relevance rather than taking the first
        # visible select on the page.
        try:
            selects = page.locator("select:visible")
            select_candidates = []
            for i in range(await selects.count()):
                el = selects.nth(i)
                opts = await el.locator("option").all_inner_texts()
                target = self._best_option(text_answer, opts)
                if target:
                    select_candidates.append((await relevance(el), el, target))
            for _, el, target in sorted(select_candidates, key=lambda x: -x[0]):
                try:
                    await el.select_option(label=target)
                    if await self._verify_select(el, target):
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        # Radio/checkbox options: rank matching controls by the same question
        # context. This avoids clicking an unrelated visible "Yes" elsewhere.
        try:
            candidates = []
            loc = page.locator("label:visible, [role='radio']:visible, [role='checkbox']:visible")
            for i in range(await loc.count()):
                el = loc.nth(i)
                try:
                    txt = re.sub(r"\s+", " ", await el.inner_text()).strip()
                    if txt and self._option_match(text_answer, txt):
                        candidates.append((await relevance(el), el))
                except Exception:
                    continue
            for _, el in sorted(candidates, key=lambda x: -x[0]):
                try:
                    await el.click(force=True)
                    return True
                except Exception:
                    continue
        except Exception:
            pass

        # Text-like controls are question-scored and verified.
        try:
            controls = page.locator("input:visible, textarea:visible, [contenteditable='true']:visible")
            scored = []
            for i in range(await controls.count()):
                el = controls.nth(i)
                try:
                    typ = (await el.get_attribute("type") or "text").lower()
                    if typ in {"hidden", "file", "submit", "button", "checkbox", "radio"}:
                        continue
                    # On combined LinkedIn question pages, previously answered
                    # text inputs remain mounted. Never reuse an already-filled
                    # field for the next question; otherwise the relevance score
                    # can select the first filled field again and leave the actual
                    # unanswered field blank.
                    try:
                        if typ != "file":
                            existing = await el.input_value()
                        else:
                            existing = ""
                    except Exception:
                        try:
                            existing = await el.inner_text() if await el.get_attribute("contenteditable") == "true" else ""
                        except Exception:
                            existing = ""
                    if str(existing).strip():
                        continue
                    scored.append((await relevance(el), el))
                except Exception:
                    pass
            scored.sort(key=lambda x: -x[0])
            for score, el in scored:
                if score < 1 and len(scored) > 1:
                    continue
                try:
                    await el.fill(text_answer)
                    value = await el.input_value() if await el.get_attribute("contenteditable") != "true" else await el.inner_text()
                    if re.sub(r"\s+", " ", str(value)).strip() == re.sub(r"\s+", " ", text_answer).strip():
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    async def _click_visible_option(self, page: Page, answer: str) -> bool:
        target = re.sub(r"\s+", " ", str(answer).strip()).lower()
        if not target:
            return False
        try:
            loc = page.locator("[role='option']:visible, [role='radio']:visible, label:visible, button:visible")
            for i in range(loc.count() - 1, -1, -1):
                el = loc.nth(i)
                if not await el.is_visible():
                    continue
                txt = re.sub(r"\s+", " ", await el.inner_text()).strip().lower()
                if txt == target or txt.startswith(target + " ") or target in txt:
                    await el.click(force=True)
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _option_match(answer: str, option: str) -> bool:
        a, o = re.sub(r"\s+", " ", answer).strip().lower(), re.sub(r"\s+", " ", option).strip().lower()
        return a == o or a in o or o in a

    @staticmethod
    def _best_option(answer: str, options: list[str]) -> str | None:
        for option in options:
            if LinkedInAgent._option_match(answer, option):
                return option
        return None

    async def _verify_select(self, el, expected: str) -> bool:
        try:
            return (await el.input_value()).strip() != ""
        except Exception:
            return False

    async def _wait_for_easy_apply_advance(self, page: Page, old_question: str, timeout_ms: int = 7000) -> bool:
        old_key = re.sub(r"\s+", " ", str(old_question or "")).strip().lower()
        elapsed = 0
        while elapsed < timeout_ms:
            try:
                body = re.sub(r"\s+", " ", await page.locator("body").inner_text()).lower()
                if any(x in body for x in ("application submitted", "your application was sent", "you applied")):
                    return True
                if await self._has_submit(page):
                    return True
                q = await self._visible_question(page)
                q_key = re.sub(r"\s+", " ", str(q or "")).strip().lower()
                if q_key and q_key != old_key:
                    return True
            except Exception:
                pass
            await page.wait_for_timeout(250)
            elapsed += 250
        return False

    async def _easy_apply_loop(self, page: Page, job_url: str) -> str:
        """Generic LinkedIn Easy Apply step machine with verification and safe stops."""
        last_question_key = None
        resume_uploaded = False
        resume_attempted = False
        for _ in range(80):
            if await self.detect_blocker(page):
                return "security_check"

            body = re.sub(r"\s+", " ", await page.locator("body").inner_text()).lower()
            if any(x in body for x in ("application submitted", "your application was sent", "you applied")):
                return "dry_run_complete" if self.dry_run else "applied"

            # LinkedIn may expose the resume picker without a conventional text question.
            # Upload/select the tailored resume only once per Easy Apply flow. The file
            # input can remain mounted in the modal after LinkedIn advances to later
            # pages; re-running set_input_files there would re-upload the resume instead
            # of processing the actual questions on those pages.
            if not resume_uploaded and not resume_attempted and await self._linkedin_resume_picker_active(page):
                resume_attempted = True
                resume_uploaded = await self._upload_linkedin_resume(page)
                if not resume_uploaded:
                    # Never spin on the same resume picker for the remainder of the
                    # Easy Apply loop. Leave the native tab open so the upload can
                    # be completed/recovered manually without blocking the agent.
                    await self._leave_native_tab_open(page, "resume_upload_failed")
                    return "resume_upload_failed"
            elif not resume_uploaded:
                # Do not touch a hidden/stale file input mounted from the earlier
                # resume step while LinkedIn is showing the actual application page.
                pass

            q = await self._visible_question(page)
            if q:
                key = re.sub(r"\s+", " ", q).lower()
                if key == last_question_key:
                    # The same unanswered question is still visible after a supposed
                    # transition. This is a real no-progress condition, not a reason
                    # to fill/submit the same field repeatedly.
                    await self._leave_native_tab_open(page, "question_did_not_advance")
                    return "no_progress"

                options = list(getattr(self, "_last_question_options", []) or [])
                if not options:
                    try:
                        options = [re.sub(r"\s+", " ", x).strip() for x in await page.locator("label:visible").all_inner_texts() if x.strip()]
                    except Exception:
                        pass
                answer, field, kind = await self._resolve(q, options)
                if answer is None:
                    print(f"  UNKNOWN LINKEDIN QUESTION: {q}")
                    # Never silently skip an unresolved employer question. Leave the
                    # native application open so it can be answered safely.
                    await self._leave_native_tab_open(page, "unknown_question")
                    return "unknown_question"
                print(f"  Q: {q}\n  A: {answer}")
                if not await self._fill_control(page, answer, q, options):
                    print(f"  LINKEDIN QUESTION FILL FAILED: {q}")
                    await self._leave_native_tab_open(page, "fill_failed")
                    return "fill_failed"
                qa(self.con, self.fingerprint(job_url), q, json.dumps(answer, ensure_ascii=False) if isinstance(answer, (list, tuple)) else str(answer), field)
                last_question_key = key

            # Final submit is deliberately gated by dry-run.
            if await self._has_submit(page):
                if self.dry_run:
                    print("  DRY RUN: final LinkedIn Submit is blocked.")
                    return "ready_to_submit"
                if await self._click_submit(page):
                    await page.wait_for_timeout(1200)
                    body2 = re.sub(r"\s+", " ", await page.locator("body").inner_text()).lower()
                    if any(x in body2 for x in ("application submitted", "your application was sent", "you applied")):
                        return "applied"
                    return "submission_unconfirmed"
                return "submit_not_found"

            if not await self._click_next(page, final_allowed=False):
                await page.wait_for_timeout(500)
                continue
            if q:
                if not await self._wait_for_easy_apply_advance(page, q, timeout_ms=7000):
                    await self._leave_native_tab_open(page, "question_did_not_advance")
                    return "no_progress"
        return "timeout"

    async def _click_next(self, page: Page, final_allowed: bool) -> bool:
        """Advance the current Easy Apply modal using the real CTA; a successful click is progress."""
        root = page.locator(".jobs-easy-apply-modal:visible, div[role='dialog']:visible, [aria-modal='true']:visible").last
        if await root.count() == 0:
            root = page.locator("body")

        # LinkedIn has used several accessible names for the same footer CTA.
        patterns = [
            r"^next$", r"^continue$", r"^review$",
            r"^next\s+step$", r"^continue\s+to\s+next$",
            r"^review\s+application$",
        ]

        async def try_locator(loc) -> bool:
            try:
                count = await loc.count()
            except Exception:
                return False
            for i in range(count - 1, -1, -1):
                try:
                    el = loc.nth(i)
                    if not await el.is_visible() or await el.is_disabled():
                        continue
                    await el.scroll_into_view_if_needed(timeout=3000)
                    for force in (False, True):
                        try:
                            await el.click(timeout=10000, force=force)
                            await page.wait_for_timeout(900)
                            return True
                        except Exception:
                            pass
                    try:
                        await el.dispatch_event("click")
                        await page.wait_for_timeout(900)
                        return True
                    except Exception:
                        pass
                except Exception:
                    continue
            return False

        for pattern in patterns:
            try:
                if await try_locator(root.get_by_role("button", name=re.compile(pattern, re.I))):
                    print(f"  EASY APPLY ADVANCE: clicked {pattern}")
                    return True
            except Exception:
                pass

        # Recovery path: inspect actual visible buttons by rendered text/ARIA.
        try:
            controls = root.locator("button:visible, [role='button']:visible")
            for i in range(await controls.count() - 1, -1, -1):
                try:
                    el = controls.nth(i)
                    if not await el.is_visible() or await el.is_disabled():
                        continue
                    text = re.sub(r"\s+", " ", await el.inner_text()).strip().lower()
                    aria = re.sub(r"\s+", " ", (await el.get_attribute("aria-label") or "")).strip().lower()
                    label = f"{text} {aria}".strip()
                    if not any(re.fullmatch(p, text, re.I) or re.search(p, aria, re.I) for p in patterns):
                        if text not in {"next", "continue", "review"} and not any(x in label for x in ("next step", "continue to next", "review application")):
                            continue
                    if await try_locator(root.locator("button:visible, [role='button']:visible").filter(has_text=re.compile(r"next|continue|review", re.I))):
                        print("  EASY APPLY ADVANCE: clicked text/ARIA fallback")
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    async def _has_submit(self, page: Page) -> bool:
        try:
            root = page.locator(".jobs-easy-apply-modal:visible, div[role='dialog']:visible").last
            if await root.count() == 0:
                root = page.locator("body")
            loc = root.get_by_role("button", name=re.compile(r"submit application|submit|send application", re.I))
            return any(await loc.nth(i).is_visible() for i in range(await loc.count()))
        except Exception:
            return False

    async def _click_submit(self, page: Page) -> bool:
        try:
            root = page.locator(".jobs-easy-apply-modal:visible, div[role='dialog']:visible").last
            if await root.count() == 0:
                root = page.locator("body")
            loc = root.get_by_role("button", name=re.compile(r"submit application|submit|send application", re.I))
            for i in range(await loc.count() - 1, -1, -1):
                el = loc.nth(i)
                if await el.is_visible() and not await el.is_disabled():
                    await el.scroll_into_view_if_needed()
                    await el.click(timeout=10000)
                    return True
        except Exception:
            pass
        return False

    async def click_external_apply(self, context, page: Page) -> Page | None:
        """Click only a validated external Apply CTA and return its owned page."""
        pages_before = set(context.pages)
        candidates = []
        try:
            loc = page.locator("button:visible, a:visible, [role='button']:visible")
            for i in range(min(await loc.count(), 200)):
                el = loc.nth(i)
                try:
                    if not await el.is_visible() or await el.is_disabled():
                        continue
                    parts = [
                        await el.inner_text(),
                        await el.get_attribute("aria-label") or "",
                        await el.get_attribute("title") or "",
                        await el.get_attribute("href") or "",
                    ]
                    label = re.sub(r"\s+", " ", " ".join(parts)).strip().lower()
                    if "easy apply" in label or not re.search(r"\bapply\b", label):
                        continue
                    href = await el.get_attribute("href") or ""
                    explicit_external = any(x in label for x in (
                        "company site", "employer site", "external application",
                        "apply externally", "on company website", "company website",
                    ))
                    if explicit_external or (href.startswith("http") and "linkedin.com" not in href.lower()):
                        candidates.append(el)
                except Exception:
                    continue
        except Exception:
            pass
        if not candidates:
            return None
        try:
            await candidates[0].scroll_into_view_if_needed()
            await candidates[0].click(timeout=10000)
        except Exception:
            try:
                await candidates[0].click(timeout=5000, force=True)
            except Exception:
                return None
        for _ in range(40):
            try:
                for candidate in reversed([p for p in context.pages if p not in pages_before and not p.is_closed()]):
                    if "linkedin.com" not in (candidate.url or "").lower() and candidate.url != "about:blank":
                        return candidate
                if "linkedin.com" not in (page.url or "").lower() and page.url != "about:blank":
                    return page
            except Exception:
                pass
            await page.wait_for_timeout(250)
        return None

    async def fill_external_with_company_agent(self, page: Page, source_url: str) -> str:
        try:
            resume_path = self.current_resume_path
            if not resume_path or not Path(str(resume_path)).exists():
                print("  EXTERNAL RESUME: job-specific tailored resume is unavailable; refusing generic resume.pdf fallback.")
                return "external_error"
            print(f"  EXTERNAL RESUME TARGET: {Path(str(resume_path)).name}")
            dry = os.getenv("COMPANY_WEBSITE_DRY_RUN", "true").lower() not in {"0", "false", "no", "off"}
            filler = CompanyWebsiteAgent(dry_run=dry, profile_path=str(self.base_dir / "profile.json"), resume_path=resume_path)
            current_url = (page.url or "").strip()
            if current_url and "linkedin.com/jobs/view/" not in current_url.lower():
                target_url = current_url
            else:
                target_url = source_url
            result = await filler.apply(page, target_url)
            state = str(result.get("status", "")).upper()
            if state in {"READY_TO_SUBMIT", "EXTERNAL_FILLED"}:
                return "external_filled"
            if state in {"SUBMITTED", "SUCCESS", "APPLIED"}:
                return "external_submitted"
            if state in {"CAPTCHA_REQUIRED", "HUMAN_INTERVENTION", "SECURITY_CHECK", "LOGIN_REQUIRED"}:
                return "external_blocked"
            return "external_error"
        except Exception as exc:
            print(f"  EXTERNAL AGENT ERROR: {type(exc).__name__}: {exc}")
            return "external_error"

    async def process_job(self, context, url: str) -> str:
        page = await context.new_page()
        title = url
        company = ""
        jd = ""
        match = {}
        result = "error"
        keep_tab_open = False
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self.wait_stable(page)
            if await self.detect_blocker(page):
                result = "security_check"
                return result
            if not await self.is_logged_in(page):
                result = "login_required"
                return result
            if not await self._is_real_job_page(page):
                print("  INVALID/NONEXISTENT JOB PAGE: skipping Apply and moving on.")
                result = "job_unavailable"
                return result
            if await self.live_applied_state(page):
                print("  LIVE APPLICATION STATE: Applied — not clicking Apply.")
                result = "already_applied"
                return result

            title, company, jd = await self.extract_job(page)
            match = self.matcher.match(title, jd)
            print(f"  JD MATCH: {match['score']}/{match['threshold']} | eligible={match['eligible']} | AI={match.get('ai_relevant')}")
            if not match["eligible"]:
                result = "experience_mismatch" if not match["experience_ok"] else "low_match"
                return result
            try:
                from resume_integration import build_tailored_resume
                self.current_resume_path = build_tailored_resume(
                    profile_path=str(self.base_dir / "profile.json"),
                    title=title, jd_text=jd, platform="linkedin", job_url=url, company=company
                )
            except Exception as exc:
                print(f"  RESUME ROUTING WARNING: {type(exc).__name__}: {exc}")

            if self.native_applications >= self.target_applications:
                result = "application_target_reached"
                return result

            route = await self.detect_apply_route(page)
            print(f"  APPLY ROUTE: {route}")
            if route == "unsupported":
                result = "apply_not_found"
                return result
            if route == "external":
                # LinkedIn external routes are controlled: click only the validated
                # employer/company-site CTA, preserve the source job tab, then hand
                # the resulting application surface to the canonical company-site
                # form engine. CAPTCHA/OTP/security checks remain stop points.
                keep_tab_open = True
                print("  *** EXTERNAL/COMPANY-SITE APPLY DETECTED — clicking and opening external application ***")
                external_page = await self.click_external_apply(context, page)
                if external_page is None:
                    result = "external_apply_click_failed"
                    return result
                result = await self.fill_external_with_company_agent(external_page, url)
                if result == "external_filled":
                    self.external_filled += 1
                elif result == "external_submitted":
                    self.external_filled += 1
                    self.external_submitted += 1
                return result

            if not await self.click_easy_apply(page):
                result = "apply_not_found"
                return result
            # Native Easy Apply owns this job tab once its modal opens. Keep it
            # open on completion, unresolved questions, fill failures, and errors.
            keep_tab_open = True
            await self._wait_for_easy_apply_surface(page)
            native_type = await self._detect_native_apply_type(page)
            print(f"  LINKEDIN NATIVE APPLY TYPE: {native_type}")
            result = await self._easy_apply_loop(page, url)
            if result == "applied":
                self.native_applications += 1
            return result
        except PlaywrightTimeoutError:
            result = "navigation_timeout"
            return result
        except Exception as exc:
            print(f"  JOB ERROR: {type(exc).__name__}: {exc}")
            result = "error"
            return result
        finally:
            self.current_resume_path = None
            try:
                await self.record(url, title, result, company=company, description=jd, match=match)
            except Exception:
                pass
            if not keep_tab_open:
                try:
                    await page.close()
                except Exception:
                    pass

    async def _click_generic_apply(self, page: Page) -> bool:
        try:
            loc = page.locator("button:visible, [role='button']:visible, a:visible")
            for i in range(await loc.count()):
                el = loc.nth(i)
                txt = " ".join([
                    await el.inner_text(), await el.get_attribute("aria-label") or "", await el.get_attribute("title") or ""
                ]).strip()
                if re.search(r"\bapply\b", txt, re.I) and not re.search(r"easy\s*apply", txt, re.I):
                    if not await el.is_disabled():
                        await el.click(timeout=7000)
                        return True
        except Exception:
            pass
        return False

    async def next_search_url(self, page: Page, current_url: str, page_number: int) -> str | None:
        if page_number >= self.max_pages:
            return None
        try:
            links = await page.locator("a[href]").evaluate_all("els => els.map(a => ({href:a.href||'',text:(a.innerText||'').trim(),rel:a.rel||'',aria:a.getAttribute('aria-label')||''}))")
            candidates = []
            for x in links:
                href = x.get("href", "")
                label = " ".join((x.get("text", ""), x.get("rel", ""), x.get("aria", ""))).lower()
                if "/jobs/search/" not in href or href.split("#",1)[0] == current_url.split("#",1)[0]:
                    continue
                score = 100 if "next" in label else 0
                m = re.search(r"[?&]start=(\d+)", href)
                if m:
                    score += 50
                if score:
                    candidates.append((score, href.split("#",1)[0]))
            if candidates:
                return sorted(candidates, key=lambda x: (-x[0], x[1]))[0][1]
        except Exception:
            pass
        # Stable fallback for LinkedIn pagination: 25 results per page.
        m = re.search(r"[?&]start=(\d+)", current_url)
        start = int(m.group(1)) if m else 0
        if start + 25 < self.max_candidates:
            base = current_url.split("&start=", 1)[0].split("?start=", 1)[0]
            return base + ("&" if "?" in base else "?") + f"start={start+25}"
        return None

    async def run_with_context(self, context, search_url: str):
        live_pages = [p for p in context.pages if not p.is_closed()]
        if self._search_page is not None and not self._search_page.is_closed():
            page = self._search_page
        else:
            if not live_pages:
                raise RuntimeError("No live Chrome tab exists in the attached CDP context.")
            page = live_pages[-1]
            self._search_page = page
        current_url = search_url

        for page_number in range(1, self.max_pages + 1):
            if len(self.seen_urls) >= self.max_candidates:
                break
            print(f"\nSEARCH PAGE {page_number}/{self.max_pages}: {current_url}")
            await page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
            await self.wait_stable(page)
            if await self._no_search_results_page(page):
                print("  NO MATCHING JOBS FOUND ON THIS SEARCH PAGE — stopping this role/search.")
                break
            raw = await self.collect_job_urls(page)
            next_url = await self.next_search_url(page, current_url, page_number)
            urls = [u for u in dict.fromkeys(raw) if u not in self.seen_urls]
            print(f"  RESULTS: {len(raw)} | NEW UNIQUE JOBS: {len(urls)}")

            if not raw:
                print("  NO EXISTING JOBS FOUND FOR THIS ROLE/SEARCH — moving to next role.")
                break

            for url in urls:
                if len(self.seen_urls) >= self.max_candidates:
                    break

                # Cross-run persistent dedup: applications.db records only
                # outcomes that were actually processed. Never pre-mark the
                # rest of the search-results page as seen.
                job_key = self.fingerprint(url)
                if seen(self.con, job_key):
                    self.seen_urls.add(url)
                    print(f"  DB DEDUP -> already processed: {url}")
                    continue

                self.seen_urls.add(url)
                print(f"\nJOB CANDIDATE: {url}")
                try:
                    outcome = await self.process_job(context, url)
                    print(f"  OUTCOME: {outcome}")
                    if outcome in {"low_match", "experience_mismatch"}:
                        self.low_match += 1
                except Exception as exc:
                    self.errors += 1
                    print(f"  SKIPPED DUE TO ERROR: {type(exc).__name__}: {exc}")

            if not next_url or next_url.split("#",1)[0] == current_url.split("#",1)[0]:
                break
            current_url = next_url

        print(f"\nLINKEDIN SUMMARY: native={self.native_applications}/{self.target_applications}, external_filled={self.external_filled}, external_submitted={self.external_submitted}, low_match={self.low_match}, errors={self.errors}")