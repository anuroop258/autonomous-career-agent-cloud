"""
COMPANY WEBSITE APPLICATION AGENT

Reusable company-website application engine.

Can be used by:
    LinkedIn
    Naukri
    Indeed
    Direct company career pages

Current test mode:
    DRY_RUN = True
"""

from __future__ import annotations

import sys

import asyncio
import hashlib
import shutil
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.application.common.ai_form_engine import AIFormEngine


# ============================================================
# CONFIG
# ============================================================

DRY_RUN = True

DEFAULT_TIMEOUT = 10_000
NAVIGATION_TIMEOUT = 30_000
FORM_WAIT_TIMEOUT = 8_000

# External application controls can be slow or custom-rendered. Keep Apply
# discovery bounded so one company page can never stall the whole run.
APPLY_DISCOVERY_TIMEOUT = 4_000
APPLY_POLL_MS = 250
UPLOAD_CONTROL_TIMEOUT = 5_000
FORM_STABILITY_WAIT = 500


PROFILE_PATH = (
    PROJECT_ROOT
    / "src"
    / "application"
    / "common"
    / "profile.json"
)

RESUME_FALLBACK = (
    PROJECT_ROOT
    / "resume"
    / "resume.pdf"
)


# ============================================================
# HELPERS
# ============================================================

def normalize(text: Any) -> str:
    if text is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(text),
    ).strip().lower()


def clean_text(text: Any) -> str:
    if text is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(text),
    ).strip()


async def short_wait(page: Page, ms: int = 200):
    try:
        await page.wait_for_timeout(ms)
    except Exception:
        await asyncio.sleep(ms / 1000)


# ============================================================
# COMPANY WEBSITE AGENT
# ============================================================

class CompanyWebsiteAgent:

    def __init__(
        self,
        dry_run: bool = DRY_RUN,
        profile_path: Optional[str] = None,
        resume_path: Optional[str] = None,
    ):
        self.dry_run = dry_run

        self.profile_path = (
            Path(profile_path)
            if profile_path
            else PROFILE_PATH
        )

        self.resume_path = (
            Path(resume_path)
            if resume_path
            else RESUME_FALLBACK
        )

        self.profile: dict[str, Any] = {}

        self.history: list[dict[str, Any]] = []

        self.fields_filled = 0

        self.resume_uploaded = False

        self.terms_accepted = False

        self.unresolved_questions: list[
            dict[str, Any]
        ] = []

        self.application_url = ""
        self._active_page: Optional[Page] = None
        self.external_resume_upload_path: Optional[str] = None

        self.step = 0

    # ========================================================
    # LOGGING
    # ========================================================

    async def record(
        self,
        action: str,
        **kwargs,
    ):
        event = {
            "step": self.step,
            "action": action,
            **kwargs,
        }

        self.history.append(event)

        details = " ".join(
            f"{key}={value!r}"
            for key, value in kwargs.items()
        )

        if details:
            print(
                f"[STEP {self.step}] "
                f"{action}: {details}"
            )
        else:
            print(
                f"[STEP {self.step}] "
                f"{action}"
            )

    # ========================================================
    # PROFILE
    # ========================================================

    def load_profile(self):

        if not self.profile_path.exists():

            print(
                f"[PROFILE] Missing: "
                f"{self.profile_path}"
            )

            self.profile = {}

            return self.profile

        try:

            with open(
                self.profile_path,
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(file)

            if not isinstance(data, dict):

                raise ValueError(
                    "profile.json must contain an object"
                )

            self.profile = data

            print(
                f"[PROFILE] Loaded profile: "
                f"{self.profile_path}"
            )

        except Exception as exc:

            print(
                f"[PROFILE] Load error: {exc}"
            )

            self.profile = {}

        return self.profile

    def flatten_profile(
        self,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:

        source = (
            data
            if data is not None
            else self.profile
        )

        result: dict[str, Any] = {}

        def walk(value):

            if isinstance(value, dict):

                for key, item in value.items():

                    if isinstance(item, dict):
                        walk(item)

                    else:
                        result[str(key)] = item

            elif isinstance(value, list):

                for item in value:
                    walk(item)

        walk(source)

        return result

    def profile_get(
        self,
        *keys: str,
        default=None,
    ):

        flat = self.flatten_profile()

        normalized = {}

        for key, value in flat.items():

            normalized[
                re.sub(
                    r"[^a-z0-9]",
                    "",
                    key.lower(),
                )
            ] = value

        for requested in keys:

            lookup = re.sub(
                r"[^a-z0-9]",
                "",
                requested.lower(),
            )

            if lookup not in normalized:
                continue

            value = normalized[lookup]

            if value is None:
                continue

            if isinstance(value, str):

                if not value.strip():
                    continue

                return value.strip()

            return value

        return default

    # ========================================================
    # RESUME
    # ========================================================

    def get_resume_path(self) -> Optional[str]:
        # An explicit resume_path supplied by a platform's external job flow
        # is authoritative. This prevents the common profile's master
        # resume.pdf from overriding the job-specific tailored PDF.
        if self.resume_path and self.resume_path.exists():
            return str(self.resume_path)

        configured = self.profile_get(
            "resume_path",
            "resume",
            "cv",
        )

        if configured:
            path = Path(str(configured))
            if path.exists():
                return str(path)

        return None

    # ========================================================
    # PAGE WAITING
    # ========================================================

    async def wait_for_page(
        self,
        page: Page,
    ):

        try:

            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=15_000,
            )

        except Exception:
            pass

        await short_wait(
            page,
            750,
        )

        try:

            await page.wait_for_load_state(
                "networkidle",
                timeout=5_000,
            )

        except Exception:
            pass

        await short_wait(
            page,
            500,
        )

    # ========================================================
    # COOKIE CONSENT
    # ========================================================

    async def handle_cookie_consent(
        self,
        page: Page,
    ):

        patterns = [
            r"^accept$",
            r"^accept all$",
            r"^accept cookies$",
            r"^accept all cookies$",
            r"^allow all$",
            r"^i agree$",
            r"^agree$",
            r"^got it$",
        ]

        selectors = [
            "button",
            "a",
            "[role='button']",
        ]

        for selector in selectors:

            locator = page.locator(
                selector
            )

            try:
                count = await locator.count()

            except Exception:
                continue

            for i in range(count):

                element = locator.nth(i)

                try:

                    if not await element.is_visible():
                        continue

                    text = clean_text(
                        await element.inner_text()
                    )

                except Exception:
                    continue

                normalized = normalize(
                    text
                )

                if any(
                    re.fullmatch(
                        pattern,
                        normalized,
                        re.I,
                    )
                    for pattern in patterns
                ):

                    try:

                        await element.click(
                            timeout=3_000
                        )

                        await self.record(
                            "cookie_consent",
                            text=text,
                        )

                        await short_wait(
                            page,
                            500,
                        )

                        return True

                    except Exception:
                        continue

        return False

    # ========================================================
    # BLOCKERS
    # ========================================================

    async def detect_blocker(
        self,
        page: Page,
    ) -> Optional[str]:

        try:

            body = normalize(
                await page.locator(
                    "body"
                ).inner_text(
                    timeout=5_000
                )
            )

        except Exception:

            return None

        patterns = {

            "CAPTCHA_REQUIRED": [
                "captcha",
                "i'm not a robot",
                "verify you are human",
                "human verification",
            ],

            "LOGIN_REQUIRED": [
                "login to apply",
                "sign in to apply",
                "please sign in",
                "please log in",
            ],

            "ALREADY_APPLIED": [
                "already applied",
                "application already submitted",
                "you have already applied",
            ],

            "JOB_EXPIRED": [
                "job has expired",
                "job is no longer available",
                "position has been filled",
                "no longer accepting applications",
            ],
        }

        for status, phrases in patterns.items():

            for phrase in phrases:

                if phrase in body:

                    await self.record(
                        "blocker_detected",
                        status=status,
                        phrase=phrase,
                    )

                    return status

        return None

    # ========================================================
    # APPLY BUTTON
    # ========================================================

    async def _application_context(self, page: Page) -> bool:
        """Return True when the page already looks like an application form.

        This allows generic ATS pages to use a final ``Submit``/``Submit
        application`` CTA, while avoiding accidental clicks on unrelated
        website forms (newsletter/search/feedback).
        """
        try:
            url = normalize(page.url or "")
            if any(marker in url for marker in (
                "/application", "/apply", "/candidate", "/submission",
                "smartapply", "application-form", "apply-form",
            )):
                return True
            inputs = await page.locator("input:visible, textarea:visible, select:visible").count()
            files = await page.locator("input[type='file']:visible").count()
            forms = await page.locator("form:visible").count()
            if files or (forms and inputs >= 2):
                return True
        except Exception:
            pass
        return False

    async def _has_explicit_apply_cta(self, page: Page) -> bool:
        """Return True only when the current page visibly exposes an Apply CTA.

        This is narrower than find_apply_button(), which also recognizes final
        Submit variants. It prevents a company job-detail URL containing
        /ApplicationMethods or /application from being mistaken for a form
        when the page still exposes its own Apply link.
        """
        exact_apply = {
            "apply", "apply now", "start application", "start applying",
            "apply for this job", "apply to this job", "apply online",
        }
        frames = [page] + list(page.frames)
        for frame in frames:
            for selector in (
                "button:visible", "a:visible", "[role='button']:visible",
                "[role='link']:visible", "input[type='button']:visible",
                "input[type='submit']:visible",
            ):
                try:
                    loc = frame.locator(selector)
                    count = min(await loc.count(), 250)
                except Exception:
                    continue
                for i in range(count):
                    try:
                        el = loc.nth(i)
                        if not await el.is_visible() or await el.is_disabled():
                            continue
                        label = clean_text(await el.inner_text())
                        if not label:
                            label = clean_text(
                                await el.get_attribute("aria-label")
                                or await el.get_attribute("title")
                                or await el.get_attribute("value")
                                or ""
                            )
                        if label.lower() in exact_apply:
                            return True
                    except Exception:
                        continue
        return False

    async def _looks_like_application_url(self, url: str) -> bool:
        u = normalize(url or "")
        return any(marker in u for marker in (
            "/application", "/apply", "/candidate", "/submission",
            "smartapply", "application-form", "apply-form",
        ))

    async def find_apply_button(
        self,
        page: Page,
    ):
        """Find the next actionable ATS application CTA.

        Supports normal Apply labels plus application-page submit variants
        (Submit application / Submit your application / Send application /
        Complete application). DOM churn is handled per element so a detached
        node can never crash the entire agent.
        """
        exact_apply = {
            "apply", "apply now", "start application", "start applying",
            "apply for this job", "apply to this job", "apply online",
        }
        strong_apply = (
            "apply now", "apply for this job", "apply to this job",
            "start application", "start applying", "apply online",
        )
        submit_exact = {
            "submit application", "submit your application",
            "send application", "send your application",
            "complete application", "complete your application",
        }
        app_context = await self._application_context(page)
        frames = [page] + list(page.frames)
        best = None
        best_score = -1

        for frame in frames:
            selectors = [
                "button", "a", "input[type='button']", "input[type='submit']",
                "[role='button']", "[role='link']", "[onclick]",
            ]
            for selector in selectors:
                try:
                    locator = frame.locator(selector)
                    count = await locator.count()
                except Exception:
                    continue
                for i in range(min(count, 250)):
                    try:
                        element = locator.nth(i)
                        if not await element.is_visible():
                            continue
                        if await element.is_disabled():
                            continue
                    except Exception:
                        continue

                    attrs = {}
                    try:
                        for attr in ("aria-label", "title", "value", "data-testid", "data-test", "name", "id", "href"):
                            try:
                                attrs[attr] = clean_text(await element.get_attribute(attr))
                            except Exception:
                                attrs[attr] = ""
                        try:
                            text = clean_text(await element.inner_text())
                        except Exception:
                            text = ""
                    except Exception:
                        continue

                    normalized_text = normalize(text)
                    normalized_attrs = normalize(" ".join(attrs.values()))
                    score = -1

                    if normalized_text in exact_apply:
                        score = 110
                    elif any(phrase in normalized_text for phrase in strong_apply):
                        score = 105
                    elif "apply" in normalized_text and len(normalized_text) <= 100:
                        score = 90
                    elif "apply" in normalize(attrs.get("aria-label")):
                        score = 88
                    elif "apply" in normalize(attrs.get("title")):
                        score = 86
                    elif "apply" in normalized_attrs and (attrs.get("data-testid") or attrs.get("data-test")):
                        score = 82
                    elif "apply" in normalize(attrs.get("href")):
                        score = 70
                    elif normalized_text in submit_exact:
                        # Strong, explicit application CTAs are safe even on
                        # a job page whose URL has not yet changed to /apply.
                        score = 100
                    elif any(p in normalized_text for p in submit_exact):
                        score = 95
                    elif app_context and normalized_text == "submit":
                        # Bare "Submit" is only accepted once the page is
                        # clearly an application form, preventing unrelated
                        # newsletter/search forms from being clicked.
                        score = 92
                    elif app_context and "submit application" in normalized_attrs:
                        score = 90

                    if score > best_score:
                        best = element
                        best_score = score

            # Text-only fallback for ATS layouts where the clickable target is
            # a span/div with text but no button/link semantics. Promote the
            # closest actual clickable ancestor rather than clicking arbitrary
            # page text.
            try:
                patterns = [
                    re.compile(r"^\s*(?:apply|apply now|start application|apply online)\s*$", re.I),
                ]
                if app_context:
                    patterns.append(re.compile(r"^\s*(?:submit|submit application|submit your application|send application|complete application)\s*$", re.I))
                for pat in patterns:
                    loc = frame.get_by_text(pat)
                    count = await loc.count()
                    for i in range(min(count, 80)):
                        try:
                            node = loc.nth(i)
                            if not await node.is_visible():
                                continue
                            clickable = node.locator("xpath=ancestor-or-self::*[self::button or self::a or @role='button' or @role='link' or @onclick][1]")
                            if await clickable.count():
                                candidate = clickable.first
                                if await candidate.is_visible() and not await candidate.is_disabled():
                                    score = 108 if "submit" not in (await node.inner_text()).lower() else 98
                                    if score > best_score:
                                        best, best_score = candidate, score
                        except Exception:
                            continue
            except Exception:
                pass

        return best

    async def click_apply(
        self,
        page: Page,
    ) -> bool:

        await self.record("searching_for_apply_button")

        # Structural fast path: several ATSs expose a real Apply control
        # without usable visible text. Keep these selectors narrowly scoped
        # to known application controls so non-Apply buttons are untouched.
        structural_selectors = (
            "button.apply-now-button",
            "[data-automation-id=adventureButton][role=button]",
            "a[data-automation-id=adventureButton][href*='/apply']",
            "input[type=button][value='Apply Now']",
            "input[type=button][id='zr-detail-view-applybtn']",
        )

        async def click_structural_apply(button):
            try:
                await button.scroll_into_view_if_needed(timeout=1_500)
            except Exception:
                pass
            try:
                await button.click(timeout=4_000)
                return True
            except Exception as first_exc:
                await self.record("apply_button_click_error", error=str(first_exc))
                try:
                    await button.click(timeout=2_000, force=True)
                    return True
                except Exception as second_exc:
                    await self.record("apply_button_force_click_error", error=str(second_exc))
                    return False

        for frame in [page] + list(page.frames):
            for selector in structural_selectors:
                try:
                    candidates = frame.locator(selector)
                    count = min(await candidates.count(), 8)
                    for i in range(count):
                        button = candidates.nth(i)
                        try:
                            if not await button.is_visible(timeout=700):
                                continue
                            if await button.is_disabled():
                                continue
                        except Exception:
                            continue

                        before_pages = list(page.context.pages)
                        if not await click_structural_apply(button):
                            continue

                        for _ in range(10):
                            try:
                                new_pages = [
                                    p for p in page.context.pages
                                    if p not in before_pages and not p.is_closed()
                                ]
                                if new_pages:
                                    popup = new_pages[-1]
                                    self._active_page = popup
                                    try:
                                        await popup.wait_for_load_state("domcontentloaded", timeout=6_000)
                                    except Exception:
                                        pass
                                    self.application_url = popup.url
                                    await self.record("apply_popup_opened", url=popup.url)
                                    return True
                            except Exception:
                                pass
                            await short_wait(page, APPLY_POLL_MS)

                        self._active_page = page
                        await short_wait(page, APPLY_POLL_MS)
                        self.application_url = page.url
                        await self.record("apply_button_found", text="Apply", attempt=1)
                        return True
                except Exception:
                    continue

        # Fast path: exact Apply-for-this-job controls are common on company
        # job pages and avoid slow per-element visibility RPCs.
        fast_patterns = (
            re.compile(r"^\s*apply\s*$", re.I),
            re.compile(r"^\s*apply\s+for\s+this\s+job\s*$", re.I),
            re.compile(r"^\s*apply\s+now\s*$", re.I),
            re.compile(r"^\s*start\s+application\s*$", re.I),
        )

        for frame in [page] + list(page.frames):
            for pat in fast_patterns:
                try:
                    candidates = frame.get_by_text(pat)
                    count = min(await candidates.count(), 8)
                    for i in range(count):
                        node = candidates.nth(i)
                        try:
                            if not await node.is_visible(timeout=700):
                                continue
                        except Exception:
                            continue
                        clickable = node.locator(
                            "xpath=ancestor-or-self::*[self::a or self::button or @role='link' or @role='button'][1]"
                        )
                        if await clickable.count():
                            button = clickable.first
                        else:
                            button = node
                        try:
                            if not await button.is_visible(timeout=700) or await button.is_disabled():
                                continue
                        except Exception:
                            continue

                        try:
                            before_pages = list(page.context.pages)
                            await button.click(timeout=4_000)
                        except Exception as exc:
                            await self.record("apply_button_click_error", error=str(exc))
                            # A matching Apply label can appear on a decorative
                            # clone or be temporarily covered during hydration.
                            # Do not terminate the external apply flow here;
                            # continue to the remaining candidates/semantic
                            # discovery path.
                            continue

                        # Capture target=_blank/new-tab applications without clicking twice.
                        for _ in range(10):
                            try:
                                new_pages = [
                                    p for p in page.context.pages
                                    if p not in before_pages and not p.is_closed()
                                ]
                                if new_pages:
                                    popup = new_pages[-1]
                                    self._active_page = popup
                                    try:
                                        await popup.wait_for_load_state("domcontentloaded", timeout=6_000)
                                    except Exception:
                                        pass
                                    self.application_url = popup.url
                                    await self.record("apply_popup_opened", url=popup.url)
                                    return True
                            except Exception:
                                pass
                            await short_wait(page, APPLY_POLL_MS)

                        self._active_page = page
                        await short_wait(page, APPLY_POLL_MS)
                        self.application_url = page.url
                        await self.record(
                            "apply_button_found",
                            text=clean_text(await button.inner_text()) if await button.count() else "Apply",
                            attempt=1,
                        )
                        return True
                except Exception:
                    continue

        # Full semantic search, but bounded by a hard wall-clock deadline.
        # A broken/detached DOM control must never block the run indefinitely.
        async def discover():
            for attempt in range(1, 17):
                button = await self.find_apply_button(page)
                if button:
                    return attempt, button
                await short_wait(page, APPLY_POLL_MS)
            return None, None

        try:
            attempt, button = await asyncio.wait_for(
                discover(),
                timeout=APPLY_DISCOVERY_TIMEOUT / 1000,
            )
        except asyncio.TimeoutError:
            await self.record("apply_button_search_timeout", timeout_ms=APPLY_DISCOVERY_TIMEOUT)
            return False
        except Exception as exc:
            await self.record("apply_button_search_error", error=str(exc))
            return False

        if not button:
            await self.record("apply_button_not_found")
            return False

        try:
            text = clean_text(await button.inner_text()) or "Apply"
        except Exception:
            text = "Apply"

        await self.record("apply_button_found", text=text, attempt=attempt)
        old_url = page.url

        try:
            before_pages = list(page.context.pages)
            await button.click(timeout=4_000)
        except Exception as exc:
            await self.record("apply_button_click_error", error=str(exc))
            return False

        for _ in range(10):
            try:
                new_pages = [
                    p for p in page.context.pages
                    if p not in before_pages and not p.is_closed()
                ]
                if new_pages:
                    popup = new_pages[-1]
                    self._active_page = popup
                    try:
                        await popup.wait_for_load_state("domcontentloaded", timeout=6_000)
                    except Exception:
                        pass
                    self.application_url = popup.url
                    await self.record("apply_popup_opened", url=popup.url)
                    return True
            except Exception:
                pass
            await short_wait(page, APPLY_POLL_MS)

        self._active_page = page
        await short_wait(page, 750)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:
            pass
        await short_wait(page, 500)

        if page.url != old_url:
            await self.record("application_navigation_detected", url=page.url)
        else:
            await self.record("application_navigation_same_url")

        self.application_url = page.url
        return True

    # ========================================================
    # FORM READINESS
    # ========================================================

    async def get_form_signals(
        self,
        page: Page,
    ) -> dict[str, Any]:

        signals = {
            "inputs": 0,
            "selects": 0,
            "textareas": 0,
            "buttons": 0,
            "files": 0,
            "checkboxes": 0,
            "submit": 0,
            "first_name": 0,
            "last_name": 0,
            "email": 0,
            "phone": 0,
            "resume": 0,
            "terms": 0,
        }

        try:
            controls = page.locator(
                "input, textarea, select, button"
            )
            count = await controls.count()
            controls_data = await controls.evaluate_all(
                """
                elements => elements.map(el => ({
                    tag: (el.tagName || '').toLowerCase(),
                    type: (el.getAttribute('type') || '').toLowerCase(),
                    name: (el.getAttribute('name') || '').toLowerCase(),
                    id: (el.getAttribute('id') || '').toLowerCase(),
                    placeholder: (el.getAttribute('placeholder') || '').toLowerCase(),
                    aria: (el.getAttribute('aria-label') || '').toLowerCase(),
                }))
                """
            )
        except Exception:
            return signals

        signals["total"] = count

        for data in controls_data:
            tag = normalize(data.get("tag"))
            field_type = normalize(data.get("type"))
            name = normalize(data.get("name"))
            element_id = normalize(data.get("id"))
            placeholder = normalize(data.get("placeholder"))
            aria = normalize(data.get("aria"))

            combined = " ".join([name, element_id, placeholder, aria])

            if tag == "input":
                signals["inputs"] += 1
            elif tag == "select":
                signals["selects"] += 1
            elif tag == "textarea":
                signals["textareas"] += 1
            elif tag == "button":
                signals["buttons"] += 1

            if field_type == "file":
                signals["files"] += 1
            if field_type == "checkbox":
                signals["checkboxes"] += 1
            if field_type == "submit":
                signals["submit"] += 1
            if "firstname" in combined or "first_name" in combined:
                signals["first_name"] += 1
            if "lastname" in combined or "last_name" in combined:
                signals["last_name"] += 1
            if "email" in combined:
                signals["email"] += 1
            if "phone" in combined or "mobile" in combined or "telephone" in combined:
                signals["phone"] += 1
            if ("resume" in combined or "cv" in combined) and field_type == "file":
                signals["resume"] += 1
            if "terms" in combined or "privacy" in combined or "termscondition" in combined:
                signals["terms"] += 1

        return signals

    async def wait_for_application_form(
        self,
        page: Page,
        allow_minimal_form: bool = False,
    ) -> bool:

        await self.record(
            "waiting_for_full_application_form"
        )

        deadline = (
            asyncio.get_running_loop().time()
            + FORM_WAIT_TIMEOUT / 1000
        )

        last_signature = None
        stable_count = 0

        while (
            asyncio.get_running_loop().time()
            < deadline
        ):

            signals = await self.get_form_signals(
                page
            )

            strong_signal = (
                signals["first_name"] > 0
                and signals["email"] > 0
                and signals["phone"] > 0
            )

            complete_signal = (
                signals["resume"] > 0
                and signals["terms"] > 0
                and signals["submit"] > 0
            )

            meaningful_form = (
                signals["inputs"]
                + signals["selects"]
                + signals["textareas"]
                >= 8
            )

            # An external platform adapter has already clicked a verified
            # Apply CTA and captured this owned page. Many real ATS flows are
            # multi-step and initially expose only one or two controls, so do
            # not reject a genuine first step merely because it is not a long
            # all-fields-on-one-page form.
            minimal_handoff_form = (
                allow_minimal_form
                and (
                    signals["files"] > 0
                    or signals["selects"] > 0
                    or signals["textareas"] > 0
                    or signals["inputs"] >= 3
                    or (signals["inputs"] >= 1 and signals["buttons"] >= 2)
                )
            )

            ready = (
                strong_signal
                or complete_signal
                or (
                    meaningful_form
                    and signals["submit"] > 0
                )
                or minimal_handoff_form
            )

            signature = (
                signals["inputs"],
                signals["selects"],
                signals["textareas"],
                signals["files"],
                signals["checkboxes"],
                signals["submit"],
                signals["first_name"],
                signals["email"],
                signals["resume"],
                signals["terms"],
            )

            if signature == last_signature:

                stable_count += 1

            else:

                stable_count = 0
                last_signature = signature

            if ready and stable_count >= 2:

                await self.record(
                    "application_form_ready",
                    signals=signals,
                    mode=("minimal_handoff" if minimal_handoff_form and not (strong_signal or complete_signal or (meaningful_form and signals["submit"] > 0)) else "full_form"),
                )

                return True

            await short_wait(
                page,
                750,
            )

        signals = await self.get_form_signals(
            page
        )

        await self.record(
            "application_form_timeout",
            signals=signals,
        )

        return False

    # ========================================================
    # FIELD LABEL
    # ========================================================

    async def find_label(
        self,
        element,
    ) -> str:
        """Resolve the label attached to one control inside any frame.

        The old implementation queried ``label[for=...]`` relative to the
        input locator itself, which only searches descendants of the input and
        therefore misses the normal sibling ``<label>`` used by real external
        forms.  Use the control's own document so same-frame labels, ARIA
        references, and component-library labels stay frame-safe.
        """
        try:
            text = await element.evaluate(
                """el => {
                    const clean = value => String(value || '').replace(/\\s+/g, ' ').trim();
                    const id = el.getAttribute('id');
                    if (id) {
                        const label = Array.from(document.querySelectorAll('label')).find(node => node.htmlFor === id);
                        if (label) return clean(label.innerText || label.textContent);
                    }
                    const labelledby = el.getAttribute('aria-labelledby') || '';
                    const parts = [];
                    for (const ref of labelledby.split(/\\s+/).filter(Boolean)) {
                        const node = document.getElementById(ref);
                        if (node) parts.push(clean(node.innerText || node.textContent));
                    }
                    if (parts.length) return clean(parts.join(' '));
                    const ancestorLabel = el.closest('label');
                    if (ancestorLabel) return clean(ancestorLabel.innerText || ancestorLabel.textContent);
                    const field = el.closest('mat-form-field');
                    if (field) {
                        const label = field.querySelector('mat-label, .mdc-floating-label');
                        if (label) return clean(label.innerText || label.textContent);
                    }
                    return '';
                }"""
            )
            text = clean_text(text)
            if text:
                return text
        except Exception:
            pass

        # Safe parent fallback: only use a container if it contains this
        # control and no sibling form controls. This prevents a neighbouring
        # field's label from contaminating classification.
        for levels in (1, 2, 3):
            try:
                node = element
                for _ in range(levels):
                    node = node.locator("xpath=..")
                controls = node.locator("input, textarea, select")
                if await controls.count() != 1:
                    continue
                text = clean_text(await node.inner_text())
                if text and len(text) <= 240:
                    return text
            except Exception:
                continue

        return ""

    # ========================================================
    # FIELD CONTEXT
    # ========================================================

    async def get_context(
        self,
        element,
    ) -> str:

        try:

            value = await element.evaluate(
                """
                el => {
                    const parts = [];

                    if (el.parentElement) {
                        parts.push(
                            el.parentElement.innerText ||
                            el.parentElement.textContent ||
                            ''
                        );
                    }

                    if (
                        el.parentElement &&
                        el.parentElement.parentElement
                    ) {
                        parts.push(
                            el.parentElement.parentElement.innerText ||
                            el.parentElement.parentElement.textContent ||
                            ''
                        );
                    }

                    return parts.join(' ')
                        .replace(/\\s+/g, ' ')
                        .trim();
                }
                """
            )

            return clean_text(
                value[:1000]
            )

        except Exception:

            return ""

    # ========================================================
    # FORM INSPECTION
    # ========================================================

    async def inspect_form(
        self,
        page: Page,
    ) -> list[dict[str, Any]]:

        locator = page.locator(
            "input, textarea, select, button"
        )

        try:

            count = await locator.count()

        except Exception:

            count = 0

        fields = []

        for i in range(count):

            element = locator.nth(i)

            try:

                if not await element.is_visible():
                    continue

            except Exception:

                continue

            try:

                tag = normalize(
                    await element.evaluate(
                        "el => el.tagName"
                    )
                )

                field_type = normalize(
                    await element.get_attribute(
                        "type"
                    )
                )

                name = (
                    await element.get_attribute(
                        "name"
                    )
                    or ""
                )

                element_id = (
                    await element.get_attribute(
                        "id"
                    )
                    or ""
                )

                placeholder = (
                    await element.get_attribute(
                        "placeholder"
                    )
                    or ""
                )

                aria = (
                    await element.get_attribute(
                        "aria-label"
                    )
                    or ""
                )

                required_attr = (
                    await element.get_attribute(
                        "required"
                    )
                )

                aria_required = (
                    await element.get_attribute(
                        "aria-required"
                    )
                )

            except Exception:

                continue

            label = await self.find_label(
                element
            )

            context = await self.get_context(
                element
            )

            value = ""

            try:

                value = await element.input_value()

            except Exception:
                pass

            checked = False

            if field_type in {
                "checkbox",
                "radio",
            }:

                try:

                    checked = await element.is_checked()

                except Exception:
                    pass

            required = (
                required_attr is not None
                or normalize(
                    aria_required
                ) == "true"
            )

            fields.append(
                {
                    "index": i,
                    "element": element,
                    "tag": tag,
                    "type": field_type,
                    "name": name,
                    "id": element_id,
                    "label": label,
                    "placeholder": placeholder,
                    "aria_label": aria,
                    "context": context,
                    "value": value,
                    "checked": checked,
                    "required": required,
                }
            )

        await self.record(
            "form_inspected",
            fields=len(fields),
        )

        return fields

    # ========================================================
    # CLASSIFICATION
    # ========================================================

    def classify(
        self,
        field: dict[str, Any],
    ) -> str:

        tag = normalize(
            field["tag"]
        )

        field_type = normalize(
            field["type"]
        )

        name = normalize(
            field["name"]
        )

        element_id = normalize(
            field["id"]
        )

        label = normalize(
            field["label"]
        )

        placeholder = normalize(
            field["placeholder"]
        )

        aria = normalize(
            field["aria_label"]
        )

        context = normalize(
            field["context"]
        )

        strong = " ".join(
            [
                name,
                element_id,
            ]
        )

        text = " ".join(
            [
                strong,
                label,
                placeholder,
                aria,
                context,
            ]
        )

        # High-confidence field identity must beat the declared HTML type.
        # Some ATSs incorrectly mark Full Name as type=email.  Use the
        # visible field label / aria label first, and only fall back to the
        # technical type when the semantic label is absent.
        explicit = " ".join([label, aria, placeholder]).strip()
        explicit_norm = normalize(explicit)
        text_norm = normalize(text)

        if any(
            phrase in text_norm
            for phrase in (
                "leave this field empty",
                "do not fill this field",
                "honeypot",
            )
        ):
            return "honeypot"

        if re.search(r"\bmiddle\s+name\b", explicit_norm):
            return "unknown"
        if re.search(r"\bfirst\s+name\b", explicit_norm):
            return "first_name"
        if re.search(r"\b(?:last|family)\s+name\b|\bsurname\b", explicit_norm):
            return "last_name"
        if re.search(r"\b(?:full|candidate)\s+name\b", explicit_norm):
            return "full_name"
        if re.search(r"\b(?:e[- ]?mail|email\s+id|email address)\b", explicit_norm):
            return "email"
        if re.search(r"\b(?:phone|mobile(?:\s+(?:number|no))?|telephone|contact number|contact no)\b", explicit_norm):
            return "phone"

        # ----------------------------------------------------
        # Exact company-form mappings.
        # These take priority over broad context text so that
        # RippleHire fields are mapped to the correct profile
        # value instead of being skipped or misclassified.
        # ----------------------------------------------------

        exact_key = normalize(
            " ".join([name, element_id])
        ).replace(" ", "")

        if exact_key in {"firstname"}:
            return "first_name"

        if exact_key in {"middlename"}:
            return "unknown"

        if exact_key in {"lastname"}:
            return "last_name"

        if exact_key in {"emailaddr"}:
            return "email"

        if exact_key in {"phoneno"}:
            return "phone"

        if exact_key in {"currentlocation"}:
            return "current_location"

        if exact_key in {"noticeperiodselect"}:
            return "notice_period"

        if exact_key in {"currentctc"}:
            return "current_ctc"

        if exact_key in {"expectedctc"}:
            return "expected_ctc"

        if exact_key in {"expyears"}:
            return "experience"

        if exact_key in {"expmonths"}:
            return "experience_months"

        if exact_key in {"custom6"}:
            return "work_authorization"

        if exact_key in {"preferredlocation"}:
            return "preferred_location"

        if exact_key in {"preferredlocation2"}:
            return "preferred_location_2"

        if exact_key in {"preferredlocation3"}:
            return "preferred_location_3"

        # ----------------------------------------------------
        # Submit
        # ----------------------------------------------------

        if (
            field_type == "submit"
            or (
                "submit" in text
                and tag == "button"
            )
        ):
            return "submit"

        # ----------------------------------------------------
        # Resume
        # ----------------------------------------------------

        if field_type == "file":

            if any(
                x in text
                for x in [
                    "resume",
                    "cv",
                    "curriculum vitae",
                ]
            ):
                return "resume"

            return "file"

        # ----------------------------------------------------
        # Checkbox
        # ----------------------------------------------------

        if field_type == "checkbox":

            if any(
                x in text
                for x in [
                    "terms",
                    "terms of use",
                    "terms and conditions",
                    "privacy",
                    "privacy policy",
                    "termscondition",
                ]
            ):
                return "terms"

            return "checkbox"

        # ----------------------------------------------------
        # Radio
        # ----------------------------------------------------

        if field_type == "radio":
            return "radio"

        # ----------------------------------------------------
        # Email
        # ----------------------------------------------------

        # Do not trust the raw HTML type alone. Some ATS forms declare a
        # narrative field (for example "Message") as type=email, and some
        # page-level context contains the word "email" even though the field
        # is not asking for contact information. Only explicit field metadata
        # can authorize the email semantic.
        explicit_email_signal = bool(
            re.search(
                r"\b(?:e[- ]?mail|email\s+id|email address)\b",
                explicit_norm,
            )
            or re.search(r"(?:^|[\W_])email(?:[\W_]|$)", name)
            or re.search(r"(?:^|[\W_])email(?:[\W_]|$)", element_id)
        )
        narrative_signal = bool(
            re.search(
                r"\b(?:message|tell\s+us|about\s+(?:yourself|you)|relevant\s+experience|experience|summary|motivation|cover\s+letter|introduction|why\s+(?:do|are|should)|additional\s+information)\b",
                explicit_norm,
            )
            or tag == "textarea"
        )

        if "email" in text and not explicit_email_signal and narrative_signal:
            return "message"
        if field_type == "email" and explicit_email_signal:
            return "email"

        # ----------------------------------------------------
        # Phone
        # ----------------------------------------------------

        if (
            field_type == "tel"
            or any(
                x in text
                for x in [
                    "phone",
                    "mobile",
                    "telephone",
                    "contact number",
                ]
            )
        ):
            return "phone"

        # ----------------------------------------------------
        # First name
        # ----------------------------------------------------

        if any(
            x in text
            for x in [
                "firstname",
                "first name",
                "given name",
                "fname",
            ]
        ):
            return "first_name"

        # ----------------------------------------------------
        # Last name
        # ----------------------------------------------------

        if any(
            x in text
            for x in [
                "lastname",
                "last name",
                "surname",
                "family name",
                "lname",
            ]
        ):
            return "last_name"

        # ----------------------------------------------------
        # Full name
        # ----------------------------------------------------

        if any(
            x in text
            for x in [
                "full name",
                "fullname",
                "candidate name",
            ]
        ):
            return "full_name"

        # ----------------------------------------------------
        # Current location
        # ----------------------------------------------------

        if any(
            x in text
            for x in [
                "currentlocation",
                "current location",
                "current city",
            ]
        ):
            return "current_location"

        # ----------------------------------------------------
        # Preferred location
        # ----------------------------------------------------

        if (
            "preferred location" in text
            and not any(
                x in text
                for x in [
                    "preferred location 2",
                    "preferred location2",
                    "preferred location 3",
                    "preferred location3",
                ]
            )
        ):
            return "preferred_location"

        # ----------------------------------------------------
        # Secondary preferred location
        # ----------------------------------------------------

        if any(
            x in text
            for x in [
                "preferred location 2",
                "preferred location2",
                "preferred location 3",
                "preferred location3",
            ]
        ):
            return "secondary_preferred_location"

        # ----------------------------------------------------
        # Experience
        # ----------------------------------------------------

        if (
            "experience" in text
            or "expyears" in strong
        ):

            if (
                "month" in text
                or "expmonths" in strong
            ):
                return "experience_months"

            # Open-ended text such as "Experience and projects" is a
            # question, not a numeric duration.  Let Custom Q&A / the
            # reasoner handle it instead of writing 0 into a textarea.
            if tag == "textarea" or field_type in {"text", "search", ""}:
                duration_cue = bool(re.search(
                    r"\b(?:how many years?|years? of experience|experience in years|total years|number of years)\b",
                    text,
                    re.I,
                ))
                if not duration_cue:
                    return "unknown"

            return "experience"

        # ----------------------------------------------------
        # Current company
        # ----------------------------------------------------

        if any(
            x in text
            for x in [
                "current company",
                "current employer",
                "employer",
            ]
        ):
            return "current_company"

        # ----------------------------------------------------
        # Notice period
        # ----------------------------------------------------

        if (
            "notice period" in text
            or "noticeperiod" in strong
        ):
            return "notice_period"

        # ----------------------------------------------------
        # Work authorization
        # ----------------------------------------------------

        if any(
            x in text
            for x in [
                "legally authorized",
                "work authorization",
                "authorized to work",
                "needs sponsorship",
            ]
        ):
            return "work_authorization"

        # ----------------------------------------------------
        # Sponsorship
        # ----------------------------------------------------

        if "sponsorship" in text:
            return "sponsorship"

        # ----------------------------------------------------
        # Relocation
        # ----------------------------------------------------

        if (
            "relocation" in text
            or "relocate" in text
        ):
            return "relocation"

        # ----------------------------------------------------
        # Salary — Expected vs Current
        # ----------------------------------------------------

        if any(
            x in text
            for x in [
                "expected ctc",
                "expected salary",
                "expected annual",
                "expected compensation",
                "expectedctc",
            ]
        ):
            return "expected_ctc"

        if any(
            x in text
            for x in [
                "current ctc",
                "current salary",
                "last drawn",
                "current/ last drawn",
                "current compensation",
                "currentctc",
            ]
        ):
            return "current_ctc"

        if any(
            x in text
            for x in [
                "salary",
                "ctc",
                "compensation",
            ]
        ):
            return "salary"

        # ----------------------------------------------------
        # DOB
        # ----------------------------------------------------

        if (
            "date of birth" in text
            or name in {
                "day",
                "month",
                "year",
            }
        ):
            return "date"

        # ----------------------------------------------------
        # Gender
        # ----------------------------------------------------

        if "gender" in text:
            return "gender"

        # ----------------------------------------------------
        # Links
        # ----------------------------------------------------

        if "linkedin" in text:
            return "linkedin"

        if "github" in text:
            return "github"

        if "portfolio" in text:
            return "portfolio"

        # ----------------------------------------------------
        # Education
        # ----------------------------------------------------

        if any(
            x in text
            for x in [
                "education",
                "degree",
                "qualification",
                "university",
                "college",
            ]
        ):
            return "education"

        if tag == "textarea":
            return "unknown"

        return "unknown"

    # ========================================================
    # PROFILE VALUE
    # ========================================================

    def get_value(
        self,
        semantic: str,
    ):

        if semantic == "first_name":
            value = self.profile_get(
                "first_name",
                "firstname",
            )
            if value:
                return value
            full_name = self.profile_get("full_name", "name", default="")
            parts = str(full_name).strip().split()
            return parts[0] if parts else None

        if semantic == "last_name":
            value = self.profile_get(
                "last_name",
                "lastname",
                "surname",
            )
            if value:
                return value
            full_name = self.profile_get("full_name", "name", default="")
            parts = str(full_name).strip().split()
            return " ".join(parts[1:]) if len(parts) > 1 else None

        if semantic == "full_name":

            return self.profile_get(
                "full_name",
                "name",
            )

        if semantic == "email":

            return self.profile_get(
                "email",
                "email_address",
            )

        if semantic == "phone":

            return self.profile_get(
                "phone",
                "phone_number",
                "mobile",
            )

        if semantic == "current_location":

            return self.profile_get(
                "current_location",
                "city",
                "location",
            )

        if semantic == "preferred_location":

            return self.profile_get(
                "preferred_location",
                "preferred_city",
                "city",
                "location",
            )

        if semantic in {
            "preferred_location_2",
            "preferred_location_3",
        }:

            return self.profile_get(
                "preferred_location",
                "preferred_city",
                "city",
                "location",
            )

        if semantic == "experience":

            return self.profile_get(
                "total_experience",
                "total_experience_years",
                "experience_years",
                "years_of_experience",
                default=0,
            )

        if semantic == "experience_months":

            return self.profile_get(
                "experience_months",
                "total_experience_months",
                default=0,
            )

        if semantic == "current_company":

            return self.profile_get(
                "current_company",
            )

        if semantic == "notice_period":
            return self.profile_get(
                "notice_period",
                "notice_period_days",
                default=0,
            )

        if semantic == "linkedin":

            return self.profile_get(
                "linkedin",
                "linkedin_url",
            )

        if semantic == "github":

            return self.profile_get(
                "github",
                "github_url",
            )

        if semantic == "portfolio":

            return self.profile_get(
                "portfolio",
                "portfolio_url",
                "website",
            )

        if semantic == "education":

            return self.profile_get(
                "education",
                "highest_education",
                "degree",
            )

        # ----------------------------------------------------
        # DOB
        # ----------------------------------------------------

        if semantic == "date":

            return self.profile_get(
                "date_of_birth",
                "dob",
                "birth_date",
            )

        # ----------------------------------------------------
        # Expected CTC
        # Profile value wins if present; otherwise falls back
        # to the requested "4,00,000" default.
        # ----------------------------------------------------

        if semantic == "expected_ctc":

            return self.profile_get(
                "expected_ctc",
                "expected_salary",
                "expected_annual_ctc",
                default="4,00,000",
            )

        if semantic == "current_ctc":

            return self.profile_get(
                "current_ctc",
                "current_salary",
                default=0,
            )

        return None

    # ========================================================
    # TEXT FILL
    # ========================================================

    async def fill_text(
        self,
        field: dict[str, Any],
        semantic: str,
        value: Any,
    ) -> bool:

        if value is None:
            return False

        value = str(value).strip()

        if not value:
            return False

        element = field["element"]

        try:

            current = ""

            try:

                current = await element.input_value()

            except Exception:
                pass

            if current.strip():
                return False

            await element.fill(
                value
            )

            await short_wait(
                element.page,
                200,
            )

            actual = ""

            try:

                actual = await element.input_value()

            except Exception:
                pass

            if normalize(actual) == normalize(value):

                self.fields_filled += 1

                await self.record(
                    "field_filled",
                    semantic=semantic,
                    label=field["label"],
                    name=field["name"],
                    id=field["id"],
                )

                return True

            await element.fill(
                value
            )

            await short_wait(
                element.page,
                200,
            )

            actual = await element.input_value()

            if normalize(actual) == normalize(value):

                self.fields_filled += 1

                await self.record(
                    "field_filled_retry",
                    semantic=semantic,
                    label=field["label"],
                    name=field["name"],
                )

                return True

        except Exception as exc:

            await self.record(
                "field_fill_error",
                semantic=semantic,
                label=field["label"],
                error=str(exc),
            )

        return False

    # ========================================================
    # SELECT OPTIONS
    # ========================================================

    async def get_options(
        self,
        element,
    ):

        try:

            return await element.locator(
                "option"
            ).evaluate_all(
                """
                options => options.map(o => ({
                    value: o.value,
                    text: (
                        o.innerText ||
                        o.textContent ||
                        ''
                    ).trim()
                }))
                """
            )

        except Exception:

            return []

    # ========================================================
    # SELECT FILL
    # ========================================================

    async def fill_select(
        self,
        field: dict[str, Any],
        semantic: str,
        value: Any,
    ) -> bool:

        if value is None:
            return False

        element = field["element"]

        # Never overwrite/recount a select that is already filled.
        try:
            current = await element.input_value()
            if str(current).strip():
                return False
        except Exception:
            pass

        options = await self.get_options(
            element
        )

        if not options:
            return False

        wanted = normalize(
            value
        )

        # ----------------------------------------------------
        # DOB MONTH
        # Convert numeric month to month name.
        # Example:
        # 9 -> September
        # 09 -> September
        # ----------------------------------------------------

        field_text = normalize(
            " ".join(
                [
                    field.get("name", ""),
                    field.get("id", ""),
                    field.get("label", ""),
                    field.get("placeholder", ""),
                ]
            )
        )

        if (
            semantic == "date"
            and "month" in field_text
        ):

            months = {
                "1": "january",
                "01": "january",

                "2": "february",
                "02": "february",

                "3": "march",
                "03": "march",

                "4": "april",
                "04": "april",

                "5": "may",
                "05": "may",

                "6": "june",
                "06": "june",

                "7": "july",
                "07": "july",

                "8": "august",
                "08": "august",

                "9": "september",
                "09": "september",

                "10": "october",
                "11": "november",
                "12": "december",
            }

            wanted = months.get(
                wanted,
                wanted,
            )

        # ----------------------------------------------------
        # NOTICE PERIOD
        # 0 = Can join immediately
        # ----------------------------------------------------

        if semantic == "notice_period":

            notice_map = {
                "0": "can join immediately",
                "0 days": "can join immediately",
                "immediate": "can join immediately",
                "immediately": "can join immediately",
            }

            wanted = notice_map.get(
                wanted,
                wanted,
            )

        selected = None

        # ----------------------------------------------------
        # Exact match
        # ----------------------------------------------------

        for option in options:

            option_value = normalize(
                option["value"]
            )

            option_text = normalize(
                option["text"]
            )

            if (
                wanted == option_value
                or wanted == option_text
            ):

                selected = option

                break

        # ----------------------------------------------------
        # Partial match
        # ----------------------------------------------------

        if selected is None:

            for option in options:

                option_value = normalize(
                    option["value"]
                )

                option_text = normalize(
                    option["text"]
                )

                if (
                    wanted in option_text
                    or option_text in wanted
                    or wanted in option_value
                ):

                    selected = option

                    break

        # ----------------------------------------------------
        # Numeric/range experience matching
        # Handles 0, 0-2, 0–2, 0—2, 0−2, "0 to 2 years",
        # "less than 1 year", "3+", etc.
        # ----------------------------------------------------

        if (
            selected is None
            and semantic in {
                "experience",
                "experience_months",
            }
        ):
            raw = str(value).strip().lower()
            nums = re.findall(r"\d+(?:\.\d+)?", raw)

            try:
                wanted_number = float(nums[0]) if nums else None
            except Exception:
                wanted_number = None

            if wanted_number is not None:
                ranked = []

                for index, option in enumerate(options):
                    option_text = normalize(option.get("text", ""))
                    option_value = normalize(option.get("value", ""))
                    combined = f"{option_text} {option_value}".strip()

                    score = 0.0
                    if raw in {"0", "0 years", "0 year", "fresher", "less than 1 year"}:
                        if any(x in combined for x in ("fresher", "no experience", "less than 1 year")):
                            score = 100.0

                    range_match = re.search(
                        r"(\d+(?:\.\d+)?)\s*(?:-|–|—|−|to)\s*(\d+(?:\.\d+)?)",
                        combined,
                    )
                    plus_match = re.search(r"(\d+(?:\.\d+)?)\s*\+", combined)
                    less_match = re.search(
                        r"(?:less than|under|below)\s*(\d+(?:\.\d+)?)",
                        combined,
                    )

                    if range_match:
                        low = float(range_match.group(1))
                        high = float(range_match.group(2))
                        if low <= wanted_number <= high:
                            # Prefer the narrowest matching range and exact lower bound.
                            score = max(score, 80.0 + (20.0 if wanted_number == low else 0.0) - (high - low))
                    elif less_match:
                        high = float(less_match.group(1))
                        if wanted_number < high:
                            score = max(score, 85.0 - high)
                    elif plus_match:
                        low = float(plus_match.group(1))
                        if wanted_number >= low:
                            score = max(score, 70.0 + (20.0 if wanted_number == low else 0.0))
                    elif re.fullmatch(r"\d+(?:\.\d+)?", option_text) or re.fullmatch(r"\d+(?:\.\d+)?", option_value):
                        try:
                            exact_num = float(option_text if re.fullmatch(r"\d+(?:\.\d+)?", option_text) else option_value)
                            if exact_num == wanted_number:
                                score = max(score, 95.0)
                        except Exception:
                            pass

                    if score > 0:
                        ranked.append((score, -index, option))

                if ranked:
                    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
                    selected = ranked[0][2]

        if selected is None:

            await self.record(
                "select_option_not_found",
                semantic=semantic,
                label=field["label"],
                requested=value,
            )

            return False

        try:

            await element.select_option(
                selected["value"]
            )

            await short_wait(
                element.page,
                250,
            )

            actual = await element.input_value()

            if normalize(actual) == normalize(
                selected["value"]
            ):

                self.fields_filled += 1

                await self.record(
                    "select_filled",
                    semantic=semantic,
                    label=field["label"],
                    value=selected["value"],
                    text=selected["text"],
                )

                return True

        except Exception as exc:

            await self.record(
                "select_fill_error",
                semantic=semantic,
                label=field["label"],
                error=str(exc),
            )

        return False

    # ========================================================
    # CUSTOM Q&A
    # ========================================================

    def _custom_answer(self, field: dict[str, Any]):
        """Return an exact saved answer for a field, if any.

        Check the actual field label first, then contextual variants. This is
        important for company forms whose helper text/question context can be
        longer or different from the visible field label. The semantic
        ProfileReasoner handles fuzzy matching after routing.
        """
        try:
            from custom_qa_store import find_custom_answer
        except Exception:
            return None

        candidates = []
        for key in (
            "label",
            "question_context",
            "placeholder",
            "aria_label",
            "name",
            "id",
            "context",
        ):
            value = str(field.get(key) or "").strip()
            if value and value not in candidates:
                candidates.append(value)

        options = []
        for item in field.get("options") or []:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
            else:
                text = str(item).strip()
            if text and text not in options:
                options.append(text)

        best = None
        for question in candidates:
            try:
                result = find_custom_answer(question, options=options or None, exact_only=True)
            except Exception:
                continue
            if result and (best is None or float(result.get("score", 0)) > float(best.get("score", 0))):
                best = result

        return best

    # ========================================================
    # FILL STANDARD FIELDS
    # ========================================================


    def _external_profile_values(self):
        """Flattened, truthful values used by the proven external-form pass.

        This mirrors the earlier V16/V21 company-site strategy: classify by the
        actual field metadata/context first, then fill from profile facts.
        Unknown facts are left for Custom Q&A / ProfileReasoner.
        """
        online = self.profile.get("online_profiles", {}) or {}
        candidate = self.profile.get("candidate", {}) or {}
        compensation = self.profile.get("compensation", {}) or {}
        return {
            "first_name": self.get_value("first_name"),
            "last_name": self.get_value("last_name"),
            "full_name": self.get_value("full_name"),
            "email": self.get_value("email"),
            "phone": self.get_value("phone"),
            "city": self.get_value("current_location"),
            "address": self.profile_get("street_address", "address", default=""),
            "state": self.profile_get("state", default=""),
            "country": self.profile_get("country", "work_country", default=""),
            "pin_code": self.profile_get("pin_code", "pincode", default=""),
            "current_company": "N/A - Fresher / Graduate" if not candidate.get("currently_employed") else self.get_value("current_company"),
            "notice_period": self.get_value("notice_period"),
            "expected_ctc": self.get_value("expected_ctc"),
            "current_ctc": self.get_value("current_ctc"),
            "total_experience": self.get_value("experience"),
            "linkedin": online.get("linkedin") or self.get_value("linkedin"),
            "github": online.get("github") or self.get_value("github"),
            "website": self.get_value("portfolio") or online.get("linkedin") or online.get("github"),
            "job_role": self.profile_get("application_job_role", "job_role", default=""),
            "age": self.profile_get("age", default=""),
        }

    async def fill_external_profile_fields_deterministically(self, page: Page) -> int:
        """V16/V21-style deterministic external-company field pass.

        This pass intentionally happens before the generic AI/QA engine. It
        scans the visible main document and every frame, uses the actual field
        label/attributes plus nearby field text, and fills only values that are
        already present in the candidate profile. Unknown items are left for
        Custom Q&A / ProfileReasoner.
        """
        values = self._external_profile_values()
        rules = [
            (["first name", "given name", "fname"], "first_name"),
            (["last name", "surname", "family name", "lname"], "last_name"),
            (["full name", "your name", "candidate name", "applicant name", "legal name"], "full_name"),
            (["email", "e-mail"], "email"),
            (["phone", "mobile", "telephone", "contact number", "contact no", "contactno", "phone no", "phone number", "mobile no", "mobile number"], "phone"),
            (["pin code", "pincode", "postal code", "zip code", "zipcode"], "pin_code"),
            (["address", "street address", "residential address", "home address", "current address"], "address"),
            (["city", "town", "place", "current place", "current city", "current location", "location"], "city"),
            (["state", "province"], "state"),
            (["country"], "country"),
            (["current company", "current employer"], "current_company"),
            (["notice period"], "notice_period"),
            (["expected ctc", "expected salary", "expected compensation", "expected annual"], "expected_ctc"),
            (["current ctc", "current salary", "last drawn"], "current_ctc"),
            (["total experience", "years of experience", "work experience"], "total_experience"),
            (["linkedin"], "linkedin"),
            (["website", "links", "portfolio", "personal website"], "website"),
            (["position", "job role", "role applying", "role to which you want to apply"], "job_role"),
            (["age"], "age"),
        ]

        filled = 0
        seen = set()

        async def parent_context(el):
            chunks = []
            try:
                node = el
                for _ in range(6):
                    node = node.locator("xpath=..")
                    if await node.count():
                        txt = clean_text(await node.first.inner_text())
                        if txt and len(txt) <= 1200:
                            chunks.append(txt)
            except Exception:
                pass
            return " ".join(chunks)

        async def process_frame(frame):
            nonlocal filled
            try:
                controls = frame.locator(
                    "input:visible, textarea:visible, select:visible, [role='combobox']:visible"
                )
                count = await controls.count()
            except Exception:
                return

            for i in range(count):
                el = controls.nth(i)
                try:
                    if not await el.is_visible() or await el.is_disabled():
                        continue
                except Exception:
                    continue

                try:
                    tag = normalize(await el.evaluate("e => e.tagName"))
                    field_type = normalize(await el.get_attribute("type") or "")
                    name = normalize(await el.get_attribute("name") or "")
                    element_id = normalize(await el.get_attribute("id") or "")
                    placeholder = normalize(await el.get_attribute("placeholder") or "")
                    aria = normalize(await el.get_attribute("aria-label") or "")
                    title = normalize(await el.get_attribute("title") or "")
                    autocomplete = normalize(await el.get_attribute("autocomplete") or "")
                    label = normalize(await self.find_label(el) or "")
                    nearby = normalize(await parent_context(el))
                except Exception:
                    continue

                # Never touch hidden/password/submit/file/checkbox/radio controls here.
                if field_type in {"hidden", "password", "submit", "button", "file", "checkbox", "radio", "reset", "image"}:
                    continue

                # Direct field metadata is authoritative. Nearby parent text can
                # contain labels for sibling controls (e.g. Email, Mobile, Name)
                # and must never override the current input's own identity.
                direct = " ".join(x for x in (label, placeholder, aria, title) if x)
                strong = " ".join(x for x in (name, element_id, autocomplete) if x)
                direct_norm = normalize(direct)
                strong_norm = normalize(strong)

                direct_rules = [
                    (r"\b(?:first|given)\s+name\b|\bfname\b", "first_name"),
                    (r"\b(?:last|family)\s+name\b|\bsurname\b|\blname\b", "last_name"),
                    (r"\b(?:full\s+name|your\s+name|candidate\s+name|applicant\s+name|legal\s+name)\b|^name\b", "full_name"),
                    (r"\b(?:e[- ]?mail|email\s+id|email\s+address)\b", "email"),
                    (r"\b(?:phone|mobile|telephone|contact\s*(?:number|no)|phone\s*(?:number|no)|mobile\s*(?:number|no))\b", "phone"),
                    (r"\bpin\s*code\b|\bpincode\b|\bpostal\s*code\b|\bzip\s*code\b|\bzipcode\b", "pin_code"),
                    (r"\b(?:address|street\s+address|residential\s+address|home\s+address|current\s+address)\b", "address"),
                    (r"\b(?:city|town|place|current\s+place|current\s+city|current\s+location|location)\b", "city"),
                    (r"\bstate\b|\bprovince\b", "state"),
                    (r"\bcountry\b", "country"),
                    (r"\bcurrent\s+(?:company|employer)\b", "current_company"),
                    (r"\bnotice\s+period\b", "notice_period"),
                    (r"\bexpected\s+(?:ctc|salary|compensation|annual)\b", "expected_ctc"),
                    (r"\b(?:current\s+ctc|current\s+salary|last\s+drawn)\b", "current_ctc"),
                    (r"\b(?:total\s+experience|years\s+of\s+experience|work\s+experience)\b", "total_experience"),
                    (r"\blinkedin\b", "linkedin"),
                    (r"\bgithub\b", "github"),
                    (r"\b(?:website|portfolio)\b", "website"),
                    (r"\b(?:position|job\s+role|role\s+applying|role\s+to\s+which\s+you\s+want\s+to\s+apply)\b", "job_role"),
                    (r"\bage\b", "age"),
                ]

                strong_rules = [
                    (r"\b(?:first|given)\s*name\b|\bfname\b", "first_name"),
                    (r"\b(?:last|family)\s*name\b|\bsurname\b|\blname\b", "last_name"),
                    (r"\b(?:full|candidate)\s*name\b|\bname\b", "full_name"),
                    (r"\b(?:e[- ]?mail|email|emailaddr)\b", "email"),
                    (r"\b(?:phone|mobile|tel|phoneno|contact)\b", "phone"),
                    (r"\b(?:city|town|place|currentplace|currentcity|currentlocation|location)\b", "city"),
                    (r"\b(?:address|streetaddress|residentialaddress|homeaddress|currentaddress)\b", "address"),
                    (r"\bstate\b|\bprovince\b", "state"),
                    (r"\bcountry\b", "country"),
                    (r"\bnoticeperiod\b", "notice_period"),
                    (r"\bexpectedctc\b|\bexpectedsalary\b", "expected_ctc"),
                    (r"\bcurrentctc\b|\bcurrentsalary\b", "current_ctc"),
                    (r"\blinkedin\b", "linkedin"),
                    (r"\bgithub\b", "github"),
                    (r"\b(?:website|portfolio|links)\b", "website"),
                    (r"\bposition\b|\bjob[_ -]?role\b", "job_role"),
                    (r"\bage\b", "age"),
                ]

                semantic = None
                for pattern, key in direct_rules:
                    if re.search(pattern, direct_norm):
                        if key == "phone" and direct_norm == "contact":
                            # External ATS forms frequently label a phone field
                            # simply as "Contact" while omitting tel/phone
                            # metadata. Treat the explicit field label as the
                            # authoritative semantic so the deterministic pass
                            # uses the grounded phone value instead of allowing
                            # generic reasoning to guess a name such as Anuroop.
                            pass
                        semantic = key
                        break

                if semantic is None:
                    for pattern, key in strong_rules:
                        if re.search(pattern, strong_norm):
                            semantic = key
                            break

                # Do not fall back to broad parent context for deterministic
                # classification. Unknown fields remain available to the
                # generic profile-reasoner / exact Custom-Q&A routing.
                # Open-ended narrative experience belongs to Custom Q&A /
                # ProfileReasoner, never the numeric professional-years fact.
                if semantic == "total_experience" and tag == "TEXTAREA":
                    semantic = None

                if semantic is None:
                    continue

                value = values.get(semantic)
                if value in (None, ""):
                    continue

                key = (getattr(frame, "url", ""), i, semantic)
                if key in seen:
                    continue
                seen.add(key)

                try:
                    current = (await el.input_value()).strip()
                except Exception:
                    current = ""

                def replaceable_default(existing: str, semantic_key: str) -> bool:
                    value_norm = normalize(existing).rstrip("/")
                    if not value_norm:
                        return True
                    url_skeletons = {
                        "linkedin": {
                            "https://www.linkedin.com/in",
                            "http://www.linkedin.com/in",
                            "https://linkedin.com/in",
                            "http://linkedin.com/in",
                        },
                        "github": {
                            "https://github.com",
                            "http://github.com",
                        },
                    }
                    if semantic_key in url_skeletons and value_norm in url_skeletons[semantic_key]:
                        return True
                    # Some forms incorrectly seed every social/link field with
                    # the LinkedIn base path. Treat that exact skeleton as a
                    # placeholder when the actual semantic field is GitHub.
                    if semantic_key == "github" and value_norm in {
                        "https://www.linkedin.com/in",
                        "http://www.linkedin.com/in",
                        "https://linkedin.com/in",
                        "http://linkedin.com/in",
                    }:
                        return True
                    return False

                if current and not replaceable_default(current, semantic):
                    continue
                if current:
                    # Clear only known browser/site seed values (for example
                    # a LinkedIn base URL prefilled into a social-link field).
                    # The normal fill_text helper otherwise treats any
                    # non-empty value as authoritative and refuses to replace it.
                    try:
                        await el.fill("")
                    except Exception:
                        pass

                field = {
                    "element": el,
                    "tag": tag,
                    "type": field_type,
                    "name": name,
                    "id": element_id,
                    "label": label,
                    "placeholder": placeholder,
                    "aria_label": aria,
                    "context": nearby,
                }

                ok = False
                try:
                    if tag == "select":
                        ok = await self.fill_select(field, semantic, value)
                    elif field_type == "combobox" or await el.get_attribute("role") == "combobox":
                        # Keep custom widgets conservative; the common widget
                        # filler handles the actual visible option selection.
                        ok = await self._fill_custom_combobox(el, value)
                    else:
                        ok = await self.fill_text(field, semantic, value)
                except Exception:
                    ok = False

                if ok:
                    filled += 1
                    await self.record(
                        "external_deterministic_field_filled",
                        semantic=semantic,
                        label=label,
                        value=str(value),
                    )

        for frame in list(page.frames):
            await process_frame(frame)

        if filled:
            await self.record(
                "external_deterministic_prefill_complete",
                fields_filled=filled,
            )
        return filled

    async def _fill_custom_combobox(self, element, value) -> bool:
        """Fill a generic visible combobox using the shared widget helper."""
        try:
            from .adaptive_form_runtime import AdaptiveWidgetFiller
            return await AdaptiveWidgetFiller().select_custom(element.page, element, value)
        except Exception:
            return False


    async def fill_contact_fields_deterministically(self, page: Page) -> int:
        """Fill core contact fields before any AI/LLM reasoning.

        This is a hard deterministic pass for identity/contact fields only.
        It deliberately does not use Custom Q&A or the LLM.  It scans the main
        document and child frames because external ATS forms can render the
        actual inputs inside an iframe.
        """
        profile_values = {
            "full_name": self.get_value("full_name"),
            "first_name": self.get_value("first_name"),
            "last_name": self.get_value("last_name"),
            "email": self.get_value("email"),
            "phone": self.get_value("phone"),
        }

        filled = 0
        seen = set()

        async def process_frame(frame):
            nonlocal filled
            try:
                locator = frame.locator(
                    "input:visible, textarea:visible"
                )
                count = await locator.count()
            except Exception:
                return

            for i in range(count):
                element = locator.nth(i)
                try:
                    field_type = normalize(
                        await element.get_attribute("type") or ""
                    )
                    name = normalize(
                        await element.get_attribute("name") or ""
                    )
                    element_id = normalize(
                        await element.get_attribute("id") or ""
                    )
                    placeholder = normalize(
                        await element.get_attribute("placeholder") or ""
                    )
                    aria = normalize(
                        await element.get_attribute("aria-label") or ""
                    )
                    label = await self.find_label(element)
                    label_n = normalize(label or "")
                except Exception:
                    continue

                signal = " ".join(
                    x for x in (
                        name, element_id, placeholder, aria, label_n
                    ) if x
                )
                explicit = " ".join(
                    x for x in (placeholder, aria, label_n)
                    if x
                ).strip()

                semantic = None

                # High-confidence contact detection.  Never let surrounding
                # website copy override the control's own placeholder/label.
                explicit_email_signal = bool(
                    re.search(r"\b(?:e[- ]?mail|email\s+id|email address)\b", explicit)
                    or re.search(r"(?:^|[\W_])email(?:[\W_]|$)", name)
                    or re.search(r"(?:^|[\W_])email(?:[\W_]|$)", element_id)
                )
                narrative_signal = bool(
                    re.search(
                        r"\b(?:message|tell\s+us|about\s+(?:yourself|you)|relevant\s+experience|experience|summary|motivation|cover\s+letter|introduction|why\s+(?:do|are|should)|additional\s+information)\b",
                        explicit,
                    )
                )

                if explicit_email_signal:
                    semantic = "email"
                elif field_type == "email" and narrative_signal:
                    # Broken ATS typing: this is a narrative field, not contact.
                    semantic = None
                elif re.fullmatch(r"(?:contact)\s*[*:：-]?", explicit):
                    # External ATS forms frequently label the applicant phone
                    # field simply as "Contact" and may omit tel/phone metadata.
                    # The explicit control label is authoritative here; use the
                    # grounded profile phone instead of falling through to a
                    # generic reasoner that could leak the candidate's name.
                    semantic = "phone"
                elif (
                    field_type == "tel"
                    or re.search(r"\b(?:phone|mobile(?:\s+(?:number|no))?|telephone|contact number|contact no)\b", explicit)
                    or re.search(r"(?:^|[\W_])(?:phone|mobile|tel)(?:[\W_]|$)", name)
                    or re.search(r"(?:^|[\W_])(?:phone|mobile|tel)(?:[\W_]|$)", element_id)
                ):
                    semantic = "phone"
                elif re.fullmatch(r"(?:name|full name|candidate name)", explicit):
                    semantic = "full_name"
                elif re.search(r"\bfirst name\b", explicit):
                    semantic = "first_name"
                elif re.search(r"\b(?:last|family) name\b|\bsurname\b", explicit):
                    semantic = "last_name"

                if not semantic:
                    continue

                value = profile_values.get(semantic)
                if value in (None, ""):
                    continue

                # Avoid touching the same locator twice when a form is
                # rendered through multiple Playwright frame handles.
                key = (id(frame), i)
                if key in seen:
                    continue
                seen.add(key)

                try:
                    current = (await element.input_value()).strip()
                except Exception:
                    current = ""
                if current:
                    continue

                field = {
                    "element": element,
                    "type": field_type,
                    "tag": "textarea" if "textarea" in await element.evaluate("e => e.tagName.toLowerCase()") else "input",
                    "name": name,
                    "id": element_id,
                    "label": label or "",
                }
                if await self.fill_text(field, semantic, value):
                    filled += 1

        frames = list(page.frames)
        for frame in frames:
            await process_frame(frame)

        if filled:
            await self.record(
                "deterministic_contact_prefill_complete",
                fields_filled=filled,
            )

        return filled

    async def fill_standard_fields(
        self,
        page: Page,
        fields: list[dict[str, Any]],
    ):

        for field in fields:

            semantic = self.classify(
                field
            )

            # Final defense-in-depth: never map a field to the profile email
            # unless the field itself explicitly asks for an email address.
            field_meta = normalize(
                " ".join(
                    str(field.get(k, "") or "")
                    for k in ("label", "placeholder", "aria_label", "name", "id")
                )
            )
            explicit_email_field = bool(
                re.search(r"\b(?:e[- ]?mail|email\s+id|email address)\b", field_meta)
                or re.search(r"(?:^|[\W_])email(?:[\W_]|$)", normalize(field.get("name", "")))
                or re.search(r"(?:^|[\W_])email(?:[\W_]|$)", normalize(field.get("id", "")))
            )
            if semantic == "email" and not explicit_email_field:
                semantic = "message" if normalize(field.get("tag", "")) == "textarea" or re.search(
                    r"\b(?:message|tell\s+us|about\s+(?:yourself|you)|relevant\s+experience|experience|summary|motivation|cover\s+letter|introduction|additional\s+information)\b",
                    field_meta,
                ) else "unknown"

            # Do not refill a field already populated by the AI form engine.
            try:
                existing_value = await field["element"].input_value()
            except Exception:
                existing_value = ""

            if existing_value and str(existing_value).strip():
                continue

            # Persistent dashboard Custom Q&A is for application questions,
            # not deterministic identity/contact fields.  Never let a saved
            # answer overwrite email, full name, phone, location, etc.
            field_type = normalize(field.get("type", ""))
            tag = normalize(field.get("tag", ""))
            qa_allowed = semantic in {
                "unknown", "message", "bio", "education", "experience_text",
            } or (tag == "textarea" and semantic not in {
                "terms", "checkbox", "submit", "resume", "file",
            })

            if qa_allowed:
                custom = self._custom_answer(field)
                if custom:
                    custom_value = custom.get("answer")
                    if custom_value not in (None, "") and field_type not in {"file", "submit", "checkbox"}:
                        if tag == "select":
                            if await self.fill_select(field, semantic, custom_value):
                                continue
                        elif tag in {"input", "textarea"}:
                            if field_type in {"", "text", "email", "tel", "search", "number"}:
                                if await self.fill_text(field, semantic, custom_value):
                                    continue

            # ------------------------------------------------
            # Fields that must NOT be guessed.
            # Notice period is intentionally NOT here.
            # expected_ctc is intentionally NOT here.
            # ------------------------------------------------

            if semantic in {
                "unknown",
                "honeypot",
                "radio",
                "gender",
                "salary",
                "work_authorization",
                "sponsorship",
                "relocation",
                "resume",
                "file",
                "terms",
                "checkbox",
                "submit",
            }:
                continue

            # ------------------------------------------------
            # SELECT FIELDS
            # ------------------------------------------------

            if field["tag"] == "select":

                # --------------------------------------------
                # DOB dropdowns
                # --------------------------------------------

                if semantic == "date":

                    dob = self.get_value(
                        "date"
                    )

                    # No verified DOB:
                    # leave the field untouched.
                    if not dob:
                        continue

                    dob_text = str(
                        dob
                    ).strip()

                    day = None
                    month = None
                    year = None

                    # YYYY-MM-DD
                    match = re.match(
                        r"^(\d{4})-(\d{1,2})-(\d{1,2})$",
                        dob_text,
                    )

                    if match:

                        year = match.group(1)
                        month = match.group(2)
                        day = match.group(3)

                    # DD/MM/YYYY
                    # DD-MM-YYYY
                    if not match:

                        match = re.match(
                            r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$",
                            dob_text,
                        )

                        if match:

                            day = match.group(1)
                            month = match.group(2)
                            year = match.group(3)

                    if not all(
                        [
                            day,
                            month,
                            year,
                        ]
                    ):
                        continue

                    field_text = normalize(
                        " ".join(
                            [
                                field["name"],
                                field["id"],
                                field["label"],
                                field["placeholder"],
                            ]
                        )
                    )

                    # Determine which DOB dropdown this is.
                    if "year" in field_text:

                        dob_value = year

                    elif "month" in field_text:

                        dob_value = month

                    elif "day" in field_text:

                        dob_value = day

                    else:

                        continue

                    await self.fill_select(
                        field,
                        "date",
                        dob_value,
                    )

                    continue

                # --------------------------------------------
                # Normal select fields
                # --------------------------------------------

                value = self.get_value(
                    semantic
                )

                if value is not None:

                    await self.fill_select(
                        field,
                        semantic,
                        value,
                    )

                continue

            # ------------------------------------------------
            # TEXT / AUTOCOMPLETE FIELDS
            # ------------------------------------------------

            if field["tag"] in {
                "input",
                "textarea",
            }:

                if field["type"] not in {
                    "",
                    "text",
                    "email",
                    "tel",
                    "search",
                    "number",
                }:
                    continue

                value = self.get_value(
                    semantic
                )

                if value is None:
                    continue

                # --------------------------------------------
                # Salary fields.
                # Fill only profile-backed factual values.
                # --------------------------------------------

                if semantic in {
                    "current_ctc",
                    "expected_ctc",
                }:

                    await self.fill_text(
                        field,
                        semantic,
                        self.get_value(semantic),
                    )

                    continue

                # --------------------------------------------
                # Current Location = Google autocomplete.
                # Type the requested location, then COMMIT the actual
                # suggestion. Never report success unless the value is
                # present after the selection.
                # --------------------------------------------

                if semantic == "current_location":

                    value = str(
                        value
                    ).strip()

                    if not value:
                        continue

                    element = field["element"]

                    try:
                        current = await element.input_value()

                        if not current.strip():
                            await element.fill(value)

                        await short_wait(
                            page,
                            1_000,
                        )

                        selected = False

                        # Prefer an actual visible autocomplete suggestion.
                        selectors = [
                            ".pac-container .pac-item",
                            ".pac-item",
                            "[role='option']",
                        ]

                        wanted = normalize(value)

                        for selector in selectors:

                            if selected:
                                break

                            suggestions = page.locator(
                                selector
                            )

                            try:
                                count = await suggestions.count()
                            except Exception:
                                count = 0

                            for i in range(count):

                                suggestion = suggestions.nth(i)

                                try:
                                    if not await suggestion.is_visible():
                                        continue

                                    text = clean_text(
                                        await suggestion.inner_text()
                                    )

                                    normalized_text = normalize(
                                        text
                                    )

                                    wanted_city = normalize(value)
                                    # Hyderabad is ambiguous. Never accept a
                                    # generic Hyderabad result: it must be
                                    # explicitly Telangana, India.
                                    verified_suggestion = (
                                        wanted_city == "hyderabad"
                                        and "telangana" in normalized_text
                                        and "india" in normalized_text
                                        and "pakistan" not in normalized_text
                                    ) or (
                                        wanted_city != "hyderabad"
                                        and wanted_city in normalized_text
                                        and "india" in normalized_text
                                        and "pakistan" not in normalized_text
                                    )

                                    if verified_suggestion:
                                        await suggestion.click(
                                            timeout=3_000
                                        )

                                        await short_wait(
                                            page,
                                            500,
                                        )

                                        actual = (
                                            await element.input_value()
                                        )

                                        actual_normalized = normalize(actual)

                                        if (
                                            actual.strip()
                                            and "india" in actual_normalized
                                            and "pakistan" not in actual_normalized
                                            and (
                                                wanted_city != "hyderabad"
                                                or "telangana" in actual_normalized
                                            )
                                        ):
                                            selected = True

                                            await self.record(
                                                "location_autocomplete_selected",
                                                requested=value,
                                                suggestion=text,
                                            )

                                            break

                                except Exception:
                                    continue

                        # Do NOT use ArrowDown/Enter fallback here.
                        # For ambiguous cities such as Hyderabad, the first
                        # suggestion can be Hyderabad City, Pakistan.
                        if not selected:
                            await self.record(
                                "location_autocomplete_not_committed",
                                requested=value,
                                reason="No verified Telangana/India suggestion; keyboard fallback disabled",
                            )

                        # Final verification: only count the field as filled
                        # when the input actually contains a value.
                        actual = ""

                        try:
                            actual = (
                                await element.input_value()
                            )
                        except Exception:
                            pass

                        actual_normalized = normalize(actual)
                        location_is_verified = (
                            actual.strip()
                            and "india" in actual_normalized
                            and "pakistan" not in actual_normalized
                            and (
                                normalize(value) != "hyderabad"
                                or "telangana" in actual_normalized
                            )
                        )

                        if selected and location_is_verified:

                            self.fields_filled += 1

                            await self.record(
                                "field_filled",
                                semantic=semantic,
                                label=field["label"],
                                name=field["name"],
                                id=field["id"],
                                value=actual,
                            )
                        else:
                            await self.record(
                                "location_autocomplete_not_committed",
                                requested=value,
                            )

                    except Exception as exc:

                        await self.record(
                            "location_autocomplete_error",
                            semantic=semantic,
                            label=field["label"],
                            error=str(exc),
                        )

                    continue

                # --------------------------------------------
                # Normal text field
                # --------------------------------------------

                await self.fill_text(
                    field,
                    semantic,
                    value,
                )

    # ========================================================
    # RESUME UPLOAD
    # ========================================================

    def _prepare_external_resume_upload_copy(self, resume_path: str) -> str:
        """Create a job-specific external upload file without mutating the source PDF."""
        source = Path(resume_path).resolve()
        if not source.exists():
            raise FileNotFoundError(str(source))

        # Tailored PDFs are stored under bounded .../resume_versions/<platform>/<short-company-hash>/<short-role-hash>/j-<id>/resume.pdf paths.
        # Use that job directory as the strongest identity signal.
        job_token = "job"
        for parent in (source.parent, *source.parents):
            if parent.name.lower().startswith("job-"):
                job_token = re.sub(r"[^A-Za-z0-9_-]", "", parent.name)
                break

        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:10]
        upload_dir = PROJECT_ROOT / "webapp" / "runtime" / "external_resume_uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_name = f"Anuroop_Kudire_{digest}_{job_token}_tailored_resume{source.suffix.lower()}"
        target = upload_dir / upload_name
        if source.resolve() != target.resolve():
            if (not target.exists()) or target.stat().st_size != source.stat().st_size:
                shutil.copy2(source, target)
        self.external_resume_upload_path = str(target)
        return str(target)

    async def _verify_resume_file_input(self, locator, expected_name: str) -> bool:
        try:
            names = await locator.evaluate(
                "el => el.files ? Array.from(el.files).map(f => f.name) : []"
            )
            normalized = [str(x).strip().lower() for x in (names or [])]
            return expected_name.lower() in normalized
        except Exception:
            return False

    async def _select_visible_resume_option_by_name(self, frame, expected_name: str) -> bool:
        expected = Path(expected_name).name.strip().lower()
        if not expected:
            return False
        for selector in ("[role='radio'][aria-label]", "[role='radio']", "input[type='radio']", "label", "[aria-label]"):
            try:
                loc = frame.locator(selector)
                count = min(await loc.count(), 160)
            except Exception:
                continue
            for i in range(count):
                el = loc.nth(i)
                try:
                    if not await el.is_visible(timeout=300):
                        continue
                except Exception:
                    continue
                vals=[]
                for attr in ("aria-label","title","data-testid"):
                    try: v=await el.get_attribute(attr)
                    except Exception: v=None
                    if v: vals.append(v)
                try: vals.append(await el.inner_text())
                except Exception: pass
                text=re.sub(r"\s+"," "," ".join(vals)).strip().lower()
                if expected not in text:
                    continue
                try: await el.scroll_into_view_if_needed()
                except Exception: pass
                try: await el.click(timeout=3000, force=True)
                except Exception: continue
                try:
                    if await el.get_attribute("aria-checked") == "true": return True
                except Exception: pass
                try:
                    if (await el.get_attribute("type") or "").lower() == "radio" and await el.is_checked(): return True
                except Exception: pass
                return True
        return False

    async def _visible_upload_controls(self, frame):
        patterns = (
            re.compile(r"^upload\s*resume$", re.I),
            re.compile(r"upload\s+(?:a\s+)?(?:different\s+)?(?:resume|cv|file|document)", re.I),
            re.compile(r"(?:choose|select|browse|attach)\s+(?:a\s+)?(?:file|resume|cv|document)", re.I),
            re.compile(r"upload\s+(?:from\s+device|from\s+computer)", re.I),
        )
        selectors = (
            "button", "a", "label", "[role='button']", "[role='link']",
            "[role='menuitem']", "[aria-label]", "[title]",
        )
        for selector in selectors:
            try:
                loc = frame.locator(selector)
                count = min(await loc.count(), 120)
            except Exception:
                continue
            for i in range(count):
                el = loc.nth(i)
                try:
                    if not await el.is_visible(timeout=500) or await el.is_disabled():
                        continue
                except Exception:
                    continue
                values = []
                for attr in ("aria-label", "title", "value", "data-testid", "data-test"):
                    try:
                        v = await el.get_attribute(attr)
                    except Exception:
                        v = None
                    if v:
                        values.append(v)
                try:
                    values.append(await el.inner_text())
                except Exception:
                    pass
                text = re.sub(r"\s+", " ", " ".join(values)).strip()
                if any(p.search(text) for p in patterns):
                    yield el, text

    async def upload_resume(
        self,
        page: Page,
        fields: list[dict[str, Any]],
    ) -> bool:

        if self.resume_uploaded:
            return True

        resume_path = self.get_resume_path()
        if not resume_path:
            await self.record("resume_not_found")
            return False

        try:
            upload_path = self._prepare_external_resume_upload_copy(resume_path)
        except Exception as exc:
            await self.record("resume_upload_copy_error", error=str(exc), source=resume_path)
            return False

        expected_name = Path(upload_path).name
        await self.record(
            "resume_upload_target",
            source=resume_path,
            upload_file=expected_name,
        )

        frames = [page] + list(page.frames)

        for frame in frames:
            try:
                if await self._select_visible_resume_option_by_name(frame, expected_name):
                    body = re.sub(r"\s+", " ", await frame.locator("body").inner_text(timeout=1000)).lower()
                    if expected_name.lower() in body:
                        self.resume_uploaded = True
                        await self.record("resume_selected_by_name", path=upload_path, selected=expected_name)
                        return True
            except Exception:
                pass

        # 1) Direct file inputs. This is the preferred route and works even when
        # the input itself is visually hidden. Always verify the actual FileList.
        for frame in frames:
            try:
                inputs = frame.locator("input[type='file']")
                count = min(await inputs.count(), 40)
            except Exception:
                continue
            for i in range(count):
                el = inputs.nth(i)
                try:
                    if await el.is_disabled():
                        continue
                except Exception:
                    pass
                try:
                    await el.set_input_files(upload_path)
                    if await self._verify_resume_file_input(el, expected_name):
                        selected_named = False
                        try:
                            selected_named = await self._select_visible_resume_option_by_name(frame, expected_name)
                        except Exception:
                            pass
                        self.resume_uploaded = True
                        self.fields_filled += 1
                        await self.record(
                            "resume_uploaded",
                            path=upload_path,
                            files=[expected_name],
                            selected_by_name=selected_named,
                            strategy="direct_file_input",
                        )
                        return True
                except Exception as exc:
                    await self.record("resume_upload_error", strategy="direct_file_input", error=str(exc))

        # 2) Many ATSs render only an Upload/Choose button and create the file
        # input after it is clicked. Capture the browser file chooser explicitly.
        for frame in frames:
            async for control, label in self._visible_upload_controls(frame):
                try:
                    await self.record("resume_upload_control_found", label=label[:160])
                    try:
                        async with page.expect_file_chooser(timeout=UPLOAD_CONTROL_TIMEOUT) as fc_info:
                            await control.click(timeout=UPLOAD_CONTROL_TIMEOUT)
                        chooser = await fc_info.value
                        await chooser.set_files(upload_path)
                    except Exception:
                        # Some widgets create the input only after the click;
                        # rescan before declaring the upload failed.
                        try:
                            await control.click(timeout=UPLOAD_CONTROL_TIMEOUT, force=True)
                        except Exception:
                            pass
                        await short_wait(page, 300)
                        inputs = frame.locator("input[type='file']")
                        count = min(await inputs.count(), 20)
                        selected = False
                        for i in range(count):
                            el = inputs.nth(i)
                            try:
                                await el.set_input_files(upload_path)
                                if await self._verify_resume_file_input(el, expected_name):
                                    selected = True
                                    break
                            except Exception:
                                continue
                        if not selected:
                            continue

                    # Verify the exact selected filename in the file input if one
                    # exists, otherwise require the target filename/success text to
                    # appear in the rendered upload surface.
                    verified = False
                    for check_frame in [page] + list(page.frames):
                        try:
                            inputs = check_frame.locator("input[type='file']")
                            for i in range(min(await inputs.count(), 30)):
                                if await self._verify_resume_file_input(inputs.nth(i), expected_name):
                                    verified = True
                                    break
                        except Exception:
                            pass
                        if verified:
                            break
                    if not verified:
                        try:
                            body = await page.locator("body").inner_text(timeout=1500)
                            body_norm = re.sub(r"\s+", " ", body).lower()
                            verified = (
                                expected_name.lower() in body_norm
                                or "uploaded successfully" in body_norm
                                or "resume uploaded" in body_norm
                                or "file uploaded" in body_norm
                            )
                        except Exception:
                            verified = False

                    if verified:
                        selected_named = False
                        for select_frame in [page] + list(page.frames):
                            try:
                                if await self._select_visible_resume_option_by_name(select_frame, expected_name):
                                    selected_named = True
                                    break
                            except Exception:
                                pass
                        self.resume_uploaded = True
                        self.fields_filled += 1
                        await self.record(
                            "resume_uploaded",
                            path=upload_path,
                            files=[expected_name],
                            selected_by_name=selected_named,
                            strategy="file_chooser_or_upload_control",
                        )
                        return True

                    await self.record("resume_upload_verification_failed", expected=expected_name)
                except Exception as exc:
                    await self.record("resume_upload_error", strategy="upload_control", error=str(exc))

        await self.record(
            "resume_field_not_found",
            expected_filename=expected_name,
        )
        return False

    # ========================================================
    # TERMS
    # ========================================================

    async def accept_terms(
        self,
        page: Page,
    ) -> bool:

        self.terms_accepted = False

        try:

            direct = page.locator(
                "#termscondition"
            )

            if await direct.count():

                await self.record(
                    "terms_direct_found"
                )

                try:

                    if not await direct.is_checked():

                        await direct.check(
                            force=True
                        )

                    if await direct.is_checked():

                        self.terms_accepted = True

                        await self.record(
                            "terms_privacy_accepted",
                            name="termscondition",
                            id="termscondition",
                        )

                        return True

                except Exception as exc:

                    await self.record(
                        "terms_direct_error",
                        error=str(exc),
                    )

        except Exception as exc:

            await self.record(
                "terms_direct_lookup_error",
                error=str(exc),
            )

        try:

            checkboxes = page.locator(
                "input[type='checkbox']"
            )

            count = await checkboxes.count()

            await self.record(
                "terms_checkbox_scan",
                count=count,
            )

        except Exception as exc:

            await self.record(
                "terms_checkbox_scan_error",
                error=str(exc),
            )

            return False

        for i in range(count):

            checkbox = checkboxes.nth(i)

            try:

                context = await checkbox.evaluate(
                    """
                    el => {
                        const parts = [];

                        if (el.getAttribute('aria-label')) {
                            parts.push(
                                el.getAttribute('aria-label')
                            );
                        }

                        if (el.id) {
                            const label =
                                document.querySelector(
                                    `label[for="${CSS.escape(el.id)}"]`
                                );

                            if (label) {
                                parts.push(
                                    label.innerText ||
                                    label.textContent ||
                                    ''
                                );
                            }
                        }

                        const closest =
                            el.closest('label');

                        if (closest) {
                            parts.push(
                                closest.innerText ||
                                closest.textContent ||
                                ''
                            );
                        }

                        if (el.parentElement) {
                            parts.push(
                                el.parentElement.innerText ||
                                el.parentElement.textContent ||
                                ''
                            );
                        }

                        return parts
                            .join(' ')
                            .replace(/\\s+/g, ' ')
                            .trim();
                    }
                    """
                )

            except Exception as exc:

                await self.record(
                    "terms_context_error",
                    index=i,
                    error=str(exc),
                )

                continue

            normalized = normalize(
                context
            )

            if not any(
                phrase in normalized
                for phrase in [
                    "terms",
                    "terms of use",
                    "terms and conditions",
                    "privacy",
                    "privacy policy",
                    "accept",
                    "agree",
                ]
            ):
                continue

            await self.record(
                "terms_checkbox_candidate",
                index=i,
                context=context[:300],
            )

            try:

                if not await checkbox.is_checked():

                    await checkbox.check(
                        force=True
                    )

                if await checkbox.is_checked():

                    self.terms_accepted = True

                    await self.record(
                        "terms_privacy_accepted",
                        index=i,
                        context=context[:300],
                    )

                    return True

            except Exception as exc:

                await self.record(
                    "terms_checkbox_error",
                    index=i,
                    error=str(exc),
                )

                try:

                    await checkbox.click(
                        force=True
                    )

                    if await checkbox.is_checked():

                        self.terms_accepted = True

                        await self.record(
                            "terms_privacy_accepted_click_fallback",
                            index=i,
                        )

                        return True

                except Exception as click_exc:

                    await self.record(
                        "terms_checkbox_click_error",
                        index=i,
                        error=str(click_exc),
                    )

                # Some ATSs render the real checkbox as a hidden input and
                # expose the clickable control through aria-labelledby.  Use
                # the visible labelled control instead of forcing the hidden
                # input itself.
                try:
                    labelledby = await checkbox.get_attribute("aria-labelledby") or ""
                    for label_id in [x.strip() for x in labelledby.split() if x.strip()]:
                        label_node = page.locator(f"#{label_id}").first
                        if not await label_node.count():
                            continue
                        try:
                            await label_node.click()
                        except Exception:
                            await label_node.click(force=True)
                        if await checkbox.is_checked():
                            self.terms_accepted = True
                            await self.record(
                                "terms_privacy_accepted_aria_label",
                                index=i,
                                label_id=label_id,
                            )
                            return True
                except Exception as aria_exc:
                    await self.record(
                        "terms_aria_label_fallback_error",
                        index=i,
                        error=str(aria_exc),
                    )

        await self.record(
            "terms_privacy_not_found_or_not_accepted"
        )

        return False

    # ========================================================
    # REQUIRED FIELD CHECK
    # ========================================================

    async def verify_required_fields(
        self,
        page: Page,
        fields: list[dict[str, Any]],
    ) -> bool:

        self.unresolved_questions = []

        radio_groups = {}

        for field in fields:

            if field["type"] != "radio":
                continue

            name = (
                field["name"]
                or f"radio_{field['index']}"
            )

            radio_groups.setdefault(
                name,
                [],
            ).append(field)

        for name, group in radio_groups.items():

            required = any(
                field["required"]
                for field in group
            )

            if not required:
                continue

            if not any(
                field["checked"]
                for field in group
            ):

                self.unresolved_questions.append(
                    {
                        "type": "radio",
                        "name": name,
                        "labels": [
                            field["label"]
                            for field in group
                        ],
                        "reason": (
                            "Required radio group "
                            "has no verified answer"
                        ),
                    }
                )

        for field in fields:

            if not field["required"]:
                continue

            semantic = self.classify(
                field
            )

            if field["type"] == "radio":
                continue

            if semantic in {"honeypot"}:
                continue

            if semantic == "terms":

                if not self.terms_accepted:

                    self.unresolved_questions.append(
                        {
                            "type": "terms",
                            "name": field["name"],
                            "id": field["id"],
                            "label": field["label"],
                            "reason": (
                                "Terms/privacy "
                                "not accepted"
                            ),
                        }
                    )

                continue

            if field["type"] == "checkbox":

                if not field["checked"]:

                    self.unresolved_questions.append(
                        {
                            "type": "checkbox",
                            "name": field["name"],
                            "id": field["id"],
                            "label": field["label"],
                            "reason": (
                                "Required checkbox "
                                "not checked"
                            ),
                        }
                    )

                continue

            if field["tag"] == "select":

                try:

                    value = await field[
                        "element"
                    ].input_value()

                except Exception:

                    value = ""

                if not str(value).strip():

                    self.unresolved_questions.append(
                        {
                            "type": "select",
                            "semantic": semantic,
                            "name": field["name"],
                            "id": field["id"],
                            "label": field["label"],
                            "reason": (
                                "Required select "
                                "has no value"
                            ),
                        }
                    )

                continue

            try:

                value = await field[
                    "element"
                ].input_value()

            except Exception:

                value = ""

            # A required question is resolved if the browser control is
            # actually populated, even when the semantic classifier cannot
            # assign a deterministic profile key.  This is what lets a saved
            # Custom Q&A answer satisfy an otherwise unknown textarea.
            if str(value).strip():
                continue

            self.unresolved_questions.append(
                {
                    "type": "input",
                    "semantic": semantic,
                    "name": field["name"],
                    "id": field["id"],
                    "label": field["label"],
                    "reason": (
                        "Required field "
                        "is empty"
                    ),
                }
            )

        if self.unresolved_questions:

            await self.record(
                "required_fields_unresolved",
                count=len(
                    self.unresolved_questions
                ),
                fields=self.unresolved_questions,
            )

            return False

        await self.record(
            "required_fields_verified"
        )

        return True

    # ========================================================
    # VALIDATION ERRORS
    # ========================================================

    async def validation_errors(
        self,
        page: Page,
    ) -> list[str]:

        selectors = [
            "[role='alert']",
            ".error",
            ".errors",
            ".field-error",
            ".invalid-feedback",
            ".error-message",
            "[aria-invalid='true']",
        ]

        errors = []

        for selector in selectors:

            locator = page.locator(
                selector
            )

            try:

                count = await locator.count()

            except Exception:

                continue

            for i in range(count):

                try:

                    text = clean_text(
                        await locator.nth(i).inner_text()
                    )

                    if (
                        text
                        and text not in errors
                    ):
                        errors.append(text)

                except Exception:
                    continue

        if errors:

            await self.record(
                "validation_errors_found",
                errors=errors[:20],
            )

        return errors

    # ========================================================
    # NEXT / CONTINUE
    # ========================================================

    async def find_next_button(
        self,
        page: Page,
    ):

        wanted = {
            "next",
            "continue",
            "save & continue",
            "save and continue",
            "proceed",
        }

        locator = page.locator(
            "button, input[type='button'], [role='button']"
        )

        try:

            count = await locator.count()

        except Exception:

            return None

        for i in range(count):

            element = locator.nth(i)

            try:

                if not await element.is_visible():
                    continue

                text = clean_text(
                    await element.inner_text()
                )

            except Exception:

                continue

            if normalize(text) in wanted:
                return element

        return None

    async def handle_next_steps(
        self,
        page: Page,
    ):

        for step_number in range(10):

            button = await self.find_next_button(
                page
            )

            if not button:
                return

            try:

                text = clean_text(
                    await button.inner_text()
                )

            except Exception:

                text = "Next"

            await self.record(
                "next_button_found",
                text=text,
                step=step_number + 1,
            )

            try:

                await button.click(
                    timeout=5_000
                )

            except Exception as exc:

                await self.record(
                    "next_button_error",
                    error=str(exc),
                )

                return

            await short_wait(
                page,
                1_000,
            )

            await self.wait_for_page(
                page
            )

            # A Next/Continue click can land on a dynamically rendered SPA step.
            # Wait for the new application form state before scanning it so the
            # agent does not inspect a half-rendered page and then sit idle.
            await self.wait_for_application_form(
                page,
                allow_minimal_form=True,
            )

            fields = await self.inspect_form(
                page
            )

            # Re-run the same layered form pipeline used on the initial page.
            # In particular, unknown/employer questions must go back through the
            # adaptive AI form engine on every newly rendered step; deterministic
            # contact/profile passes alone are insufficient for multi-page ATS forms.
            await self.fill_external_profile_fields_deterministically(
                page
            )
            await self.fill_contact_fields_deterministically(
                page
            )
            await self.run_ai_form_engine(
                page
            )

            fields = await self.inspect_form(
                page
            )

            await self.fill_standard_fields(
                page,
                fields,
            )

            await self.fill_ust_specific_fields(page, fields)

            fields = await self.inspect_form(
                page
            )

            await self.upload_resume(
                page,
                fields,
            )

            await self.accept_terms(
                page
            )


    # ========================================================
    # UST / RIPPLEHIRE REQUIRED FIELD HANDLING
    # ========================================================

    async def fill_ust_specific_fields(self, page: Page, fields):
        """Handle the known UST RippleHire fields without guessing DOB."""
        filled = 0

        def label_for(f):
            return normalize(
                " ".join(
                    str(f.get(k, "") or "")
                    for k in ("label", "name", "id", "context")
                )
            )

        async def select_field(field, wanted, semantic):
            nonlocal filled
            try:
                el = field["element"]
                if not await el.is_visible():
                    return False
                current = (await el.input_value()).strip()
                if current:
                    return True

                options = await self.get_options(el)
                wn = normalize(str(wanted))
                chosen = next(
                    (o for o in options if normalize(o["text"]) == wn),
                    None,
                )
                if chosen is None:
                    chosen = next(
                        (o for o in options if wn in normalize(o["text"])),
                        None,
                    )
                if chosen is None:
                    await self.record(
                        "specific_select_option_not_found",
                        semantic=semantic,
                        requested=wanted,
                    )
                    return False

                ok = await self.fill_select(field, semantic, chosen["text"])
                if ok:
                    filled += 1
                return ok
            except Exception as exc:
                await self.record(
                    "specific_select_error",
                    semantic=semantic,
                    error=str(exc),
                )
                return False

        # Notice period -> Can join immediately.
        notice_days = self.profile_get("notice_period_days", default=None)
        immediate = self.profile_get(
            "available_to_join_immediately",
            "available_to_join",
            default=False,
        )
        if notice_days in (0, "0") or immediate is True:
            for f in fields:
                text = label_for(f)
                if "noticeperiod" in text or (
                    "notice" in text and "period" in text
                ):
                    if f.get("type") == "select":
                        await select_field(
                            f,
                            "Can join immediately",
                            "notice_period",
                        )
                        break

        # Gender -> Male when the form exposes a gender select.
        gender = self.profile_get("gender", default=None)
        if gender:
            for f in fields:
                text = label_for(f)
                if "gender" in text and f.get("type") == "select":
                    await select_field(f, gender, "gender")
                    break

        # Current Company is required. Do not invent an employer.
        # "Fresher" is the truthful value for a user with no current employer.
        for f in fields:
            text = label_for(f)
            if (
                f.get("type") == "text"
                and "currentcompany" in text
            ):
                try:
                    current = (await f["element"].input_value()).strip()
                except Exception:
                    current = ""
                if not current:
                    if await self.fill_text(
                        f,
                        "current_company",
                        "Fresher",
                    ):
                        filled += 1
                break

        # UST previous employment -> No.
        for f in fields:
            text = label_for(f)
            if (
                f.get("type") == "radio"
                and (
                    "pastemployment" in text
                    or "employmentwithust" in text
                    or "ust" in text
                )
            ):
                # Radio fields may share a group; inspect nearby text/value.
                group_name = f.get("name")
                radios = page.locator(
                    f"input[type='radio'][name='{group_name}']"
                ) if group_name else page.locator(
                    "input[type='radio']"
                )
                for i in range(await radios.count()):
                    r = radios.nth(i)
                    bits = []
                    for attr in ("value", "aria-label", "title"):
                        v = await r.get_attribute(attr)
                        if v:
                            bits.append(v)
                    try:
                        bits.append(await r.locator("xpath=..").inner_text())
                    except Exception:
                        pass
                    if normalize(" ".join(bits)) == "no":
                        try:
                            await r.check(force=True)
                        except Exception:
                            await r.click(force=True)
                        if await r.is_checked():
                            filled += 1
                            await self.record(
                                "specific_radio_filled",
                                semantic="ust_previous_employment",
                                value="No",
                            )
                        break
                break

        return filled

    async def verify_ust_required_fields(self, page, fields):
        """Strictly block READY_TO_SUBMIT when known required controls are empty."""
        missing = []

        for f in fields:
            if not f.get("required"):
                continue

            try:
                el = f["element"]
                if not await el.is_visible():
                    continue

                typ = f.get("type", "")
                if typ in {"file", "hidden", "button", "submit"}:
                    continue

                if typ == "radio":
                    continue

                value = (await el.input_value()).strip()
                label = normalize(
                    " ".join(
                        str(f.get(k, "") or "")
                        for k in ("label", "name", "id")
                    )
                )

                if typ == "select":
                    if (
                        not value
                        or normalize(value) in {
                            "select", "select...", "day", "month", "year"
                        }
                    ):
                        missing.append(label or f"field_{f.get('index')}")
                elif not value:
                    missing.append(label or f"field_{f.get('index')}")
            except Exception:
                continue

        # Required radio groups.
        groups = {}
        for f in fields:
            if f.get("required") and f.get("type") == "radio":
                groups.setdefault(f.get("name") or "radio", []).append(f)

        for name, group in groups.items():
            if not any(bool(f.get("checked")) for f in group):
                missing.append(name)

        # Explicitly require DOB only when the form marks its DOB controls required.
        if missing:
            self.unresolved_questions = [
                {"field": x, "reason": "required field is empty"}
                for x in missing
            ]
            await self.record(
                "required_fields_missing",
                fields=missing,
            )
            return False

        await self.record("strict_required_fields_verified")
        return True


    # ========================================================
    # FINAL SUBMIT
    # ========================================================

    async def find_submit(
        self,
        page: Page,
    ):

        wanted = {
            "submit",
            "submit application",
            "send application",
            "finish",
            "complete application",
        }

        locator = page.locator(
            "button, input[type='submit'], [role='button']"
        )

        try:

            count = await locator.count()

        except Exception:

            return None

        for i in range(count):

            element = locator.nth(i)

            try:

                if not await element.is_visible():
                    continue

                text = clean_text(
                    await element.inner_text()
                )

            except Exception:

                text = ""

            if not text:

                try:

                    text = (
                        await element.get_attribute(
                            "value"
                        )
                        or ""
                    )

                except Exception:

                    text = ""

            if normalize(text) in wanted:
                return element

        return None

    # ========================================================
    # SUBMIT
    # ========================================================

    async def submit(
        self,
        page: Page,
    ) -> dict[str, Any]:

        if not self.terms_accepted:

            await self.record(
                "submission_blocked",
                reason=(
                    "Terms/privacy checkbox "
                    "was not accepted"
                ),
            )

            return {
                "status": "QUESTION_UNRESOLVED",
                "reason": (
                    "Terms/privacy checkbox "
                    "not accepted"
                ),
            }

        fields = await self.inspect_form(
            page
        )

        required_ok = (
            await self.verify_required_fields(
                page,
                fields,
            )
        )

        # UST/RippleHire exposes additional required selects/radios.
        if await page.locator(
            "select, input[type='radio']"
        ).count() and (
            await page.locator("#noticePeriodSelect").count()
            or await page.get_by_text("Notice period", exact=False).count()
        ):
            required_ok = await self.verify_ust_required_fields(
                page,
                fields,
            )

        if not required_ok:

            return {
                "status": "QUESTION_UNRESOLVED",
                "reason": (
                    "Required fields unresolved"
                ),
                "unresolved_questions": (
                    self.unresolved_questions
                ),
            }

        errors = await self.validation_errors(
            page
        )

        if errors:

            return {
                "status": "FORM_ERROR",
                "errors": errors,
            }

        button = await self.find_submit(
            page
        )

        if not button:

            await self.record(
                "final_submit_not_found"
            )

            return {
                "status": "FORM_ERROR",
                "reason": (
                    "Final submit button "
                    "not found"
                ),
            }

        await self.record(
            "final_submit_button_found"
        )

        if not self.terms_accepted:

            await self.record(
                "submission_blocked",
                reason=(
                    "Terms not verified "
                    "immediately before submit"
                ),
            )

            return {
                "status": "QUESTION_UNRESOLVED",
                "reason": (
                    "Terms not verified"
                ),
            }

        if self.dry_run:

            print()
            print(
                "DRY_RUN=True"
            )
            print(
                "Final submission BLOCKED."
            )

            return {
                "status": "READY_TO_SUBMIT",
            }

        try:

            await button.click(
                timeout=10_000
            )

            await short_wait(
                page,
                2_000,
            )

            await self.wait_for_page(
                page
            )

            return await self.verify_submission(
                page
            )

        except Exception as exc:

            await self.record(
                "submission_error",
                error=str(exc),
            )

            return {
                "status": "FAILED",
                "reason": str(exc),
            }

    # ========================================================
    # SUBMISSION VERIFICATION
    # ========================================================

    async def verify_submission(
        self,
        page: Page,
    ) -> dict[str, Any]:

        try:

            body = normalize(
                await page.locator(
                    "body"
                ).inner_text(
                    timeout=5_000
                )
            )

        except Exception:

            body = ""

        success_phrases = [
            "application submitted",
            "application has been submitted",
            "successfully applied",
            "thank you for applying",
            "thank you for your application",
            "application received",
            "your application was submitted",
        ]

        for phrase in success_phrases:

            if phrase in body:

                await self.record(
                    "application_submitted",
                    confirmation=phrase,
                )

                return {
                    "status": "APPLIED",
                    "confirmation": phrase,
                }

        blocker = await self.detect_blocker(
            page
        )

        if blocker == "ALREADY_APPLIED":

            return {
                "status": "ALREADY_APPLIED",
            }

        errors = await self.validation_errors(
            page
        )

        if errors:

            return {
                "status": "FORM_ERROR",
                "errors": errors,
            }

        return {
            "status": "FAILED",
            "reason": (
                "Submission clicked but "
                "confirmation was not verified"
            ),
        }

    # ========================================================
    # MAIN APPLY FLOW
    # ========================================================

    async def apply(
        self,
        page: Page,
        url: str,
        application_opened: bool = False,
    ) -> dict[str, Any]:

        self.step = 0

        self.history = []

        self.fields_filled = 0

        self.resume_uploaded = False

        self.terms_accepted = False

        self.unresolved_questions = []
        self._active_page = None
        self.external_resume_upload_path = None

        self.load_profile()

        await self.record(
            "opening_job_url",
            url=url,
        )

        application_opened = bool(application_opened or await self._looks_like_application_url(url))

        # Some company job-detail pages contain URL segments such as
        # /ApplicationMethods while still showing the job-page Apply CTA.
        # In that state we must click Apply instead of treating the page as
        # an already-open application form.
        if application_opened:
            try:
                if await self._has_explicit_apply_cta(page):
                    await self.record("application_url_still_has_apply_cta")
                    application_opened = False
            except Exception:
                pass

        if not application_opened:
            try:

                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=NAVIGATION_TIMEOUT,
                )

            except Exception as exc:

                await self.record(
                    "navigation_error",
                    error=str(exc),
                )

                return {
                    "status": "FAILED",
                    "reason": str(exc),
                    "history": self.history,
                }
        else:
            await self.record("using_existing_application_page", url=page.url)

        await self.wait_for_page(
            page
        )

        blocker = await self.detect_blocker(
            page
        )

        if blocker:

            return {
                "status": blocker,
                "history": self.history,
            }

        clicked = application_opened or await self.click_apply(page)

        if getattr(self, "_active_page", None) is not None and self._active_page is not page:
            page = self._active_page
            await self.record("switched_to_application_page", url=page.url)

        if not clicked:

            return {
                "status": "APPLY_BUTTON_NOT_FOUND",
                "url": page.url,
                "history": self.history,
            }

        self.step = 1

        await self.wait_for_page(
            page
        )

        await self.handle_cookie_consent(
            page
        )

        # Once the engine has successfully clicked the verified Apply CTA,
        # treat this page as an application handoff even when the ATS keeps
        # the same URL and exposes only the first step initially.
        ready = await self.wait_for_application_form(
            page,
            allow_minimal_form=True,
        )

        if not ready:

            return {
                "status": "FORM_NOT_READY",
                "url": page.url,
                "history": self.history,
            }

        print()
        print("=" * 70)
        print("FORM DETECTION")
        print("=" * 70)

        fields = await self.inspect_form(
            page
        )

        # Hard deterministic external-profile pass comes first. Known profile
        # facts must be filled before the generic AI/Custom-Q&A route.
        await self.fill_external_profile_fields_deterministically(
            page
        )

        fields = await self.inspect_form(
            page
        )

        # Hard deterministic contact pass comes next. These fields must never
        # depend on LLM reasoning or Custom Q&A.
        await self.fill_contact_fields_deterministically(
            page
        )

        fields = await self.inspect_form(
            page
        )

        await self.run_ai_form_engine(
            page
        )

        fields = await self.inspect_form(
            page
        )

        await self.fill_standard_fields(
            page,
            fields,
        )

        await self.fill_ust_specific_fields(page, fields)

        fields = await self.inspect_form(
            page
        )

        await self.upload_resume(
            page,
            fields,
        )

        await self.accept_terms(
            page
        )

        if not self.terms_accepted:

            await short_wait(
                page,
                1_500,
            )

            await self.accept_terms(
                page
            )

        await self.handle_next_steps(
            page
        )

        fields = await self.inspect_form(
            page
        )

        if not self.resume_uploaded:

            await self.upload_resume(
                page,
                fields,
            )

        if not self.terms_accepted:

            await self.accept_terms(
                page
            )

        fields = await self.inspect_form(
            page
        )

        required_ok = (
            await self.verify_required_fields(
                page,
                fields,
            )
        )

        if not required_ok:

            return {
                "status": "QUESTION_UNRESOLVED",
                "url": page.url,
                "fields_filled": (
                    self.fields_filled
                ),
                "resume_uploaded": (
                    self.resume_uploaded
                ),
                "terms_accepted": (
                    self.terms_accepted
                ),
                "unresolved_questions": (
                    self.unresolved_questions
                ),
                "history": self.history,
            }

        result = await self.submit(
            page
        )

        result.update(
            {
                "url": page.url,
                "fields_filled": (
                    self.fields_filled
                ),
                "resume_uploaded": (
                    self.resume_uploaded
                ),
                "terms_accepted": (
                    self.terms_accepted
                ),
                "unresolved_questions": (
                    self.unresolved_questions
                ),
                "history": self.history,
            }
        )

        return result

    # ========================================================
    # AI FORM ENGINE
    # ========================================================

    async def run_ai_form_engine(
        self,
        page: Page,
    ):

        try:

            engine = AIFormEngine(
                page=page,
                profile=self.profile,
                enable_resume_upload=False,
            )

            result = await engine.fill_form_safely()

            if not isinstance(
                result,
                dict,
            ):
                result = {}

            # AIFormEngine returns fields_filled as an integer.
            filled = result.get(
                "fields_filled",
                0,
            )

            try:
                filled_count = int(filled or 0)
            except (TypeError, ValueError):
                filled_count = 0

            resume_uploaded = bool(
                result.get(
                    "resume_uploaded",
                    False,
                )
            )

            if resume_uploaded:
                self.resume_uploaded = True

            await self.record(
                "ai_form_engine_complete",
                fields_filled=filled_count,
                resume_uploaded=resume_uploaded,
            )

            return result

        except Exception as exc:

            await self.record(
                "ai_form_engine_error",
                error=str(exc),
            )

            return {}


# ============================================================
# PLAYWRIGHT LOCATOR HELPER
# ============================================================

def page_locator(
    element,
    selector: str,
):
    return element.locator(
        selector
    )


# ============================================================
# CHROME CDP
# ============================================================

async def connect_to_real_chrome(
    playwright,
    cdp_url: str = "http://127.0.0.1:9222",
):

    print(
        "Connecting to logged-in Chrome..."
    )

    try:
        browser: Browser = await asyncio.wait_for(
            playwright.chromium.connect_over_cdp(cdp_url),
            timeout=15,
        )
    except asyncio.TimeoutError as exc:
        raise RuntimeError(
            f"Timed out connecting to Chrome CDP at {cdp_url}. "
            "Start Chrome with --remote-debugging-port=9222 and retry."
        ) from exc
    except Exception as exc:
        raise RuntimeError(
            f"Could not connect to Chrome CDP at {cdp_url}: {exc}"
        ) from exc

    if not browser.contexts:

        raise RuntimeError(
            "No Chrome context available."
        )

    context: BrowserContext = (
        browser.contexts[0]
    )

    return browser, context


# ============================================================
# MAIN
# ============================================================

async def main():

    print()
    print("=" * 70)
    print("COMPANY WEBSITE APPLICATION AGENT")
    print("=" * 70)

    print()
    print(
        f"DRY_RUN = {DRY_RUN}"
    )
    print()

    # This module is a reusable engine, not a job-specific test harness.
    # Platform agents normally pass their discovered application URL directly
    # to apply(); standalone use must supply one explicitly.
    target_url = (
        sys.argv[1].strip()
        if len(sys.argv) > 1 and sys.argv[1].strip()
        else os.getenv("COMPANY_APPLICATION_URL", "").strip()
    )
    if not target_url:
        raise RuntimeError(
            "Provide a company application URL as the first argument or set COMPANY_APPLICATION_URL."
        )

    async with async_playwright() as playwright:

        try:

            browser, context = (
                await connect_to_real_chrome(
                    playwright
                )
            )

        except Exception as exc:

            print()
            print(
                "Could not connect to existing Chrome."
            )
            print(exc)
            print()

            return

        live_pages = [
            page
            for page in context.pages
            if not page.is_closed()
        ]

        if live_pages:

            page = live_pages[-1]

        else:
            try:
                page = await asyncio.wait_for(
                    context.new_page(),
                    timeout=15,
                )
            except asyncio.TimeoutError as exc:
                raise RuntimeError(
                    "Timed out creating a new Chrome tab."
                ) from exc

        agent = CompanyWebsiteAgent(
            dry_run=DRY_RUN
        )

        result = await agent.apply(
            page,
            target_url,
        )

        print()
        print("=" * 70)
        print("FINAL RESULT")
        print("=" * 70)

        print(
            json.dumps(
                result,
                indent=2,
                default=str,
            )
        )

        print()
        print("=" * 70)
        print("HISTORY")
        print("=" * 70)

        for item in agent.history:

            print(item)

        print()
        print(
            "Browser left open for inspection."
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
