import asyncio
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
import sys
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from urllib.parse import urljoin, urlencode, urlparse, parse_qs

# Direct platform execution must resolve its own storage/adapter modules even
# when the project root has been injected into PYTHONPATH.
PLATFORM_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
while str(PLATFORM_DIR) in sys.path:
    sys.path.remove(str(PLATFORM_DIR))
sys.path.insert(0, str(PLATFORM_DIR))

try:
    from .qa_engine import AnswerEngine
    from .storage import db, seen, app, qa, canonical_job_key
    from .jd_matcher import JDMatcher
except ImportError:
    # Direct-file execution: use platform-qualified imports to avoid module-name
    # collisions with another portal's ``storage``/``qa_engine`` modules.
    from platforms.glassdoor.qa_engine import AnswerEngine
    from platforms.glassdoor.storage import db, seen, app, qa, canonical_job_key
    from platforms.glassdoor.jd_matcher import JDMatcher
from src.application.common.company_website_agent import CompanyWebsiteAgent
from platforms.indeed.indeed_agent import IndeedAgent

BASE = "https://www.glassdoor.co.in"

# Indeed keeps its persistent site chrome (global nav, header, the site-wide
# "Job title, keywords, or company" / "City, state, zip code" search bar)
# visible even on dedicated flow pages such as smartapply.indeed.com. Broad
# selectors like "form:visible" or "input:visible" match those chrome
# elements too, which gets misread as an application question/field (e.g.
# "Q: search: Job title, keywords, or company" / "A: Mr"). Appended to a
# selector, this excludes anything that lives inside that chrome.
CHROME_EXCLUDE = (
    ":not(nav *):not(header *):not([role='banner'] *):not([role='navigation'] *)"
    ":not([class*='gnav' i] *):not([id*='gnav' i] *):not(form[role='search'] *)"
    ":not(nav):not(header):not([role='banner']):not([role='navigation'])"
    ":not([class*='gnav' i]):not([id*='gnav' i]):not(form[role='search'])"
)


class GlassdoorAgent:
    """Glassdoor application agent using Glassdoor job pages with Indeed SmartApply-native application flow."""

    def __init__(self):
        self.engine = AnswerEngine()
        self.con = db()
        self.current_resume_path = None
        self.dry_run = os.getenv("DRY_RUN", "false").strip().lower() in {"1", "true", "yes", "on"}
        cfg_path = Path(__file__).with_name("role_config.json")
        self.cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        configured_target = int(self.cfg.get("target_direct_applications", 10))
        configured_candidates = int(self.cfg.get("max_total_candidates", 1000))
        # An operator can cap a supervised run without editing role_config.json.
        # Invalid values are ignored rather than accidentally expanding scope.
        self.target_direct_applications = self._positive_env_cap(
            "MAX_APPLICATIONS", configured_target
        )
        self.max_total_candidates = self._positive_env_cap(
            "MAX_JOBS", configured_candidates
        )
        self.max_search_pages_per_role = max(1, int(self.cfg.get("max_search_pages_per_role", 5)))
        self.direct_applications = 0
        self.external_skipped = 0  # backward-compatible counter for unsupported/invalid external routes
        self.external_applications = 0
        self.external_filled = 0
        self.external_errors = 0
        self.low_match_skipped = 0
        self.seen_urls = set()
        self.seen_job_keys = set()
        self.answered = set()
        self._last_answer_value = None
        self.matcher = JDMatcher(str(Path(__file__).parent))
        self.search_page = None
        self._jobs_section_opened = False
        runtime_dir = PLATFORM_DIR.parent.parent / "webapp" / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        self.human_verification_marker = Path(
            os.getenv("JOB_AGENT_HUMAN_VERIFICATION_MARKER", str(runtime_dir / "glassdoor_human_verification.json"))
        )
        self.human_verification_signal = Path(
            os.getenv("JOB_AGENT_HUMAN_VERIFICATION_SIGNAL", str(runtime_dir / "glassdoor_human_verification.signal"))
        )

    def _mark_human_verification_waiting(self, scope: str) -> None:
        try:
            self.human_verification_marker.parent.mkdir(parents=True, exist_ok=True)
            self.human_verification_marker.write_text(
                json.dumps({"portal": "glassdoor", "scope": scope, "waiting": True}),
                encoding="utf-8",
            )
            try:
                self.human_verification_signal.unlink()
            except FileNotFoundError:
                pass
        except Exception as exc:
            print(f"  HUMAN VERIFICATION MARKER ERROR: {type(exc).__name__}: {exc}")

    def _clear_human_verification_wait(self) -> None:
        for path in (self.human_verification_marker, self.human_verification_signal):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except Exception as exc:
                print(f"  HUMAN VERIFICATION CLEANUP ERROR: {type(exc).__name__}: {exc}")

    def _continue_requested(self) -> bool:
        return self.human_verification_signal.exists()

    @staticmethod
    def _positive_env_cap(name, configured_limit):
        """Return the smaller positive operator cap, or the configured limit."""
        raw = os.getenv(name, "").strip()
        if not raw:
            return configured_limit
        try:
            requested = int(raw)
        except ValueError:
            return configured_limit
        return min(configured_limit, requested) if requested > 0 else configured_limit

    def fingerprint(self, url, title=""):
        key = (url or "").strip().lower()
        if key:
            parsed = urlparse(key)
            qs = parse_qs(parsed.query)
            jk = qs.get("jk", [None])[0]
            if jk:
                return hashlib.sha256(f"glassdoor:{jk}".encode()).hexdigest()
            key = key.split("#", 1)[0]
        return hashlib.sha256((key or (title or "").strip().lower()).encode()).hexdigest()

    def completed(self, body):
        t = re.sub(r"\s+", " ", body or "").lower()
        return any(p in t for p in (
            "your application was submitted to",
            "application was submitted to",
            "your application has been submitted",
            "application submitted successfully",
        ))

    async def detect_blocker(self, page):
        """Detect only a real, visible Indeed security challenge.

        A normal Indeed application page can contain the word "reCAPTCHA" in
        its legal/footer text ("This site is protected by reCAPTCHA...").
        That is NOT a challenge. Bare words such as captcha, recaptcha,
        challenge, or security verification therefore never trigger a stop.
        """
        if page is None or page.is_closed():
            return False

        try:
            visible_text = re.sub(
                r"\s+",
                " ",
                await page.locator("body").inner_text(timeout=5000),
            ).strip().lower()
        except Exception:
            visible_text = ""

        strong_phrases = (
            "verify you're human",
            "verify you are human",
            "confirm you're human",
            "confirm you are human",
            "confirm you are not a robot",
            "are you a robot",
            "robot check",
            "complete the verification",
            "click to verify",
            "press and hold",
            "additional verification required",
            "unusual traffic",
        )
        if any(p in visible_text for p in strong_phrases):
            return True

        security_phrase = (
            "security verification" in visible_text
            or "performing security verification" in visible_text
        )
        actionable = any(
            p in visible_text
            for p in (
                "verification required",
                "verification challenge",
                "human verification",
                "complete the verification",
                "click to verify",
                "press and hold",
            )
        )
        if security_phrase and actionable:
            return True

        # Only a VISIBLE CAPTCHA/verification widget counts. The legal footer
        # mentioning reCAPTCHA does not. Include generic captcha selectors too
        # because some Indeed challenges are not classed as "recaptcha".
        try:
            if await page.locator(
                'iframe[title*="captcha" i]:visible, '
                'iframe[src*="captcha" i]:visible, '
                'iframe[title*="recaptcha" i]:visible, '
                'iframe[src*="recaptcha" i]:visible, '
                '[class*="captcha" i]:visible, '
                '[id*="captcha" i]:visible, '
                '[aria-label*="captcha" i]:visible, '
                '[class*="recaptcha" i]:visible, '
                '[id*="recaptcha" i]:visible'
            ).count():
                return True
        except Exception:
            pass

        # Cloudflare-style full-page challenge.
        if (
            "just a moment" in visible_text
            and (
                "cloudflare" in visible_text
                or "checking your browser" in visible_text
            )
            and not any(
                marker in visible_text
                for marker in (
                    "application preview",
                    "review your application",
                    "apply now",
                    "submit your application",
                    "job description",
                )
            )
        ):
            return True

        # IMPORTANT: do not search for "captcha" or "recaptcha" here.
        return False

    async def pause_for_human_verification(self, page, scope="job"):
        """Pause until the operator clears verification and presses Enter/Continue in the dashboard."""
        self._mark_human_verification_waiting(scope)
        print(f"  HUMAN VERIFICATION DETECTED on {scope} tab.")
        print("  ACTION REQUIRED: Complete Indeed's human verification manually in Chrome.")
        print("  Then press the dashboard 'Enter / Continue Indeed' button to resume this same flow.")

        try:
            timeout_seconds = float(
                os.getenv("INDEED_HUMAN_VERIFICATION_TIMEOUT_SECONDS", "900")
            )
        except (TypeError, ValueError):
            timeout_seconds = 900.0
        timeout_seconds = max(30.0, min(timeout_seconds, 3600.0))

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        last_notice = 0.0

        while loop.time() < deadline:
            try:
                if page is None or page.is_closed():
                    return False

                if self._continue_requested():
                    if not await self.detect_blocker(page):
                        await self.wait_stable(page)
                        # The dashboard button is the explicit resume gate.
                        # Re-check after stabilization so a transient animation
                        # cannot make us resume too early.
                        if not await self.detect_blocker(page):
                            self._clear_human_verification_wait()
                            print("  HUMAN VERIFICATION CLEARED — dashboard Enter/Continue received; resuming the same Indeed flow.")
                            return True
                    else:
                        print("  ENTER/CONTINUE received, but Indeed verification is still visible; waiting for it to clear.")

                now = loop.time()
                if now - last_notice >= 10.0:
                    remaining = max(0, int(deadline - now))
                    print(
                        f"  Waiting for manual verification to clear... "
                        f"{remaining}s remaining."
                    )
                    last_notice = now

                await page.wait_for_timeout(1000)
            except Exception as exc:
                print(
                    f"  HUMAN VERIFICATION WAIT ERROR: "
                    f"{type(exc).__name__}: {exc}"
                )
                await asyncio.sleep(1)

        self._clear_human_verification_wait()
        print(
            "  HUMAN VERIFICATION TIMEOUT — preserving the application tab."
        )
        return False

    async def wait_stable(self, page):
        if page is None or page.is_closed():
            return False
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            await page.wait_for_timeout(1000)
            return True
        except Exception:
            return False

    async def is_glassdoor_job_url(self, page):
        """True while the browser is still on a Glassdoor job page."""
        return "glassdoor.co.in" in (page.url or "").lower() or "glassdoor.com" in (page.url or "").lower()

    def _is_suspicious_job_key(self, jk):
        """Reject obvious synthetic/test job keys that can appear in page markup."""
        value = re.sub(r"[^0-9a-f]", "", (jk or "").lower())
        if len(value) < 8 or len(value) > 64:
            return True
        if len(set(value)) <= 2:
            return True
        if len(value) >= 12:
            digits = "0123456789abcdef"
            if all(ch in digits for ch in value):
                positions = [digits.index(ch) for ch in value]
                cyclic = all((positions[i] + 1) % 16 == positions[i + 1] for i in range(len(positions) - 1))
                if cyclic:
                    return True
        return False

    def _is_valid_job_url(self, url):
        """Accept real-looking Glassdoor job-detail URLs only."""
        try:
            parsed = urlparse(url or "")
            host = (parsed.netloc or "").lower()
            if "glassdoor.co.in" not in host and "glassdoor.com" not in host:
                return False
            path = (parsed.path or "").lower()
            # Glassdoor uses both /Job/... search/detail routes and /job/... detail routes.
            return any(token in path for token in ("/job/", "/job-listing/", "/jobs/"))
        except Exception:
            return False

    async def collect_job_urls(self, page):
        """Collect Glassdoor job-detail links exposed in the current results page."""
        found = []
        selectors = (
            'a[href*="/job/"]:visible',
            'a[href*="/Job/"]:visible',
            'a[href*="/job-listing/"]:visible',
        )
        for delay in (900, 1600, 2400):
            try:
                await page.wait_for_timeout(delay)
            except Exception:
                break
            try:
                anchors = []
                for sel in selectors:
                    loc = page.locator(sel)
                    count = min(await loc.count(), 300)
                    for i in range(count):
                        el = loc.nth(i)
                        href = (await el.get_attribute('href') or '').strip()
                        text = re.sub(r"\s+", " ", (await el.inner_text()).strip())
                        if not href or not text:
                            continue
                        anchors.append((href, text))
            except Exception:
                anchors = []
            for href, _text in anchors:
                full = urljoin(BASE, href)
                if not self._is_valid_job_url(full):
                    continue
                clean = full.split('#',1)[0]
                # Avoid results/search pages themselves.
                if re.search(r"/job/(?:jobs|search|index)", clean, re.I):
                    continue
                if clean not in found:
                    found.append(clean)
            if found:
                break
            try:
                await page.mouse.wheel(0, 1600)
            except Exception:
                pass

        print(f"  Glassdoor search exposed {len(found)} valid job URLs")
        return found

    async def _next_search_page_url(self, page, current_url, page_number):
        """Use Glassdoor's visible Next control when available."""
        try:
            controls = page.locator("a:visible,button:visible,[role='button']:visible")
            for i in range(min(await controls.count(), 300)):
                el = controls.nth(i)
                try:
                    label = re.sub(r"\s+", " ", await self._control_label(el))
                    if not re.fullmatch(r"(?:next|next page)", label.strip(), re.I):
                        continue
                    href = await el.get_attribute('href')
                    if href:
                        nxt = urljoin(BASE, href).split('#',1)[0]
                        if nxt != current_url.split('#',1)[0]:
                            return nxt
                except Exception:
                    pass
        except Exception:
            pass
        return None

    async def get_job_text(self, page):
        try:
            return (await page.locator("body").inner_text(timeout=10000)).strip()
        except Exception:
            return ""

    async def _control_label(self, el):
        try:
            # Pagination controls can detach while Glassdoor refreshes results.
            # Keep each label probe bounded so one stale locator cannot hang the loop.
            return re.sub(r"\s+", " ", await el.evaluate("""e => ([
                e.innerText || e.textContent || '',
                e.getAttribute('aria-label') || '',
                e.getAttribute('value') || '',
                e.getAttribute('title') || '',
                e.getAttribute('placeholder') || ''
            ]).join(' ')""", timeout=1500)).strip()
        except Exception:
            return ""

    async def _wait_for_native_application_target(self, context, source_page, pages_before, source_url, timeout_ms=60000):
        """Wait until Easy Apply produces a distinct application surface."""
        elapsed = 0
        while elapsed < timeout_ms:
            candidates = [p for p in context.pages if p not in pages_before]
            # Some Glassdoor flows transition in the current tab instead of opening one.
            if source_page not in candidates and not source_page.is_closed():
                candidates.append(source_page)
            for candidate in candidates:
                try:
                    if candidate.is_closed():
                        continue
                    current = (candidate.url or "").lower()
                    original = (source_url or "").lower()
                    if candidate is source_page and (not current or current == original):
                        continue
                    body = await candidate.locator("body").inner_text(timeout=1500)
                    if re.search(r"review your application|submit your application|application questions|resume|cv options", body or "", re.I):
                        return candidate
                    # A new nonblank tab is a plausible transition, but wait for its UI.
                except Exception:
                    continue
            await source_page.wait_for_timeout(250)
            elapsed += 250
        return None

    async def direct_apply_control(self, page):
        """Find Glassdoor's native Easy Apply control."""
        exact = re.compile(r"^\s*(easy\s+apply|easy\s+apply\s+now)\s*$", re.I)
        try:
            loc = page.get_by_role("button", name=exact)
            for i in range(min(await loc.count(), 30)):
                el = loc.nth(i)
                if await el.is_visible() and not await el.is_disabled():
                    return el
        except Exception:
            pass
        try:
            loc = page.get_by_role("link", name=exact)
            for i in range(min(await loc.count(), 30)):
                el = loc.nth(i)
                if await el.is_visible() and not await el.is_disabled():
                    return el
        except Exception:
            pass
        try:
            loc = page.locator("button:visible,a:visible,[role='button']:visible")
            for i in range(min(await loc.count(), 300)):
                el = loc.nth(i)
                try:
                    label = await self._control_label(el)
                    if not exact.fullmatch(label):
                        continue
                    href = await el.get_attribute('href')
                    if href and 'glassdoor' not in urljoin(page.url, href).lower():
                        continue
                    return el
                except Exception:
                    pass
        except Exception:
            pass
        return None

    async def apply_target_is_external(self, page):
        """Classify Glassdoor Apply now/company links as external; Easy Apply is native."""
        try:
            controls = page.locator("a:visible,button:visible,[role='button']:visible")
            for i in range(min(await controls.count(), 250)):
                el = controls.nth(i)
                try:
                    text = (await self._control_label(el)).strip().lower()
                    if not text or "apply" not in text:
                        continue
                    if re.search(r"easy\s+apply", text, re.I):
                        return False
                    if re.search(r"apply\s+(?:now|on|via)|apply externally|company site|employer site", text, re.I):
                        return True
                    href = await el.get_attribute('href')
                    target = (href or await el.get_attribute('data-href') or await el.get_attribute('data-url') or '').strip()
                    if target and not target.startswith(('#','javascript:','mailto:')):
                        if 'glassdoor' not in urljoin(page.url, target).lower():
                            return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    async def _external_apply_control(self, page):
        """Find Glassdoor's explicit employer-site Apply control.

        Current Glassdoor job HTML exposes a stable data-test=applyButton
        button whose label is exactly ``Apply on employer site``. Prefer that
        contract before falling back to semantic/attribute discovery.
        """
        try:
            exact = page.locator("button[data-test='applyButton']:visible").first
            if await exact.count() and await exact.is_visible() and not await exact.is_disabled():
                label = (await self._control_label(exact)).strip()
                if re.search(r"apply\s+on\s+(?:the\s+)?employer\s+site|apply\s+now", label, re.I):
                    return exact
        except Exception:
            pass
        try:
            controls = page.locator("button:visible,a:visible,[role='button']:visible,input[type='button']:visible,input[type='submit']:visible")
            for i in range(min(await controls.count(), 400)):
                el = controls.nth(i)
                try:
                    if not await el.is_visible() or await el.is_disabled():
                        continue
                    label = (await self._control_label(el)).strip()
                    if re.search(r"easy\s+apply", label, re.I):
                        continue
                    if re.search(r"apply\s+on\s+(?:the\s+)?employer\s+site|apply\s+now|apply\s+on\s+company\s+site", label, re.I):
                        return el
                except Exception:
                    continue
        except Exception:
            pass
        return None

    async def _wait_for_external_apply_control(self, page, timeout_ms=10000):
        """Wait for Glassdoor's employer-site Apply CTA to become actionable.

        Glassdoor can hydrate the job-detail CTA after the initial DOM load.
        A single immediate selector pass can therefore report a false
        ``external_apply_not_found`` even when the button is about to appear.
        """
        deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
        last_probe = 0.0
        while asyncio.get_running_loop().time() < deadline:
            control = await self._external_apply_control(page)
            if control is not None:
                return control
            try:
                await page.wait_for_timeout(250)
            except Exception:
                await asyncio.sleep(0.25)
            last_probe = asyncio.get_running_loop().time()
        return None

    async def _click_skip_for_now(self, page):
        """Dismiss the Glassdoor preference modal observed before external redirects."""
        if page is None or page.is_closed():
            return False
        exact = re.compile(r"^\s*skip\s+for\s+now\s*$", re.I)
        for getter in (
            lambda: page.get_by_role('button', name=exact),
            lambda: page.get_by_text(exact),
        ):
            try:
                loc = getter()
                for i in range(min(await loc.count(), 10)):
                    el = loc.nth(i)
                    if not await el.is_visible():
                        continue
                    try:
                        await el.click(timeout=5000)
                    except Exception:
                        await el.click(timeout=5000, force=True)
                    print("  GLASSDOOR EXTERNAL: clicked 'Skip for now'.")
                    return True
            except Exception:
                pass
        return False

    async def _run_external_company_flow(self, context, page, source_url):
        """Follow Glassdoor's external Apply route, wait for the ATS page to load, then use the canonical company-site form engine."""
        pages_before = set(context.pages)
        await self._click_skip_for_now(page)
        control = await self._wait_for_external_apply_control(page, timeout_ms=10000)
        if not control:
            print("  EXTERNAL APPLY: matching Glassdoor Apply control not found; leaving tab open.")
            return "external_apply_not_found", page

        try:
            await control.scroll_into_view_if_needed()
            await control.click(timeout=10000)
        except Exception:
            try:
                await control.click(timeout=5000, force=True)
            except Exception as exc:
                print(f"  EXTERNAL APPLY CLICK FAILED: {type(exc).__name__}: {exc}. Leaving tab open.")
                return "external_apply_click_failed", page

        print("  *** GLASSDOOR EXTERNAL APPLY CLICKED ***")
        active = page

        # Match the working Indeed external architecture: Apply is only the
        # transition trigger. Do not hand the page to the form engine until the
        # company/ATS destination is actually reached and has had time to load.
        for _ in range(240):  # 60s maximum transition wait
            for candidate in [p for p in context.pages if not p.is_closed()]:
                await self._click_skip_for_now(candidate)
            try:
                new_pages = [
                    p for p in context.pages
                    if p not in pages_before and not p.is_closed()
                ]
                for candidate in reversed(new_pages):
                    try:
                        await candidate.wait_for_load_state(
                            "domcontentloaded", timeout=3000
                        )
                    except Exception:
                        pass
                    try:
                        u = (candidate.url or "").strip()
                    except Exception:
                        u = ""
                    if u and "about:blank" not in u.lower() and "glassdoor." not in u.lower():
                        active = candidate
                        break
                if active is not page:
                    break

                try:
                    u = (page.url or "").strip()
                except Exception:
                    u = ""
                if u and "about:blank" not in u.lower() and "glassdoor." not in u.lower():
                    active = page
                    break
            except Exception:
                pass

            try:
                await page.wait_for_timeout(250)
            except Exception:
                break

        try:
            active_url = (active.url or "").strip()
        except Exception:
            active_url = ""
        if not active_url or "glassdoor." in active_url.lower() or active_url.lower() == "about:blank":
            print("  EXTERNAL APPLY: company-site destination was not reached within 60s; leaving tab open.")
            return "external_apply_not_reached", page

        print(f"  EXTERNAL APPLICATION DESTINATION READY: {active_url}")

        # Preserve the canonical project-level profile and the job-specific
        # tailored resume used by the working Indeed external route.
        project_profile_path = Path(__file__).resolve().parents[2] / "profile.json"
        profile_path = str(project_profile_path)
        resume_path = self.current_resume_path
        if not resume_path or not Path(str(resume_path)).exists():
            print("  EXTERNAL RESUME: job-specific tailored resume is unavailable; refusing generic resume.pdf fallback.")
            return "external_error", active
        print(f"  EXTERNAL RESUME TARGET: {Path(str(resume_path)).name}")

        try:
            filler = CompanyWebsiteAgent(
                dry_run=self.dry_run,
                profile_path=profile_path,
                resume_path=resume_path,
            )
            await filler.wait_for_page(active)
            result = await filler.apply(
                active, active_url or source_url, application_opened=False
            )
            state = str(result.get("status", "")).upper()
            print(f"  EXTERNAL APPLICATION RESULT: {state}")
            if state in {"READY_TO_SUBMIT", "EXTERNAL_FILLED"}:
                return "external_filled", active
            if state in {"SUBMITTED", "SUCCESS", "APPLIED"}:
                return "external_submitted", active
            if state in {
                "CAPTCHA_REQUIRED",
                "HUMAN_INTERVENTION",
                "SECURITY_CHECK",
                "LOGIN_REQUIRED",
            }:
                return "external_blocked", active
            if state in {
                "QUESTION_UNRESOLVED",
                "FORM_ERROR",
                "FAILED",
                "FORM_NOT_READY",
                "APPLY_BUTTON_NOT_FOUND",
                "ALREADY_APPLIED",
            }:
                return "external_partial", active
            return "external_error", active
        except Exception as exc:
            print(f"  EXTERNAL COMPANY AGENT ERROR: {type(exc).__name__}: {exc}")
            return "external_error", active

    async def _record_status(self, url, title, status, company="", description="", match=None):
        try:
            match = match or {}
            app(
                self.con, url, title, status,
                company=company,
                description=description,
                match_score=match.get("score"),
                eligible=match.get("eligible"),
                matched_skills=match.get("matched_skills") or [],
            )
        except Exception as e:
            print(f"  DB record failed: {type(e).__name__}: {e}")

    async def _extract_company_name(self, page) -> str:
        """Extract the employer name from the current Glassdoor job page.

        Prefer explicit employer/company attributes and known Indeed containers;
        never infer a company name from arbitrary body text.
        """
        selectors = (
            '[data-test="employer-name"]',
            '[data-test="employer-name-link"]',
            '[data-testid*="employer" i]',
            'a[href*="/Overview/"]',
            'a[href*="/Reviews/"]',
            '[class*="EmployerProfile"]',
            '[class*="employerName" i]',
            '[class*="companyName" i]',
        )
        for sel in selectors:
            try:
                loc = page.locator(sel).filter(visible=True)
                if await loc.count():
                    for i in range(min(await loc.count(), 3)):
                        text = (await loc.nth(i).inner_text()).strip()
                        if text and len(text) <= 160:
                            return re.sub(r"\s+", " ", text)
            except Exception:
                continue
        try:
            meta = page.locator("meta[property='og:site_name'], meta[name='author']")
            if await meta.count():
                value = await meta.first.get_attribute("content")
                if value and value.strip():
                    return re.sub(r"\s+", " ", value.strip())[:160]
        except Exception:
            pass
        # Many current Glassdoor job pages expose the employer in JobPosting JSON-LD.
        try:
            scripts = page.locator("script[type='application/ld+json']")
            count = await scripts.count()
            for i in range(min(count, 10)):
                raw = (await scripts.nth(i).text_content() or "").strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                candidates = data if isinstance(data, list) else [data]
                for item in candidates:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("@type", "")).lower() != "jobposting":
                        continue
                    org = item.get("hiringOrganization") or {}
                    name = org.get("name") if isinstance(org, dict) else None
                    if name and str(name).strip():
                        return re.sub(r"\s+", " ", str(name).strip())[:160]
        except Exception:
            pass
        # Final deterministic fallback: Indeed redirect URLs sometimes expose cmp=.
        try:
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(page.url).query)
            value = (query.get("cmp") or [""])[0].strip()
            if value:
                return re.sub(r"\s+", " ", value)[:160]
        except Exception:
            pass
        return ""

    async def _run_native_indeed_flow(self, context, source_page, pages_before, source_url):
        """Run Glassdoor Easy Apply through the proven Indeed SmartApply state machine."""
        native = IndeedAgent()
        native.dry_run = self.dry_run
        native.current_resume_path = self.current_resume_path
        application_page = await native._wait_for_native_application_target(
            context, source_page, pages_before, source_url, timeout_ms=60000
        )
        if application_page is None:
            print("  NATIVE APPLICATION DID NOT OPEN/RENDER IN TIME — leaving tab open.")
            return "application_transition_timeout", None
        await native.wait_for_application_ready(application_page, timeout_ms=30000)
        if await native.detect_blocker(application_page):
            if not await native.pause_for_human_verification(application_page, "application"):
                return "human_intervention", application_page
        native_status = await native.run_application(application_page, source_url)
        print(f"  GLASSDOOR NATIVE APPLICATION RESULT: {native_status}")
        return native_status, application_page

    async def process_job(self, context, url):
        """Inspect one job in its own tab; on a match, start/attempt Apply and
        deliberately leave that tab open while the search moves to the next job.
        """
        page = await asyncio.wait_for(context.new_page(), timeout=15)
        application_page = page
        application_opened = False
        title = url
        company = ""
        body = ""
        match = {}
        status = "error"
        try:
            if not self._is_valid_job_url(url):
                print(f"  SKIPPED INVALID/SYNTHETIC INDEED JOB URL: {url}")
                status = "invalid_job_url"
                return status

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except (asyncio.TimeoutError, PlaywrightTimeoutError):
                print("  JOB NAVIGATION TIMEOUT: leaving tab open and continuing to next job.")
                status = "navigation_timeout"
                return status

            await self.wait_stable(page)
            title = (await page.title()).strip() or url
            company = await self._extract_company_name(page)
            if company:
                print(f"  COMPANY: {company}")
            print(f"  Opened: {title[:120]}")
            if await self.detect_blocker(page):
                if await self.pause_for_human_verification(page, "job"):
                    # Re-read title/body after the human clears the challenge.
                    await self.wait_stable(page)
                else:
                    status = "blocked"
                    return status
            if not await self.is_glassdoor_job_url(page):
                self.external_skipped += 1
                status = "external_skipped"
                print(f"  SKIPPED NON-GLASSDOOR DESTINATION: {page.url}")
                return status

            body = await self.get_job_text(page)
            match = self.matcher.match(title, body)
            print(
                f"  JD MATCH: {match['score']}/{match['threshold']} | eligible={match['eligible']} "
                f"| matched skills={len(match['matched_skills'])} | experience={match['experience_note']}"
            )
            if match.get("rejection_reasons"):
                print("  REJECTION REASONS:", "; ".join(match["rejection_reasons"]))

            if not match["eligible"]:
                self.low_match_skipped += 1
                status = "low_match"
                print("  SKIPPED: role/entry-level/experience/JD criteria not met; closing this tab and continuing.")
                return status

            print("  *** MATCHING JOB FOUND — LEAVING JOB TAB OPEN ***")
            try:
                from resume_integration import build_tailored_resume
                self.current_resume_path = build_tailored_resume(
                    profile_path=str(Path(__file__).with_name("profile.json")),
                    title=title, jd_text=body, platform="glassdoor", job_url=url, company=company
                )
            except Exception as exc:
                print(f"  RESUME ROUTING WARNING: {type(exc).__name__}: {exc}")
            self._indeed_resume_replaced = False

            # External/company-site applications are part of the autonomous
            # workflow. Detect them without clicking arbitrary links, then use
            # the canonical external form engine after clicking the correct CTA.
            if await self.apply_target_is_external(page):
                self.external_applications += 1
                application_opened = True
                print("  *** EXTERNAL/COMPANY-SITE APPLY DETECTED — opening external application ***")
                status, application_page = await self._run_external_company_flow(
                    context, page, url
                )
                if status in {"external_filled", "external_submitted"}:
                    self.external_filled += 1
                elif status not in {"external_blocked", "external_partial"}:
                    self.external_errors += 1
                return status

            control = await self.direct_apply_control(page)
            if not control:
                status = "match_found_no_direct_apply"
                print("  MATCHED, but no native Glassdoor Easy Apply button found. Leaving tab open; moving to next job.")
                return status

            # DRY_RUN blocks only final submission.  Clicking native Apply,
            # answering fields, and advancing intermediate steps are required
            # to exercise the real question → answer → fill → verify loop.
            if self.dry_run:
                print("  DRY RUN: native Apply and form filling are allowed; final Submit remains blocked.")

            # Snapshot tabs BEFORE Apply so a newly opened Indeed application tab
            # can be identified reliably after the Glassdoor Easy Apply click.
            pages_before = set(context.pages)
            try:
                await control.scroll_into_view_if_needed()
                await control.click(timeout=10000)
            except Exception:
                try:
                    await control.click(timeout=5000, force=True)
                except Exception as e:
                    status = "apply_click_failed"
                    print(f"  APPLY CLICK FAILED: {type(e).__name__}: {e}. Leaving tab open; moving to next job.")
                    return status

            self.direct_applications += 1
            application_opened = True
            print(f"  *** GLASSDOOR EASY APPLY CLICKED ({self.direct_applications}/{self.target_direct_applications}) ***")

            status, application_page = await self._run_native_indeed_flow(
                context, page, pages_before, url
            )
            return status

        except Exception as e:
            print(f"  JOB ERROR: {type(e).__name__}: {e}")
            # Once Apply has been opened, an unexpected engine exception must not
            # make the application tab disposable. Preserve the tab for manual
            # completion/debugging exactly like other application-failure states.
            if application_opened or (application_page is not None and application_page is not page):
                status = "application_error"
            else:
                status = "error"
            return status
        finally:
            self.current_resume_path = None
            await self._record_status(url, title, status, company=company, description=body, match=match)

            # IMPORTANT: Once an application has been opened, never close the
            # application page merely because the search controller moves to the
            # next job. In particular, a final Submit that could not be clicked,
            # a dry-run review page, CAPTCHA/security state, or an application
            # timeout must remain visible for manual completion.
            application_states_to_keep_open = {
                "apply_clicked",
                "blocked",
                "human_intervention",
                "ready_to_submit",
                "submit_not_found",
                "applied",
                "dry_run_complete",
                "submission_unconfirmed",
                "submission_unconfirmed",
                "no_progress",
                "timeout",
                "unknown_question",
                "fill_failed",
                "answer_not_verified",
                "no_questions",
                "form_discovery_failed",
                "navigation_timeout",
                "external_timeout",
                "apply_click_failed",
                "external_apply_not_found",
                "external_apply_click_failed",
                "external_apply_not_reached",
                "external_filled",
                "external_partial",
                "external_blocked",
                "external_error",
                "application_error",
            }
            try:
                target = application_page if application_page is not None else page

                # HARD NATIVE-APPLY SAFETY RULE:
                # Once the real Indeed "Apply with Indeed" CTA has been clicked,
                # never close the page merely because a downstream step returned
                # an unexpected/partial status. Indeed applications can fail at
                # resume upload, field verification, question routing, or an
                # intermediate CTA while the live application UI is still usable.
                # The old cleanup path could close that UI when the status was not
                # explicitly listed in application_states_to_keep_open.
                if application_opened:
                    if status == "applied":
                        print(f"  NATIVE APPLICATION COMPLETED: status={status} | {target.url}")
                    else:
                        print(
                            f"  NATIVE APPLICATION PRESERVED: status={status} | "
                            f"{target.url} | apply_already_clicked=True"
                        )
                    # Preserve both the application surface and its owning job
                    # tab. Do not enter the generic close path below.
                elif status in application_states_to_keep_open:
                    print(f"  LEAVING APPLICATION TAB OPEN: status={status} | {target.url}")
                else:
                    # If a separate application tab was created, do not close it
                    # just because the original job tab has completed.
                    if target is not page and not target.is_closed():
                        print(f"  APPLICATION TAB PRESERVED: {target.url}")
                    if status not in {
                        "match_found_no_direct_apply",
                        "match_found_dry_run",
                        "apply_clicked",
                    }:
                        if not page.is_closed() and target is page:
                            await page.close()
            except Exception:
                pass

    async def _open_jobs_section_first(self, page):
        """Open Glassdoor's Jobs section from its landing page before searching."""
        if self._jobs_section_opened:
            return True
        await page.goto(f"{BASE}/Job/index.htm", wait_until="domcontentloaded", timeout=60000)
        await self.wait_stable(page)
        # The observed Glassdoor header has a dedicated Jobs navigation item.
        # Require a visible exact match; do not silently skip straight to search.
        candidates = [
            page.get_by_role("link", name="Jobs", exact=True),
            page.get_by_role("button", name="Jobs", exact=True),
            page.get_by_text("Jobs", exact=True),
        ]
        for locator in candidates:
            try:
                if await locator.count() and await locator.first.is_visible():
                    await locator.first.click(timeout=10000)
                    await self.wait_stable(page)
                    self._jobs_section_opened = True
                    print("  GLASSDOOR NAV: clicked Jobs section before role search.")
                    return True
            except Exception:
                continue
        raise RuntimeError("Glassdoor Jobs navigation item was not found; refusing to bypass the requested first step.")

    async def run_search(self, context, search_url):
        # Keep one dedicated search tab. Job tabs can remain open without stealing
        # the navigation tab used for pagination/role changes.
        if self.search_page is None or self.search_page.is_closed():
            live = [p for p in context.pages if not p.is_closed()]
            self.search_page = live[-1] if live else await asyncio.wait_for(context.new_page(), timeout=15)
        page = self.search_page
        await self._open_jobs_section_first(page)
        current_url = search_url
        visited_page_keys = set()

        page_number = 0
        while True:
            page_number += 1
            if page_number > self.max_search_pages_per_role:
                print(f"  SEARCH PAGE CAP REACHED ({self.max_search_pages_per_role}); ending this role search.")
                break
            page_key = current_url.split("#", 1)[0]
            if page_key in visited_page_keys:
                print(f"  PAGE LOOP DETECTED: {page_key} — stopping this role search.")
                break
            visited_page_keys.add(page_key)
            if len(self.seen_job_keys) >= self.max_total_candidates:
                print(f"  Candidate scan cap reached ({self.max_total_candidates}); ending this role search.")
                break
            print(f"\n  SEARCH PAGE {page_number}: {current_url}")
            try:
                await page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
            except (asyncio.TimeoutError, PlaywrightTimeoutError):
                print("  SEARCH PAGE TIMEOUT: moving to the next role/search.")
                break
            await self.wait_stable(page)
            if await self.detect_blocker(page):
                if not await self.pause_for_human_verification(page, "search"):
                    print("  SEARCH VERIFICATION NOT CLEARED — ending this search safely.")
                    break
                await self.wait_stable(page)
            next_url = await self._next_search_page_url(page, current_url, page_number)
            raw_urls = await self.collect_job_urls(page)
            urls = []
            page_keys = set()
            for url in raw_urls:
                key = canonical_job_key(url)
                if key in page_keys or key in self.seen_job_keys:
                    continue
                page_keys.add(key)
                if seen(self.con, url):
                    self.seen_job_keys.add(key)
                    continue
                urls.append(url)
            print(f"  Search results exposed: {len(raw_urls)} | Unique new jobs: {len(urls)}")

            # Indeed can repeat the same result window on later offsets.
            # When a page exposes no unseen jobs, treat the search as exhausted
            # instead of continuing through duplicate pages forever.
            if not urls:
                print("  Pagination ended: no new jobs exposed on this page.")
                break

            for url in urls:
                if len(self.seen_job_keys) >= self.max_total_candidates:
                    break
                key = canonical_job_key(url)
                if key in self.seen_job_keys:
                    continue
                self.seen_job_keys.add(key)
                self.seen_urls.add(url)
                print(f"\nJOB CANDIDATE: {url}")
                try:
                    await self.process_job(context, url)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    print(f"  JOB ISOLATED ERROR: {type(e).__name__}: {e}")

                # A successful Apply click counts as an attempted application, but
                # the search continues to the next candidate instead of stopping.
                if self.direct_applications >= self.target_direct_applications:
                    print("  Application target reached; stopping new applications but finishing current page scan.")
                    # Continue scanning without further Apply clicks. process_job will
                    # leave matching jobs open, but no new click is attempted after target.
                    break

            if not next_url:
                break
            current_url = next_url
