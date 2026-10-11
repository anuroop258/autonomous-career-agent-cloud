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
while str(PLATFORM_DIR) in sys.path:
    sys.path.remove(str(PLATFORM_DIR))
sys.path.insert(0, str(PLATFORM_DIR))

from qa_engine import AnswerEngine
from storage import db, seen, app, qa, canonical_job_key
from jd_matcher import JDMatcher
from src.application.common.company_website_agent import CompanyWebsiteAgent

BASE = "https://in.indeed.com"

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


class IndeedAgent:
    """Indeed direct/native application agent built on the proven Naukri architecture."""

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
        runtime_dir = PLATFORM_DIR.parent.parent / "webapp" / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        self.human_verification_marker = Path(
            os.getenv("JOB_AGENT_HUMAN_VERIFICATION_MARKER", str(runtime_dir / "indeed_human_verification.json"))
        )
        self.human_verification_signal = Path(
            os.getenv("JOB_AGENT_HUMAN_VERIFICATION_SIGNAL", str(runtime_dir / "indeed_human_verification.signal"))
        )

    def _mark_human_verification_waiting(self, scope: str) -> None:
        try:
            self.human_verification_marker.parent.mkdir(parents=True, exist_ok=True)
            self.human_verification_marker.write_text(
                json.dumps({"portal": "indeed", "scope": scope, "waiting": True}),
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
                return hashlib.sha256(f"indeed-jk:{jk}".encode()).hexdigest()
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

    async def is_indeed_url(self, page):
        return "indeed." in (page.url or "").lower()

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
        """Accept only real-looking Indeed job URLs with a sane job key."""
        try:
            parsed = urlparse(url or "")
            if "indeed." not in (parsed.netloc or "").lower():
                return False
            path = (parsed.path or "").lower()
            if not any(x in path for x in ("/viewjob", "/rc/clk", "/pagead/clk")):
                return False
            jk = parse_qs(parsed.query).get("jk", [None])[0]
            return bool(jk) and not self._is_suspicious_job_key(jk)
        except Exception:
            return False

    async def collect_job_urls(self, page):
        found = []
        for delay in (900, 1600, 2400):
            try:
                await page.wait_for_timeout(delay)
            except Exception:
                break

            try:
                anchors = await page.locator("a[href]").evaluate_all(
                    """els => els.map(a => ({
                        href: a.href || '',
                        dataJk: a.getAttribute('data-jk') || '',
                        text: (a.innerText || a.textContent || '').trim()
                    }))"""
                )
            except Exception:
                anchors = []

            for item in anchors:
                href = (item.get("href") or "").strip()
                if not self._is_valid_job_url(href):
                    continue
                clean = href.split("#", 1)[0]
                if clean not in found:
                    found.append(clean)
            if found:
                break

            try:
                await page.mouse.wheel(0, 1400)
            except Exception:
                pass

        if not found:
            try:
                html = await page.content()
                for raw in re.findall(r'https?://[^"\'<>\s]+', html):
                    raw = raw.replace("\\/", "/").rstrip("),;")
                    if self._is_valid_job_url(raw):
                        clean = raw.split("#", 1)[0]
                        if clean not in found:
                            found.append(clean)
            except Exception:
                pass

        print(f"  Indeed search exposed {len(found)} valid job URLs")
        return found

    async def _next_search_page_url(self, page, current_url, page_number):
        """Build a monotonic Indeed results-page URL.

        Indeed sometimes exposes a broken/stale ``next`` link that points back to
        the same ``start`` offset (often with only a ``vjk`` parameter changed).
        That must never create an infinite/duplicate page loop.
        """

        parsed = urlparse(current_url)
        qs = parse_qs(parsed.query)
        try:
            current_start = int(qs.get("start", ["0"])[0])
        except (TypeError, ValueError):
            current_start = 0

        # Prefer the deterministic offset progression: 0 -> 10 -> 20 -> 30 ...
        next_start = current_start + 10
        qs["start"] = [str(next_start)]
        # ``vjk`` is only an Indeed navigation hint. Remove it so it cannot pin
        # us to the same result window when the site's link markup is stale.
        qs.pop("vjk", None)
        nxt = parsed._replace(query=urlencode(qs, doseq=True), fragment="").geturl()

        current_no_fragment = current_url.split("#", 1)[0]
        if nxt == current_no_fragment:
            return None

        print(f"  NEXT PAGE TARGET (deterministic start+10): {nxt}")
        return nxt

    async def get_job_text(self, page):
        try:
            return (await page.locator("body").inner_text(timeout=10000)).strip()
        except Exception:
            return ""

    async def _control_label(self, el):
        try:
            return re.sub(r"\s+", " ", await el.evaluate("""e => ([
                e.innerText || e.textContent || '',
                e.getAttribute('aria-label') || '',
                e.getAttribute('value') || '',
                e.getAttribute('title') || '',
                e.getAttribute('placeholder') || ''
            ]).join(' ')""")).strip()
        except Exception:
            return ""

    async def direct_apply_control(self, page):
        exact = re.compile(r"^\s*(apply with indeed|easily apply|apply now|apply)\s*$", re.I)
        for role in ("button", "link"):
            try:
                loc = page.get_by_role(role, name=exact)
                for i in range(min(await loc.count(), 40)):
                    el = loc.nth(i)
                    try:
                        if not await el.is_visible() or await el.is_disabled():
                            continue
                        href = await el.get_attribute("href")
                        if href and "indeed." not in urljoin(page.url, href).lower():
                            continue
                        return el
                    except Exception:
                        pass
            except Exception:
                pass
        try:
            loc = page.locator("button:visible,a:visible,[role='button']:visible,input[type='button']:visible,input[type='submit']:visible")
            for i in range(min(await loc.count(), 300)):
                el = loc.nth(i)
                try:
                    label = await self._control_label(el)
                    if not exact.fullmatch(label):
                        continue
                    href = await el.get_attribute("href")
                    if href and "indeed." not in urljoin(page.url, href).lower():
                        continue
                    return el
                except Exception:
                    pass
        except Exception:
            pass
        return None

    async def apply_target_is_external(self, page):
        try:
            controls = page.locator("a:visible,button:visible,[role='button']:visible")
            for i in range(min(await controls.count(), 200)):
                el = controls.nth(i)
                try:
                    text = (await self._control_label(el)).strip().lower()
                    # Explicit company/employer/external wording is sufficient to
                    # classify the CTA as external even when Indeed exposes no
                    # href/data-url attribute on the control.
                    if re.search(
                        r"\bapply\s+(?:on|via)\s+(?:the\s+)?(?:company|employer)\s+site\b|"
                        r"\bapply\s+externally\b|\bexternal\s+application\b|"
                        r"\bexternal\s+site\b|\bredirect\s+to\s+(?:the\s+)?employer\b",
                        text,
                        re.I,
                    ):
                        return True

                    if "apply" not in text or "apply with indeed" in text or "easily apply" in text:
                        continue
                    href = await el.get_attribute("href")
                    data = await el.get_attribute("data-href") or await el.get_attribute("data-url")
                    target = (href or data or "").strip()
                    if not target or target.startswith(("#", "javascript:", "mailto:")):
                        continue
                    if "indeed." not in urljoin(page.url, target).lower():
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    async def _external_apply_control(self, page):
        """Find the Indeed job-page CTA that routes to an external/company site."""
        try:
            controls = page.locator(
                "button:visible, a:visible, [role='button']:visible, input[type='button']:visible, input[type='submit']:visible"
            )
            for i in range(min(await controls.count(), 300)):
                el = controls.nth(i)
                try:
                    if not await el.is_visible() or await el.is_disabled():
                        continue
                    label = (await self._control_label(el)).strip()
                    if not re.search(r"\bapply\b", label, re.I):
                        continue
                    if re.search(r"apply\s+with\s+indeed|easily\s+apply|apply\s+now", label, re.I):
                        # "Apply now" can be a native Indeed CTA; only use the
                        # explicitly external route detected by apply_target_is_external().
                        if not re.search(r"company\s+site|employer\s+site|external", label, re.I):
                            continue
                    return el
                except Exception:
                    continue
        except Exception:
            pass
        return None

    async def _run_external_company_flow(self, context, page, source_url):
        """Click Indeed's external Apply route, fill what can be resolved, and never submit."""
        pages_before = set(context.pages)
        control = await self._external_apply_control(page)
        if not control:
            print("  EXTERNAL APPLY: matching company-site Apply control not found; leaving tab open.")
            return "external_apply_not_found", page

        try:
            await control.scroll_into_view_if_needed()
            await control.click(timeout=10000)
        except Exception:
            try:
                await control.click(timeout=5000, force=True)
            except Exception as e:
                print(f"  EXTERNAL APPLY CLICK FAILED: {type(e).__name__}: {e}. Leaving tab open.")
                return "external_apply_click_failed", page

        print("  *** APPLY ON COMPANY SITE CLICKED ***")
        active = page
        for _ in range(40):
            try:
                new_pages = [p for p in context.pages if p not in pages_before and not p.is_closed()]
                for candidate in reversed(new_pages):
                    try:
                        await candidate.wait_for_load_state("domcontentloaded", timeout=3000)
                    except Exception:
                        pass
                    u = (candidate.url or "").lower()
                    if u and "indeed." not in u and u != "about:blank":
                        active = candidate
                        break
                if active is not page:
                    break
                u = (page.url or "").lower()
                if u and "indeed." not in u and u != "about:blank":
                    active = page
                    break
            except Exception:
                pass
            try:
                await page.wait_for_timeout(250)
            except Exception:
                break

        try:
            if "indeed." in (active.url or "").lower() or not active.url:
                print("  EXTERNAL APPLY: company-site destination was not reached; leaving job tab open.")
                return "external_apply_not_reached", page
        except Exception:
            return "external_apply_not_reached", page

        # Respect the same global DRY_RUN safety boundary as native Indeed.
        # External/company forms must use the single project-level profile.
        # The old platform-specific Indeed profile omits core contact facts
        # (notably email/phone) and can silently cause deterministic fields to
        # remain blank.
        project_profile_path = Path(__file__).resolve().parents[2] / "profile.json"
        profile_path = str(project_profile_path)
        profile_data = {}
        try:
            profile_data = json.loads(Path(profile_path).read_text(encoding="utf-8"))
        except Exception:
            profile_data = {}
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
            # The company-site landing page may still be a job-detail page with
            # its own Apply CTA (for example, EA /ApplicationMethods). Let the
            # canonical company agent detect and click that CTA instead of
            # falsely declaring the page already inside the application form.
            result = await filler.apply(
                active, active.url or source_url, application_opened=False
            )
            state = str(result.get("status", "")).upper()
            print(f"  EXTERNAL APPLICATION RESULT: {state}")
            if state in {"READY_TO_SUBMIT", "EXTERNAL_FILLED"}:
                return "external_filled", active
            if state in {"QUESTION_UNRESOLVED", "FORM_ERROR", "FAILED", "FORM_NOT_READY", "APPLY_BUTTON_NOT_FOUND", "ALREADY_APPLIED"}:
                return "external_partial", active
            if state in {"CAPTCHA_REQUIRED", "HUMAN_INTERVENTION", "SECURITY_CHECK", "LOGIN_REQUIRED"}:
                return "external_blocked", active
            return "external_partial", active
        except Exception as e:
            print(f"  EXTERNAL COMPANY AGENT ERROR: {type(e).__name__}: {e}")
            return "external_error", active

    async def _find_resume(self):
        p = json.loads(Path(__file__).with_name("profile.json").read_text(encoding="utf-8"))
        r = p.get("resume", {}) or {}
        configured = str(r.get("path") or "").strip()
        filename = str(r.get("filename") or "").strip()
        if not configured:
            return None
        path = os.path.expandvars(os.path.expanduser(configured))
        if filename:
            candidate = Path(path) / filename
            if candidate.is_file():
                return str(candidate)
        base = Path(path)
        if base.is_file():
            return str(base)
        if base.is_dir():
            files = []
            for pth in base.iterdir():
                if not pth.is_file() or pth.suffix.lower() not in {".pdf", ".doc", ".docx"}:
                    continue
                low = pth.name.lower()
                score = (100 if "resume" in low else 0) + (80 if "cv" in low else 0) + (30 if "anuroop" in low else 0) + (10 if pth.suffix.lower() == ".pdf" else 0)
                files.append((score, pth.name.lower(), pth))
            if files:
                files.sort(key=lambda x: (-x[0], x[1]))
                print(f"  RESUME SELECTED: {files[0][2]}")
                return str(files[0][2])
        print(f"  RESUME NOT FOUND: {configured}")
        return None

    async def upload_resume_if_needed(self, page):
        resume = await self._find_resume()
        if not resume:
            return True
        try:
            files = page.locator("input[type='file']:visible")
            if await files.count():
                await files.first.set_input_files(resume)
                await page.wait_for_timeout(500)
                print(f"  Resume selected: {Path(resume).name}")
                return True
        except Exception as e:
            print(f"  Resume upload failed: {type(e).__name__}: {e}")
            return False
        return True

    async def current_question(self, page):
        selectors = [
            "[role='dialog']:visible" + CHROME_EXCLUDE,
            "[class*='ia-ApplyForm']:visible" + CHROME_EXCLUDE,
            "[class*='apply']:visible" + CHROME_EXCLUDE,
            "form:visible" + CHROME_EXCLUDE,
            "fieldset:visible" + CHROME_EXCLUDE,
        ]
        sources = []
        for sel in selectors:
            try:
                loc = page.locator(sel)
                for i in range(await loc.count()):
                    el = loc.nth(i)
                    if await el.is_visible():
                        txt = (await el.inner_text()).strip()
                        if txt:
                            sources.append(txt)
            except Exception:
                pass
        source = "\n".join(sources) if sources else await self.get_job_text(page)
        candidates = []
        for line in [x.strip() for x in source.splitlines() if x.strip()]:
            if not (5 <= len(line) <= 350):
                continue
            if not self._looks_like_question(line):
                continue
            if self.fingerprint(line) in self.answered:
                continue
            low = line.lower()
            if any(x in low for x in ("search jobs", "what are you looking for", "job alert", "sign in")):
                continue
            candidates.append(line)
        return candidates[-1] if candidates else None

    def _looks_like_question(self, text):
        low = text.lower()
        if any(x in low for x in ("review your application", "your application was submitted", "submit your application")):
            return False
        if "?" in text:
            return True
        return low.startswith(("do you ", "have you ", "are you ", "what ", "which ", "how ", "why ", "when ", "where ", "please ", "select ", "tell us", "describe "))

    async def visible_options(self, page):
        selectors = [
            s + CHROME_EXCLUDE for s in (
                "[role='dialog']:visible [role='radio']", "[role='dialog']:visible [role='checkbox']",
                "[role='dialog']:visible [role='option']", "[role='dialog']:visible button",
                "[role='dialog']:visible label", "[class*='apply']:visible [role='radio']",
                "[class*='apply']:visible [role='checkbox']", "[class*='apply']:visible [role='option']",
                "[class*='apply']:visible button", "[class*='apply']:visible label",
                "form:visible select option",
            )
        ]
        out = []
        action_words = {"save", "continue", "next", "submit", "submit your application", "review", "apply", "apply now", "back", "cancel", "done", "finish"}
        for sel in selectors:
            try:
                vals = await page.locator(sel).all_inner_texts()
                for v in vals:
                    v = re.sub(r"\s+", " ", v).strip()
                    if v and len(v) <= 180 and v.lower() not in action_words and v not in out:
                        out.append(v)
            except Exception:
                pass
        return out[:60]

    async def _field_group_label(self, el):
        """Find the human-readable label/prompt that belongs to a single form
        control, regardless of whether it is phrased as a question.

        Indeed's SmartApply screen ("Answer these questions from the
        employer") renders several distinct fields on ONE screen at once
        (e.g. "LinkedIn Profile", "Name as per Aadhar Card", "Website", a
        Yes/No consent field, "What is your current salary?"). Only the last
        of those is phrased as a question; the rest are plain field labels.
        current_question()/_looks_like_question() only recognise
        question-shaped sentences, so on this screen it silently ignores
        every field except the one real question. This helper instead reads
        the label directly off the DOM for a specific control, independent
        of phrasing.
        """
        try:
            return re.sub(r"\s+", " ", await el.evaluate(r"""
                e => {
                    const clean = s => (s || '').replace(/\*/g, '').trim();
                    const isChoice = (e.getAttribute('type') || '').toLowerCase() === 'radio'
                        || (e.getAttribute('type') || '').toLowerCase() === 'checkbox'
                        || e.getAttribute('role') === 'radio' || e.getAttribute('role') === 'checkbox';
                    // 1) <label for="id"> — but NOT for radio/checkbox controls,
                    //    where this would return the individual OPTION's own
                    //    text ("Yes") instead of the field/group's prompt.
                    if (e.id && !isChoice) {
                        const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
                        if (l && l.innerText.trim()) return clean(l.innerText);
                    }
                    // 2) ancestor <label> wrapping the control (same caveat).
                    if (!isChoice) {
                        const wrap = e.closest('label');
                        if (wrap) {
                            const t = clean(wrap.innerText);
                            if (t) return t;
                        }
                    }
                    // 3) aria-label / aria-labelledby
                    const aria = e.getAttribute('aria-label');
                    if (aria && aria.trim()) return clean(aria);
                    const labelledby = e.getAttribute('aria-labelledby');
                    if (labelledby) {
                        const parts = labelledby.split(' ')
                            .map(id => document.getElementById(id)?.innerText || '')
                            .filter(Boolean);
                        if (parts.length) return clean(parts.join(' '));
                    }
                    // 4) walk up a few ancestors looking for a field-group
                    //    container, and take its first non-input text node
                    //    (this is how Indeed's own field groups are built).
                    let node = e;
                    if (isChoice) {
                        // First climb to the container that holds the WHOLE
                        // option group (not just this one option), so the
                        // walk below looks for the question above the group
                        // rather than the option's own "Yes"/"No" text.
                        let n = e.closest('fieldset') || e.parentElement;
                        while (n && n !== document.body) {
                            const siblings = n.querySelectorAll(
                                'input[type="radio"], input[type="checkbox"], [role="radio"], [role="checkbox"]'
                            );
                            if (siblings.length > 1 || n.tagName === 'FIELDSET') { node = n; break; }
                            n = n.parentElement;
                        }
                        const legend = node.querySelector(':scope > legend');
                        if (legend && legend.innerText.trim()) return clean(legend.innerText);
                    }
                    for (let depth = 0; depth < 6 && node; depth++) {
                        node = node.parentElement;
                        if (!node) break;
                        const own = [...node.childNodes].filter(
                            n => n.nodeType === 3 && n.textContent.trim()
                        ).map(n => n.textContent.trim());
                        if (own.length) return clean(own.join(' '));
                        const heading = node.querySelector(':scope > label, :scope > legend, :scope > [class*="label" i]');
                        if (heading && !heading.contains(e)) {
                            const t = clean(heading.innerText);
                            if (t) return t;
                        }
                        // A sibling element rendered immediately before a
                        // container that holds this control, e.g.
                        // <div>Website</div><div><input/></div>
                        if (node.previousElementSibling) {
                            const sib = node.previousElementSibling;
                            if (!sib.querySelector('input,textarea,select,button') &&
                                sib.innerText && sib.innerText.trim().length < 200) {
                                const t = clean(sib.innerText);
                                if (t) return t;
                            }
                        }
                    }
                    return clean(e.getAttribute('placeholder')) || clean(e.getAttribute('name')) || '';
                }
            """)).strip()
        except Exception:
            return ""

    async def _option_own_label(self, el):
        """Text for a single radio/checkbox option — as opposed to
        _field_group_label(), which finds the label for the whole field/
        group. A bare <input type="radio"> has no text content of its own;
        the visible "Yes"/"No" text normally lives in an associated
        <label for="..."> or a wrapping <label>."""
        try:
            own = (await self._control_label(el)).strip()
            if own:
                return own
        except Exception:
            pass
        try:
            return re.sub(r"\s+", " ", await el.evaluate(r"""
                e => {
                    if (e.id) {
                        const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
                        if (l && l.innerText.trim()) return l.innerText.trim();
                    }
                    const wrap = e.closest('label');
                    if (wrap && wrap.innerText.trim()) return wrap.innerText.trim();
                    const sib = e.nextElementSibling;
                    if (sib && sib.innerText && sib.innerText.trim()) return sib.innerText.trim();
                    return '';
                }
            """)).strip()
        except Exception:
            return ""

    async def _has_existing_value(self, el):
        try:
            val = (await el.input_value()).strip()
            return bool(val)
        except Exception:
            pass
        try:
            txt = (await el.inner_text()).strip()
            return bool(txt)
        except Exception:
            return False

    async def _form_frames(self, page):
        """Return the main page plus child frames that may own SmartApply controls.

        Indeed SmartApply has used embedded application surfaces. The previous
        scanner only queried the top-level Page, so a perfectly visible input
        inside an iframe was invisible to form discovery and filling.
        """
        try:
            frames = list(page.frames)
            return frames or [page]
        except Exception:
            return [page]

    @staticmethod
    def _frame_index(page, frame):
        try:
            return list(page.frames).index(frame)
        except Exception:
            return 0

    async def _frame_controls(self, frame):
        """Return visible editable controls from one frame, including custom roles."""
        selectors = (
            f"input:visible{CHROME_EXCLUDE}, textarea:visible{CHROME_EXCLUDE}, "
            f"select:visible{CHROME_EXCLUDE}, [contenteditable='true']:visible{CHROME_EXCLUDE}, "
            f"[role='textbox']:visible{CHROME_EXCLUDE}, [role='combobox']:visible{CHROME_EXCLUDE}, "
            f"[role='radio']:visible{CHROME_EXCLUDE}, [role='checkbox']:visible{CHROME_EXCLUDE}"
        )
        try:
            return frame.locator(selectors)
        except Exception:
            return None

    async def _control_in_frames(self, page, selectors):
        """Yield (frame, element) for controls across page and child frames."""
        for frame in await self._form_frames(page):
            try:
                locator = frame.locator(selectors)
                for i in range(await locator.count()):
                    yield frame, locator.nth(i)
            except Exception:
                continue

    async def form_field_groups(self, page):
        """Discover every distinct answerable field currently visible on the
        screen, keyed by its own label — not by scanning page text for
        question-shaped sentences. Handles Indeed's combined multi-field
        SmartApply screens where several plain-labeled fields (text inputs,
        a Yes/No radio group, etc.) appear together on one page.
        """
        groups = []

        # Individual text-like controls: each one is its own field.
        try:
            text_like = page.locator(
                f"input:visible{CHROME_EXCLUDE}, textarea:visible{CHROME_EXCLUDE}, "
                f"[contenteditable='true']:visible{CHROME_EXCLUDE}"
            )
            for i in range(await text_like.count()):
                el = text_like.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    typ = (await el.get_attribute("type") or "").lower()
                    if typ in {"hidden", "submit", "button", "file", "image", "checkbox", "radio", "password"}:
                        continue
                    if await self._has_existing_value(el):
                        continue
                    label = await self._field_group_label(el)
                    if not label or len(label) > 200:
                        continue
                    groups.append({"kind": "text", "label": label, "options": []})
                except Exception:
                    continue
        except Exception:
            pass

        # Radio groups: collapse every option belonging to the same group
        # into a single field, keyed by the group's own label.
        try:
            radios = page.locator(
                f"input[type='radio']:visible{CHROME_EXCLUDE}, [role='radio']:visible{CHROME_EXCLUDE}"
            )
            seen_group_labels = set()
            group_options = {}
            group_order = []
            for i in range(await radios.count()):
                el = radios.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    name = (await el.get_attribute("name")) or ""
                    group_label = await self._field_group_label(el)
                    key = name or group_label
                    if not key:
                        continue
                    if key not in group_options:
                        group_options[key] = {"label": group_label, "options": [], "checked": False}
                        group_order.append(key)
                    opt_label = (await self._option_own_label(el)).strip()
                    if opt_label and opt_label not in group_options[key]["options"]:
                        group_options[key]["options"].append(opt_label)
                    try:
                        if await el.is_checked():
                            group_options[key]["checked"] = True
                    except Exception:
                        pass
                except Exception:
                    continue
            for key in group_order:
                g = group_options[key]
                if g["checked"] or not g["label"] or not g["options"]:
                    continue
                groups.append({"kind": "single_select", "label": g["label"], "options": g["options"]})
        except Exception:
            pass

        # <select> dropdowns.
        try:
            selects = page.locator(f"select:visible{CHROME_EXCLUDE}")
            for i in range(await selects.count()):
                el = selects.nth(i)
                try:
                    if not await el.is_visible() or await self._has_existing_value(el):
                        continue
                    label = await self._field_group_label(el)
                    if not label:
                        continue
                    opts = await el.evaluate(
                        "e => [...e.options].map(o => o.text.trim()).filter(Boolean)"
                    )
                    groups.append({"kind": "single_select", "label": label, "options": opts})
                except Exception:
                    continue
        except Exception:
            pass

        # Indeed SmartApply also renders dropdowns as custom ARIA comboboxes
        # (not native <select> elements). Treat these as real answerable fields.
        try:
            combos = page.locator(f"[role='combobox']:visible{CHROME_EXCLUDE}")
            empty_markers = {
                "", "select", "select an option", "choose",
                "choose an option", "please select", "select option",
            }
            for i in range(await combos.count()):
                el = combos.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    raw_value = ""
                    try:
                        raw_value = (await el.input_value()).strip()
                    except Exception:
                        pass
                    raw_text = re.sub(r"\s+", " ", (await el.inner_text()).strip())
                    aria_value = (await el.get_attribute("aria-label") or "").strip()
                    current = raw_value or raw_text
                    if current.lower() not in empty_markers:
                        if current or aria_value.lower() not in empty_markers:
                            continue
                    label = await self._field_group_label(el)
                    if not label or len(label) > 200:
                        continue
                    groups.append({"kind": "single_select", "label": label, "options": []})
                except Exception:
                    continue
        except Exception:
            pass

        # De-duplicate by fingerprinted label, and drop anything already answered.
        out, seen = [], set()
        for g in groups:
            fp = self.fingerprint(g["label"])
            if fp in seen or fp in self.answered:
                continue
            seen.add(fp)
            out.append(g)
        return out

    def _native_deterministic_profile_values(self):
        """Return verified profile values for native Indeed field filling.

        This mirrors the proven deterministic profile-routing data used by the
        supplied working Naukri/Indeed files: exact profile facts are resolved
        from the canonical profile before any model reasoning.  No value here is
        invented; missing sensitive facts such as DOB/age simply remain absent.
        """
        profile = getattr(self.engine.reasoner, "profile", {}) or {}
        contact = profile.get("contact", {}) or {}
        candidate = profile.get("candidate", {}) or {}
        comp = profile.get("compensation", {}) or {}
        online = profile.get("online_profiles", {}) or {}

        full_name = str(contact.get("name") or candidate.get("name") or "").strip()
        parts = full_name.split()

        return {
            "first_name": parts[0] if parts else "",
            "last_name": " ".join(parts[1:]) if len(parts) > 1 else "",
            "full_name": full_name,
            "email": str(contact.get("email") or "").strip(),
            "phone": str(contact.get("phone") or "").strip(),
            "city": str(contact.get("city") or "").strip(),
            "state": str(contact.get("state") or "").strip(),
            "country": str(contact.get("country") or "").strip(),
            "pin_code": str(contact.get("pin_code") or "").strip(),
            "nationality": str(contact.get("nationality") or "").strip(),
            "linkedin": str(online.get("linkedin") or "").strip(),
            "github": str(online.get("github") or "").strip(),
            # Proven fresher-safe value used by the supplied working form flow.
            "current_company": "N/A - Fresher / Graduate" if not candidate.get("currently_employed") else "",
            "current_ctc": str(comp.get("current_ctc") if comp.get("current_ctc") is not None else 0).strip(),
            "last_drawn_salary": str(comp.get("current_ctc") if comp.get("current_ctc") is not None else 0).strip(),
            "expected_ctc": str(comp.get("expected_ctc") or "").strip(),
            "total_experience": str(candidate.get("total_experience_years") if candidate.get("total_experience_years") is not None else 0).strip(),
            "notice_period": str(candidate.get("notice_period_days") if candidate.get("notice_period_days") is not None else 0).strip(),
            "graduation_year": str(candidate.get("graduation_year") or "").strip(),
            "cgpa": str(candidate.get("cgpa") or "").strip(),
            "class_10_percentage": str(candidate.get("class_10_percentage") or "").strip(),
            "class_12_percentage": str(candidate.get("class_12_percentage") or "").strip(),
            "be_percentage": str(candidate.get("be_percentage") or "").strip(),
            "current_designation": str(candidate.get("current_designation") or "").strip(),
            "degree": str((profile.get("education_details", {}) or {}).get("degree") or candidate.get("education") or "").strip(),
            "branch": str((profile.get("education_details", {}) or {}).get("branch") or "Electronics and Communication Engineering").strip(),
            "college": str((profile.get("education_details", {}) or {}).get("college") or "Vasavi College of Engineering").strip(),
            "junior_college": str((profile.get("education_details", {}) or {}).get("junior_college") or "Narayana Junior College").strip(),
            "junior_college_percentage": str((profile.get("education_details", {}) or {}).get("junior_college_percentage") or candidate.get("class_12_percentage") or "").strip(),
            "professional_summary": str(profile.get("professional_summary") or "").strip(),
            "certifications": "; ".join(str(x).strip() for x in (profile.get("certifications") or []) if str(x).strip()),
            "skills": ", ".join(str(x).strip() for x in (profile.get("skills") or []) if str(x).strip()),
            "work_authorization": "Yes" if candidate.get("authorized_to_work_in_india") is True else "No" if candidate.get("authorized_to_work_in_india") is False else "",
            "sponsorship": "Yes" if candidate.get("visa_sponsorship_required") is True else "No" if candidate.get("visa_sponsorship_required") is False else "",
            "relocation": "Yes" if profile.get("preferences", {}).get("willing_to_relocate") is True else "No" if profile.get("preferences", {}).get("willing_to_relocate") is False else "",
            "employment_bond": "Yes" if candidate.get("employment_bond_willing") is True else "No" if candidate.get("employment_bond_willing") is False else "",
        }

    @staticmethod
    def _native_profile_semantic(label, name="", field_id="", placeholder="", aria_label="",
                                 autocomplete="", input_type="", inputmode="", data_testid=""):
        """Map native Indeed profile-form controls to canonical profile semantics.

        Indeed has shipped several variants where the visible label is missing,
        generic, or rendered outside the control. In those cases the semantic
        identity is carried by stable attributes such as ``name``, ``id``,
        ``autocomplete``, ``type`` or ``inputmode``. Strong attribute signals
        are used only for contact/identity fields; narrative fields must still
        be label-driven so an incorrectly typed textarea cannot become email.
        """
        text = re.sub(r"\s+", " ", " ".join(
            [label or "", name or "", field_id or "", placeholder or "", aria_label or "",
             autocomplete or "", data_testid or ""]
        )).strip().lower()
        compact = re.sub(r"[^a-z0-9]+", "", text)
        itype = str(input_type or "").strip().lower()
        imode = str(inputmode or "").strip().lower()
        ac = str(autocomplete or "").strip().lower()

        # Strong browser/form metadata for contact fields. Do NOT infer email
        # from ``type=email`` alone: some third-party forms incorrectly label
        # narrative fields as email inputs. A telephone input is much less
        # ambiguous and is safe to map from type/inputmode.
        if ac in {"tel", "tel-national", "tel-local"} or itype == "tel" or imode == "tel":
            return "phone"
        if ac in {"email", "email-address"} and any(
            marker in text for marker in ("email", "e-mail", "mail address", "email id", "email address")
        ):
            return "email"
        if ac in {"given-name", "first-name"} and not any(x in text for x in ("email", "phone", "message", "experience")):
            return "first_name"
        if ac in {"family-name", "last-name"} and not any(x in text for x in ("email", "phone", "message", "experience")):
            return "last_name"
        if ac in {"postal-code", "zip-code"}:
            return "pin_code"
        if ac in {"address-level2", "city"}:
            return "city"
        if ac in {"address-level1", "state", "province"}:
            return "state"
        if ac in {"country", "country-name"}:
            return "country"

        rules = (
            (("first name",), "first_name"),
            (("last name", "surname", "family name"), "last_name"),
            (("full name", "candidate name", "applicant name", "legal name"), "full_name"),
            (("email", "e-mail"), "email"),
            (("phone", "mobile", "telephone", "contact number", "contact no", "phone no", "phone number", "mobile no", "mobile number"), "phone"),
            (("pin code", "pincode", "postal code", "zip code", "zipcode"), "pin_code"),
            (("current city", "present city", "city", "location"), "city"),
            (("state", "province"), "state"),
            (("country",), "country"),
            (("nationality", "citizenship"), "nationality"),
            (("linkedin",), "linkedin"),
            (("github",), "github"),
            (("current company", "current employer"), "current_company"),
            (("current/last drawn salary", "current last drawn salary", "last drawn salary", "current salary", "current ctc", "last salary"), "current_ctc"),
            (("expected annual salary", "expected salary", "expected ctc", "expected compensation", "annual salary"), "expected_ctc"),
            (("total experience", "total years of experience", "years of experience", "work experience", "relevant experience", "overall experience"), "total_experience"),
            (("notice period", "notice duration", "how many days notice"), "notice_period"),
            (("graduation year", "year of graduation", "passing year", "year did you graduate", "year did you pass out"), "graduation_year"),
            (("cgpa", "gpa"), "cgpa"),
            (("10th percentage", "ssc percentage", "10th percent"), "class_10_percentage"),
            (("12th percentage", "hsc percentage", "intermediate percentage", "12th percent"), "class_12_percentage"),
            (("b.e. percentage", "be percentage", "btech percentage", "btech percent", "bachelor percentage"), "be_percentage"),
            (("current designation", "current role", "current job title", "job title", "designation"), "current_designation"),
            (("degree", "highest qualification", "qualification"), "degree"),
            (("branch", "specialization", "major", "stream"), "branch"),
            (("college", "university", "school/college", "institution"), "college"),
            (("junior college", "intermediate college", "12th college"), "junior_college"),
            (("professional summary", "career summary", "profile summary"), "professional_summary"),
            (("certifications", "certification"), "certifications"),
            (("skills", "technical skills", "key skills"), "skills"),
            (("authorized to work", "legally authorized"), "work_authorization"),
            (("visa sponsorship", "sponsorship required", "require sponsorship", "need sponsorship"), "sponsorship"),
            (("willing to relocate", "willingness to relocate", "relocation"), "relocation"),
            (("employment bond", "service bond"), "employment_bond"),
        )
        for markers, semantic in rules:
            if any(marker in text for marker in markers):
                return semantic

        # Strong attribute-based fallbacks for forms whose visible label is short.
        if "phone" in compact or "mobile" in compact:
            return "phone"
        if "email" in compact:
            return "email"
        if "linkedin" in compact:
            return "linkedin"
        if "github" in compact:
            return "github"
        return None

    async def _native_deterministic_profile_field(self, page):
        """Find the next empty native Indeed control backed by a known profile fact."""
        values = self._native_deterministic_profile_values()
        for frame in await self._form_frames(page):
            try:
                controls = frame.locator(
                    f"[role='textbox']:visible{CHROME_EXCLUDE}, "
                    f"[role='combobox']:visible{CHROME_EXCLUDE}, "
                    f"input:visible{CHROME_EXCLUDE}, textarea:visible{CHROME_EXCLUDE}, "
                    f"select:visible{CHROME_EXCLUDE}, [contenteditable='true']:visible{CHROME_EXCLUDE}"
                )
                for i in range(await controls.count()):
                    el = controls.nth(i)
                    try:
                        if not await el.is_visible() or await self._has_existing_value(el):
                            continue
                        label = (await self._field_group_label(el)).strip()
                        if not label or len(label) > 200:
                            continue
                        fp = self.fingerprint(label)
                        if fp in self.answered:
                            continue
                        name = await el.get_attribute("name") or ""
                        field_id = await el.get_attribute("id") or ""
                        placeholder = await el.get_attribute("placeholder") or ""
                        aria = await el.get_attribute("aria-label") or ""
                        autocomplete = await el.get_attribute("autocomplete") or ""
                        input_type = await el.get_attribute("type") or ""
                        inputmode = await el.get_attribute("inputmode") or ""
                        data_testid = await el.get_attribute("data-testid") or ""
                        semantic = self._native_profile_semantic(
                            label, name, field_id, placeholder, aria, autocomplete,
                            input_type, inputmode, data_testid
                        )
                        if not semantic:
                            continue
                        value = values.get(semantic)
                        if value in (None, ""):
                            # Never guess unsupported sensitive fields (e.g. DOB/age).
                            continue
                        role = (await el.get_attribute("role") or "").lower()
                        tag = await el.evaluate("e => e.tagName.toLowerCase()")
                        kind = "single_select" if tag == "select" or role in {"combobox", "radio"} else "text"
                        options = []
                        if tag == "select":
                            options = await el.evaluate("e => [...e.options].map(o => o.text.trim()).filter(Boolean)")
                        return {
                            "kind": kind,
                            "label": label,
                            "options": options,
                            "frame_index": self._frame_index(page, frame),
                            "deterministic_value": value,
                            "deterministic_field": semantic,
                        }
                    except Exception:
                        continue
            except Exception:
                continue
        return None

    async def _deterministic_profile_diagnostics(self, page):
        """Print compact diagnostics when a native form exposes controls but no profile route."""
        try:
            samples = []
            for frame in await self._form_frames(page):
                controls = frame.locator(
                    f"input:visible{CHROME_EXCLUDE}, textarea:visible{CHROME_EXCLUDE}, "
                    f"select:visible{CHROME_EXCLUDE}, [contenteditable='true']:visible{CHROME_EXCLUDE}, "
                    f"[role='textbox']:visible{CHROME_EXCLUDE}, [role='combobox']:visible{CHROME_EXCLUDE}"
                )
                for i in range(min(await controls.count(), 60)):
                    el = controls.nth(i)
                    try:
                        if not await el.is_visible() or await self._has_existing_value(el):
                            continue
                        label = (await self._field_group_label(el)).strip()
                        attrs = {
                            "name": await el.get_attribute("name") or "",
                            "id": await el.get_attribute("id") or "",
                            "type": await el.get_attribute("type") or "",
                            "autocomplete": await el.get_attribute("autocomplete") or "",
                            "inputmode": await el.get_attribute("inputmode") or "",
                        }
                        samples.append((label, attrs))
                    except Exception:
                        continue
                if len(samples) >= 12:
                    break
            if samples:
                print(f"  NATIVE PROFILE DIAGNOSTICS: unresolved_controls={samples[:12]!r}")
        except Exception:
            pass

    async def _deterministic_form_field_fallback(self, page):
        """Recover known profile fields across all SmartApply frames."""
        deterministic_profile = await self._native_deterministic_profile_field(page)
        if deterministic_profile:
            return deterministic_profile

        for frame in await self._form_frames(page):
            try:
                controls = frame.locator(
                    f"[role='textbox']:visible{CHROME_EXCLUDE}, "
                    f"[role='combobox']:visible{CHROME_EXCLUDE}, "
                    f"input:visible{CHROME_EXCLUDE}, textarea:visible{CHROME_EXCLUDE}, "
                    f"select:visible{CHROME_EXCLUDE}, [contenteditable='true']:visible{CHROME_EXCLUDE}"
                )
                for i in range(await controls.count()):
                    el = controls.nth(i)
                    try:
                        if not await el.is_visible() or await self._has_existing_value(el):
                            continue
                        label = (await self._field_group_label(el)).strip()
                        if not label or len(label) > 200:
                            continue
                        fp = self.fingerprint(label)
                        if fp in self.answered:
                            continue
                        evidence = self.engine.evidence(label)
                        if evidence.startswith("deterministic"):
                            role = (await el.get_attribute("role") or "").lower()
                            tag = await el.evaluate("e => e.tagName.toLowerCase()")
                            kind = "single_select" if tag == "select" or role == "combobox" else "text"
                            options = []
                            if tag == "select":
                                options = await el.evaluate(
                                    "e => [...e.options].map(o => o.text.trim()).filter(Boolean)"
                                )
                            return {
                                "kind": kind,
                                "label": label,
                                "options": options,
                                "frame_index": self._frame_index(page, frame),
                            }
                    except Exception:
                        continue
            except Exception:
                continue
        return None

    async def next_unanswered_field(self, page):
        """Return the next field (dict with label/kind/options) that still
        needs an answer on the current screen, or None if there isn't one.
        """
        groups = await self.form_field_groups(page)
        return groups[0] if groups else None

    async def _visible_form_controls(self, page):
        try:
            return await page.evaluate("""() => {
                const visible = e => { const r=e.getBoundingClientRect(), s=getComputedStyle(e); return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none' && s.opacity!=='0'; };
                return [...document.querySelectorAll('input,textarea,select,button,[contenteditable="true"],[role="textbox"],[role="combobox"],[role="radio"],[role="checkbox"],[role="option"],label,[tabindex]')].filter(visible).map((e,i)=>({
                    i,tag:e.tagName.toLowerCase(),type:(e.getAttribute('type')||'').toLowerCase(),role:e.getAttribute('role')||'',
                    placeholder:e.getAttribute('placeholder')||'',aria:e.getAttribute('aria-label')||'',text:(e.innerText||e.textContent||'').trim().replace(/\\s+/g,' ').slice(0,200),
                    name:e.getAttribute('name')||'',value:e.value??'',checked:!!e.checked,disabled:!!e.disabled,editable:e.isContentEditable || !e.disabled,
                    parentText:(e.parentElement?.innerText||'').trim().replace(/\\s+/g,' ').slice(0,500)
                }));
            }""")
        except Exception:
            return []

    async def _control_is_relevant(self, el, question):
        try:
            meta = await el.evaluate("""e => ([e.parentElement?.innerText||'',e.getAttribute('aria-label')||'',e.getAttribute('placeholder')||'',e.labels?.[0]?.innerText||'',e.getAttribute('name')||''].join(' ')).toLowerCase()""")
        except Exception:
            return 0
        qwords = set(re.findall(r"[a-z0-9]+", (question or "").lower()))
        mwords = set(re.findall(r"[a-z0-9]+", meta))
        score = len(qwords & mwords)
        q = (question or "").lower()
        if "email" in q and "email" in meta: score += 20
        if "phone" in q and any(x in meta for x in ("phone", "mobile")): score += 20
        if "ctc" in q and any(x in meta for x in ("ctc", "salary", "compensation", "package")): score += 20
        if any(x in q for x in ("years", "experience")) and any(x in meta for x in ("experience", "years", "year")): score += 15
        return score

    async def _set_control_value(self, el, value):
        text = str(value)
        try:
            await el.scroll_into_view_if_needed()
            await el.click()
        except Exception:
            pass
        try:
            await el.fill(text)
        except Exception:
            try:
                await el.evaluate("""(e,v)=>{if(e.isContentEditable)e.textContent=v;else{const p=e instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;const setter=Object.getOwnPropertyDescriptor(p,'value')?.set;if(setter)setter.call(e,v);else e.value=v;}e.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:v}));e.dispatchEvent(new Event('change',{bubbles:true}));}""", text)
            except Exception:
                return False
        try:
            cur = (await el.input_value()).strip()
        except Exception:
            try: cur = (await el.inner_text()).strip()
            except Exception: cur = ""
        if cur == text:
            return True
        try:
            return float(cur.replace(",", "")) == float(text.replace(",", ""))
        except Exception:
            return False

    async def _fill_text_input(self, page, value, question=None):
        controls = []
        for sel in (s + CHROME_EXCLUDE for s in (
            "textarea:visible", "input:visible", "[contenteditable='true']:visible",
            "[role='textbox']:visible", "[role='combobox']:visible",
        )):
            try:
                loc = page.locator(sel)
                for i in range(await loc.count()-1, -1, -1):
                    el = loc.nth(i)
                    if await el.is_visible() and await el.is_editable():
                        typ = (await el.get_attribute("type") or "").lower()
                        if typ not in {"hidden", "submit", "button", "file", "image", "checkbox", "radio", "password"}:
                            controls.append(el)
            except Exception:
                pass
        scored = [(await self._control_is_relevant(el, question or ""), el) for el in controls]
        scored.sort(key=lambda x: x[0], reverse=True)
        for score, el in scored:
            if score < 1 and len(scored) > 1:
                continue
            if await self._set_control_value(el, value):
                return True
        return False

    async def _click_option(self, page, value, question=None, multi=False):
        target = re.sub(r"\s+", " ", str(value).strip()).lower()
        if not target:
            return False
        selectors = [
            s + CHROME_EXCLUDE for s in (
                "[role='radio']:visible", "[role='option']:visible", "[role='button']:visible", "button:visible",
                "label:visible", "li:visible", "input[type='radio']:visible", "input[type='checkbox']:visible",
            )
        ]
        candidates = []
        for sel in selectors:
            try:
                loc = page.locator(sel)
                for i in range(await loc.count()-1, -1, -1):
                    el = loc.nth(i)
                    if not await el.is_visible():
                        continue
                    txt = re.sub(r"\s+", " ", (await self._control_label(el)).strip()).lower()
                    if txt == target or txt.startswith(target + " ") or txt.startswith(target + ",") or target.startswith(txt + " "):
                        if question and await self._control_is_relevant(el, question) < 1:
                            continue
                        candidates.append(el)
            except Exception:
                pass
        for el in candidates:
            try:
                typ = (await el.get_attribute("type") or "").lower()
                await el.scroll_into_view_if_needed()
                if typ in ("radio", "checkbox"):
                    try: await el.check(force=True)
                    except Exception: await el.click(force=True)
                else:
                    await el.click(force=True)
                return True
            except Exception:
                try:
                    parent = el.locator("xpath=ancestor::*[self::button or @role='button' or @role='radio' or @role='option' or self::label][1]")
                    if await parent.count():
                        await parent.first.click(force=True)
                        return True
                except Exception:
                    pass

        # Generic page-wide fallback: the selector list above only matches
        # elements whose OWN text is the option label. Some Indeed controls
        # (e.g. a plain Yes/No pair rendered as styled <div>/<span> pairs
        # rather than <button>/<label>/role='radio') never surface through
        # those selectors at all, so an answer can be correctly chosen by
        # the engine and still never get filled. This mirrors the Naukri
        # agent's fallback: find the visible element whose exact text is
        # the value, then click it or its nearest clickable ancestor.
        try:
            loc = page.get_by_text(str(value).strip(), exact=True)
            for i in range(await loc.count() - 1, -1, -1):
                el = loc.nth(i)
                if not await el.is_visible():
                    continue
                try:
                    await el.click(force=True)
                    return True
                except Exception:
                    pass
                try:
                    parent = el.locator(
                        "xpath=ancestor::*[self::button or @role='button' or "
                        "@role='radio' or @role='option' or self::label][1]"
                    )
                    if await parent.count():
                        await parent.first.click(force=True)
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    async def _select_dropdown(self, page, value, question=None):
        try:
            sels = page.locator(f"select:visible{CHROME_EXCLUDE}")
            for i in range(await sels.count()-1, -1, -1):
                el = sels.nth(i)
                try:
                    await el.select_option(label=str(value)); return True
                except Exception:
                    try:
                        await el.select_option(str(value)); return True
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            combos = page.locator(f"[role='combobox']:visible{CHROME_EXCLUDE}")
            ranked = []
            for i in range(await combos.count()):
                el = combos.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    score = await self._control_is_relevant(el, question or "") if question else 0
                    ranked.append((score, i, el))
                except Exception:
                    continue
            ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
            targets = [str(value)]
            nq = re.sub(r"\s+", " ", (question or "").lower())
            if "notice period" in nq:
                targets.extend(["can join immediately", "immediate", "immediately", "0 days", "0"])
            seen_targets = set()
            deduped = []
            for target in targets:
                key = target.lower()
                if key not in seen_targets:
                    seen_targets.add(key)
                    deduped.append(target)
            for _, _, el in ranked:
                await el.scroll_into_view_if_needed()
                await el.click(force=True)
                await page.wait_for_timeout(150)
                for target in deduped:
                    if await self._click_option(page, target, question):
                        return True
                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
        except Exception:
            pass
        return False

    async def fill_answer_in_panel(self, page, value, kind, question=None, options=None):
        options = options or []
        if kind == "multi_select" and isinstance(value, (list, tuple)):
            clicked = sum(1 for item in value if await self._click_option(page, item, question, multi=True))
            return clicked > 0
        if any(re.sub(r"\s+", " ", str(o).strip()).lower() == str(value).strip().lower() for o in options):
            if await self._click_option(page, value, question):
                return True
        if kind in ("single_select", "yes_no") and await self._select_dropdown(page, value, question=question):
            return True
        if question and "notice period" in question.lower() and await self._select_dropdown(page, value, question=question):
            return True
        if kind == "yes_no":
            return await self._click_option(page, value, question) or await self._fill_text_input(page, value, question)
        if kind in ("number", "text"):
            return await self._fill_text_input(page, value, question) or await self._click_option(page, value, question)
        return await self._click_option(page, value, question) or await self._fill_text_input(page, value, question)

    async def verify_answer_in_panel(self, page, value, kind, question=None):
        if value is None:
            return False
        expected_values = [str(x).strip().lower() for x in value] if isinstance(value, (list, tuple)) else [str(value).strip().lower()]
        try:
            controls = page.locator("textarea:visible,input:visible,select:visible,[contenteditable='true']:visible,[role='textbox']:visible,[role='combobox']:visible")
            for i in range(await controls.count()):
                el = controls.nth(i)
                if not await el.is_visible():
                    continue
                try: val = (await el.input_value()).strip().lower()
                except Exception:
                    try: val = (await el.inner_text()).strip().lower()
                    except Exception: val = ""
                if val and any(v == val or v in val or val in v for v in expected_values):
                    return True
        except Exception:
            pass
        try:
            selected = page.locator(
                "[aria-selected='true']:visible,"
                "[aria-checked='true']:visible,"
                "[data-state='checked']:visible,"
                "[data-state='selected']:visible,"
                "input:checked"
            )
            selected_text = []
            for i in range(await selected.count()):
                el = selected.nth(i)
                vals = [await self._control_label(el)]
                for at in ("value", "data-value", "aria-label", "title"):
                    v = await el.get_attribute(at)
                    if v:
                        vals.append(v)
                # Include the nearest visible label/container text. Indeed's
                # custom radio controls often keep the actual checked input
                # hidden while the selected state lives on its wrapper.
                try:
                    ancestor_text = await el.evaluate(
                        """e => {
                            const a = e.closest('label,[role="radio"],[role="option"],[role="button"],button');
                            return a ? (a.innerText || a.textContent || '') : '';
                        }"""
                    )
                    if ancestor_text:
                        vals.append(ancestor_text)
                except Exception:
                    pass
                selected_text.extend(
                    re.sub(r"\s+", " ", str(x)).strip().lower()
                    for x in vals if x
                )
            joined = " ".join(selected_text)
            if any(v == x or v in x for v in expected_values for x in selected_text):
                return True
        except Exception:
            pass

        # Indeed sometimes uses a visible label/button with the selected state
        # on an ancestor rather than on the clickable element itself. Verify the
        # matched "Yes"/"No" option by inspecting that state explicitly.
        try:
            option_nodes = page.locator(
                "label:visible,[role='radio']:visible,[role='option']:visible,"
                "button:visible,[role='button']:visible"
            )
            for i in range(min(await option_nodes.count(), 300)):
                el = option_nodes.nth(i)
                try:
                    label = re.sub(r"\s+", " ", (await self._control_label(el)).strip()).lower()
                    if not any(
                        label == expected or label.startswith(expected + " ")
                        or expected.startswith(label + " ")
                        for expected in expected_values
                    ):
                        continue
                    state = await el.evaluate(
                        """e => {
                            const nodes = [e, ...e.querySelectorAll('*')];
                            for (const n of nodes) {
                                if (n.matches?.(':checked') ||
                                    n.getAttribute?.('aria-checked') === 'true' ||
                                    n.getAttribute?.('aria-selected') === 'true' ||
                                    ['checked','selected','active'].includes(
                                        (n.getAttribute?.('data-state') || '').toLowerCase()
                                    )) return true;
                            }
                            let a = e.parentElement;
                            for (let depth = 0; a && depth < 5; depth++, a = a.parentElement) {
                                if (a.getAttribute?.('aria-checked') === 'true' ||
                                    a.getAttribute?.('aria-selected') === 'true' ||
                                    ['checked','selected','active'].includes(
                                        (a.getAttribute?.('data-state') || '').toLowerCase()
                                    )) return true;
                            }
                            return false;
                        }"""
                    )
                    if state:
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        # Some Indeed controls advance immediately after the click.
        if question:
            try:
                qnow = await self.current_question(page)
                if qnow and self.fingerprint(qnow) != self.fingerprint(question):
                    return True
            except Exception:
                pass
        return False

    async def wait_for_question_change(self, page, old_question, timeout_ms=7000):
        old_fp = self.fingerprint(old_question)
        elapsed = 0
        while elapsed < timeout_ms:
            try:
                if await self.detect_blocker(page) or self.completed(await self.get_job_text(page)):
                    return True
                q = await self.current_question(page)
                if q and self.fingerprint(q) != old_fp:
                    return True
            except Exception:
                pass
            await page.wait_for_timeout(250)
            elapsed += 250
        return False

    async def click_continue(self, page):
        # Verification still runs and is logged, but no longer blocks
        # advancing - a mismatch here only means our own re-check couldn't
        # confirm the value (e.g. it reads state from a control shape it
        # doesn't recognise), not that the fill actually failed.
        expected = self._last_answer_value
        if expected is not None and not await self.verify_answer_in_panel(page, expected, "text"):
            print(f"  NOTE: could not re-confirm last answer on page (proceeding anyway): {expected}")
        # Indeed can expose an intermediate Apply / Apply again CTA inside the
        # application flow. Clicking it can reveal the next question rather than
        # submitting the application. Final submission remains handled separately
        # by submit(), which only accepts explicit Submit/Send Application labels.
        for name in ("Save", "Continue", "Next", "Review", "Done", "Apply again", "Apply Now", "Apply"):
            try:
                loc = page.get_by_role("button", name=re.compile(r"^" + re.escape(name) + r"$", re.I))
                for i in range(await loc.count()-1, -1, -1):
                    el = loc.nth(i)
                    if await el.is_visible() and not await el.is_disabled():
                        await el.scroll_into_view_if_needed(); await el.click(timeout=5000); return True
            except Exception:
                pass
        return False

    async def _has_question_progression_control(self, page):
        """Return True when a question-step progression CTA exists."""
        for name in (
            "Continue", "Next", "Review", "Save and continue",
            "Save & continue", "Done", "Finish",
        ):
            try:
                loc = page.get_by_role("button", name=re.compile(r"^" + re.escape(name) + r"$", re.I))
                count = min(await loc.count(), 20)
                for i in range(count - 1, -1, -1):
                    el = loc.nth(i)
                    if await el.is_visible() and not await el.is_disabled():
                        return True
            except Exception:
                pass
        return False

    async def _detect_native_route(self, page):
        """Classify the current native Indeed application state into one of two routes.

        Route 1: `direct_submit` — no unanswered application fields and a final
        Submit control is available (including the native review/resume state).

        Route 2: `questions_to_submit` — at least one real unanswered application
        field exists. The engine fills/validates each field, advances with Next/
        Continue/Review, and repeats until the final Submit appears.
        """
        try:
            fields = await self.form_field_groups(page)
            if fields:
                return "questions_to_submit"
        except Exception:
            # Uncertain field discovery must not trigger an automatic submission.
            pass

        try:
            if await self._has_final_submit_control(page):
                return "direct_submit"
        except Exception:
            pass

        try:
            if await self._has_question_progression_control(page):
                return "questions_to_submit"
        except Exception:
            pass

        return None

    async def submit(self, page):
        """Click Indeed's final Submit CTA using bounded exact labels only."""
        patterns = (
            r"^submit your application$",
            r"^submit application$",
            r"^send application$",
            r"^submit$",
        )
        selectors = (
            page.get_by_role("button", name=re.compile(r"(?:submit your application|submit application|send application|submit)$", re.I)),
            page.get_by_role("link", name=re.compile(r"(?:submit your application|submit application|send application|submit)$", re.I)),
            page.locator("button:visible, a:visible, [role='button']:visible, input[type='submit']:visible"),
        )
        for idx, loc in enumerate(selectors):
            try:
                count = min(await loc.count(), 80)
                for i in range(count - 1, -1, -1):
                    el = loc.nth(i)
                    if not await el.is_visible() or await el.is_disabled():
                        continue
                    if idx == 2:
                        label = re.sub(r"\s+", " ", await self._control_label(el)).strip()
                        if not any(re.fullmatch(pat, label, re.I) for pat in patterns):
                            continue
                    await el.scroll_into_view_if_needed()
                    await el.click(timeout=8000)
                    return True
            except Exception:
                pass
        return False

    async def _direct_submit_candidate(self, page):
        """Return True only when a final Submit is visible and no answerable fields remain.

        Some Indeed native applications are effectively one-click after the initial
        Apply: there are no employer questions/fields at all, only the final Submit
        CTA. The older control flow saw the Submit during readiness polling, then
        immediately tried to discover questions and could return ``no_form_field``.
        A direct submit is safe to consider only when the application form scanner
        finds no unanswered controls.
        """
        try:
            groups = await self.form_field_groups(page)
            if groups:
                return False
        except Exception:
            # If field discovery itself is uncertain, do not make an automatic
            # submission decision.
            return False

        try:
            return await self._has_final_submit_control(page)
        except Exception:
            return False

    async def _has_final_submit_control(self, page):
        """Check for a visible, enabled final-submit control without clicking it."""
        patterns = (
            r"^submit your application$",
            r"^submit application$",
            r"^send application$",
            r"^submit$",
        )
        locators = (
            page.get_by_role(
                "button",
                name=re.compile(r"(?:submit your application|submit application|send application|submit)$", re.I),
            ),
            page.get_by_role(
                "link",
                name=re.compile(r"(?:submit your application|submit application|send application|submit)$", re.I),
            ),
            page.locator(
                "button:visible, a:visible, [role='button']:visible, input[type='submit']:visible"
            ),
        )
        for idx, loc in enumerate(locators):
            try:
                count = min(await loc.count(), 80)
                for i in range(count - 1, -1, -1):
                    el = loc.nth(i)
                    if not await el.is_visible() or await el.is_disabled():
                        continue
                    if idx == 2:
                        label = re.sub(r"\s+", " ", await self._control_label(el)).strip()
                        if not any(re.fullmatch(pat, label, re.I) for pat in patterns):
                            continue
                    return True
            except Exception:
                continue
        return False

    async def _handle_direct_submit(self, page):
        """Submit a native application that has no unanswered questions/fields."""
        if not await self._direct_submit_candidate(page):
            return None

        print("  DIRECT SUBMIT: no unanswered application fields detected; checking final Submit CTA.")

        if self.dry_run:
            print("  DRY RUN: direct final Submit detected; intentionally NOT clicking.")
            return "ready_to_submit"

        if not await self.submit(page):
            print("  DIRECT SUBMIT: final Submit control disappeared or could not be clicked.")
            return None

        print("  DIRECT SUBMIT: final Submit clicked.")
        try:
            await page.wait_for_timeout(1200)
        except Exception:
            pass

        body = await self.get_job_text(page)
        if self.completed(body):
            print("  DIRECT SUBMIT CONFIRMED.")
            return "applied"

        print("  DIRECT SUBMIT CLICKED, but confirmation text was not detected; leaving application tab open.")
        return "submission_unconfirmed"

    @staticmethod
    def _is_indeed_redirect_shell(candidate_url):
        """Return True for Indeed's intermediate /beta/indeedapply/form/* shell.

        Indeed's native Apply flow can briefly land on a document containing only
        JavaScript that reads sessionStorage and redirects to the real application
        URL.  The shell must never be treated as the application target.
        """
        u = (candidate_url or "").lower().strip()
        return "indeed." in u and "/beta/indeedapply/form/" in u

    @staticmethod
    async def _read_indeed_redirect_destination(page):
        """Read/validate the destination used by Indeed's redirect-shell HTML.

        This mirrors the exact rules in Indeed's shell:
          storage key = shortUrl/<first path segment after /beta/indeedapply/>
          destination must be an absolute URL on the same origin.
        """
        try:
            return await page.evaluate(
                """() => {
                    const storageKey = 'shortUrl/' +
                        window.location.pathname
                            .replace('/beta/indeedapply/', '')
                            .split('/')[0];
                    const destinationUrl = sessionStorage.getItem(storageKey);
                    if (destinationUrl === null) {
                        return {ok: false, reason: 'missing', storageKey};
                    }

                    const anchor = document.createElement('a');
                    anchor.href = destinationUrl;

                    if (anchor.href !== destinationUrl) {
                        return {ok: false, reason: 'relative_or_noncanonical', storageKey};
                    }

                    if (
                        anchor.origin &&
                        window.location.origin &&
                        anchor.origin !== window.location.origin
                    ) {
                        return {ok: false, reason: 'cross_origin', storageKey};
                    }

                    let merged = anchor.href;
                    if (anchor.search === '') {
                        merged = merged + window.location.search;
                    } else if (window.location.search) {
                        merged =
                            merged +
                            window.location.search.replace('?', '&');
                    }

                    return {ok: true, storageKey, url: merged};
                }"""
            )
        except Exception as exc:
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def _is_indeed_native_target_url(candidate_url):
        """Recognize the concrete native SmartApply target produced by Indeed's shell."""
        u = (candidate_url or "").lower().strip()
        if not u or "smartapply.indeed.com" not in u:
            return False
        return any(token in u for token in (
            "/beta/indeedapply/applybyapplyablejobid",
            "/beta/indeedapply/form/review-module",
            "/beta/indeedapply/form/resume-selection-module",
            "/beta/indeedapply/form/application",
            "/beta/indeedapply/review-module",
            "/beta/indeedapply/resume-selection",
        ))

    async def _follow_indeed_redirect_shell(self, page):
        """Resolve Indeed's shell by reproducing its exact window.location navigation."""
        try:
            if page is None or page.is_closed():
                return False

            current_url = (page.url or "").strip()
            if not self._is_indeed_redirect_shell(current_url):
                return True

            info = await self._read_indeed_redirect_destination(page)
            if not info.get("ok"):
                print(
                    "  INDEED APPLY REDIRECT SHELL WAITING: "
                    f"reason={info.get('reason')} key={info.get('storageKey')}"
                )
                return False

            destination = str(info.get("url") or "").strip()
            print(f"  INDEED APPLY REDIRECT SHELL TARGET: {destination}")
            if not destination:
                return False

            # The supplied Indeed shell uses window.location = anchor.href.
            # Reproduce that browser-side navigation instead of page.goto(), which
            # can leave SmartApply bouncing on the intermediate shell.
            await page.evaluate("url => { window.location.href = url; }", destination)

            for _ in range(40):
                try:
                    current = (page.url or "").strip()
                except Exception:
                    current = ""
                if current and current != current_url:
                    if self._is_indeed_native_target_url(current) or not self._is_indeed_redirect_shell(current):
                        return True
                try:
                    await page.wait_for_timeout(250)
                except Exception:
                    await asyncio.sleep(0.25)

            try:
                current = (page.url or "").strip()
            except Exception:
                current = ""
            return bool(current and not self._is_indeed_redirect_shell(current))
        except Exception as exc:
            print(
                "  INDEED APPLY REDIRECT SHELL RESOLUTION FAILED: "
                f"{type(exc).__name__}: {exc}"
            )
            return False

    def _application_scopes(self, page):
        """Return the page plus child frames that can contain the native SmartApply UI."""
        scopes = [page]
        try:
            main_frame = getattr(page, "main_frame", None)
            for frame in getattr(page, "frames", []) or []:
                if main_frame is not None and frame is main_frame:
                    continue
                if frame not in scopes:
                    scopes.append(frame)
        except Exception:
            pass
        return scopes

    async def _wait_for_native_application_target(self, context, source_page, pages_before, source_url, timeout_ms=30000):
        """Wait for Indeed to actually open/transition into the native application surface.

        Do not let the search loop advance simply because the original job-page Apply
        control is still visible. Indeed can create the application tab a few seconds
        after the click, and that tab may briefly be about:blank while it initializes.
        """
        elapsed = 0
        poll_ms = 250
        last_candidate = None

        def _looks_like_application_url(candidate_url, original_url):
            u = (candidate_url or "").lower().strip()
            o = (original_url or "").lower().strip()
            if not u or u == "about:blank" or "indeed." not in u:
                return False
            if _is_indeed_redirect_shell(u):
                return False
            if u == o:
                return False
            # A SmartApply URL is a transition target, not proof that the
            # application UI has rendered.  The caller must keep waiting until
            # a concrete application surface is observable.
            return any(token in u for token in (
                "/apply", "/application", "applyjob", "jk="
            )) or u.rstrip("/") != o.rstrip("/")

        async def _has_application_surface(candidate, original_page=False):
            try:
                if candidate.is_closed():
                    return False
                if await self.detect_blocker(candidate):
                    return True

                # SmartApply commonly renders the real form inside one or more
                # child frames.  Looking only at candidate.locator(...) can therefore
                # miss a fully rendered application even though the user can see it.
                # Do not accept the ordinary job-page Apply CTA or generic job-page text as readiness.
                for scope in self._application_scopes(candidate):
                    try:
                        body = await self.get_job_text(scope)
                    except Exception:
                        body = ""

                    if re.search(
                        r"review your application|submit your application|cv options",
                        body or "", re.I,
                    ):
                        return True

                    # A concrete application form often starts with these profile
                    # controls before a question is available. Require a small
                    # cluster of form signals so generic job-page text does not count.
                    try:
                        visible_inputs = scope.locator(
                            "input:visible,textarea:visible,select:visible,[contenteditable='true']:visible"
                        )
                        input_count = min(await visible_inputs.count(), 40)
                    except Exception:
                        input_count = 0

                    if input_count >= 2 and re.search(
                        r"\b(full\s*name|first\s*name|email|phone|mobile|resume|cv)\b",
                        body or "", re.I,
                    ):
                        return True

                    try:
                        question = await self.current_question(scope)
                    except Exception:
                        question = None
                    if question:
                        return True

                    dialogs = scope.locator(
                        "[role='dialog']:visible, [aria-modal='true']:visible, "
                        "[class*='ia-ApplyForm']:visible, form:visible"
                    )
                    dcount = min(await dialogs.count(), 30)
                    for i in range(dcount):
                        dialog = dialogs.nth(i)
                        try:
                            text = re.sub(r"\s+", " ", await dialog.inner_text()).strip()
                        except Exception:
                            text = ""
                        if re.search(
                            r"resume|cv options|continue|next|review|submit|save and continue|"
                            r"phone|email|experience|education|salary|full name",
                            text, re.I,
                        ):
                            return True

                    controls = scope.locator(
                        "button:visible,a:visible,[role='button']:visible,"
                        "input:visible,textarea:visible,select:visible"
                    )
                    count = min(await controls.count(), 160)
                    for i in range(count):
                        el = controls.nth(i)
                        try:
                            label = re.sub(r"\s+", " ", await self._control_label(el)).strip()
                            if re.fullmatch(
                                r"(continue|next|review|submit|submit your application|"
                                r"save and continue|cv options)",
                                label, re.I,
                            ):
                                return True
                        except Exception:
                            continue
            except Exception:
                return False
            return False

        last_wait_log_url = None
        last_wait_log_elapsed = -3000


        while elapsed < timeout_ms:
            try:
                live_pages = [p for p in context.pages if not p.is_closed()]
                new_pages = [p for p in live_pages if p not in pages_before]

                # Prefer a newly-created Indeed tab, but wait until it has a real URL
                # or application DOM before treating it as the application target.
                for candidate in reversed(new_pages):
                    last_candidate = candidate
                    try:
                        candidate_url = (candidate.url or "").strip()
                    except Exception:
                        candidate_url = ""
                    if candidate_url.lower() == "about:blank" or not candidate_url:
                        continue
                    if "indeed." not in candidate_url.lower():
                        continue

                    # Indeed may first open a redirect shell such as
                    # /beta/indeedapply/form/<id>. That document immediately
                    # executes JavaScript using sessionStorage to redirect to the
                    # real application page. Do not classify the shell as the
                    # application target and do not search it for Resume/Edit.
                    if self._is_indeed_redirect_shell(candidate_url):
                        print(f"  INDEED APPLY REDIRECT SHELL DETECTED: {candidate_url}")
                        try:
                            await candidate.wait_for_load_state("domcontentloaded", timeout=1500)
                        except Exception:
                            pass
                        # Re-read after the shell's JS redirect; if the redirect
                        # script was not able to run (for example, because
                        # sessionStorage was not yet populated), resolve the same
                        # destination ourselves using the documented shell rules.
                        try:
                            candidate_url = (candidate.url or "").strip()
                        except Exception:
                            candidate_url = ""
                        if self._is_indeed_redirect_shell(candidate_url):
                            await self._follow_indeed_redirect_shell(candidate)
                            try:
                                candidate_url = (candidate.url or "").strip()
                            except Exception:
                                candidate_url = ""
                        if not candidate_url or self._is_indeed_redirect_shell(candidate_url):
                            # The destination can be known before SmartApply has
                            # finished rendering. Keep waiting on the same tab.
                            continue
                    else:
                        try:
                            await candidate.wait_for_load_state("domcontentloaded", timeout=1500)
                        except Exception:
                            pass
                        # URL may have changed during DOMContentLoaded/redirect.
                        try:
                            candidate_url = (candidate.url or "").strip()
                        except Exception:
                            candidate_url = ""
                        if not candidate_url or candidate_url.lower() == "about:blank":
                            continue

                    # Seeing the SmartApply/native target URL is not enough.
                    # Indeed can expose the final URL while the application UI is
                    # still booting. Keep polling this same tab until a concrete
                    # application surface is present.
                    native_target_observed = self._is_indeed_native_target_url(candidate_url)
                    surface_ready = await _has_application_surface(candidate)
                    if surface_ready:
                        if native_target_observed:
                            print(f"  APPLICATION TAB READY AFTER NATIVE TARGET: {candidate_url}")
                        else:
                            print(f"  APPLICATION TAB DETECTED AFTER WAIT: {candidate_url}")
                        return candidate
                    if native_target_observed:
                        if candidate_url != last_wait_log_url or elapsed - last_wait_log_elapsed >= 3000:
                            print(f"  NATIVE APPLICATION TARGET OBSERVED — WAITING FOR UI: {candidate_url}")
                            last_wait_log_url = candidate_url
                            last_wait_log_elapsed = elapsed
                        continue
                    if _looks_like_application_url(candidate_url, source_url):
                        if candidate_url != last_wait_log_url or elapsed - last_wait_log_elapsed >= 3000:
                            print(f"  APPLICATION URL OBSERVED — WAITING FOR UI: {candidate_url}")
                            last_wait_log_url = candidate_url
                            last_wait_log_elapsed = elapsed
                        continue

                # Some Indeed flows stay in the same tab and navigate/render the form.
                # However, when a *new* candidate tab exists, never fall back to the
                # original job page while that candidate is still booting. The original
                # job page can expose generic controls/text that look application-like.
                if not new_pages:
                    current_url = ""
                    try:
                        current_url = (source_page.url or "").strip()
                    except Exception:
                        pass
                    if self._is_indeed_redirect_shell(current_url):
                        # Same-tab variant of the intermediate Indeed redirect shell.
                        # Keep polling until the shell resolves using the exact browser
                        # navigation semantics from the supplied HTML.
                        await self._follow_indeed_redirect_shell(source_page)
                        try:
                            current_url = (source_page.url or "").strip()
                        except Exception:
                            current_url = ""
                    if self._is_indeed_native_target_url(current_url):
                        if current_url != last_wait_log_url or elapsed - last_wait_log_elapsed >= 3000:
                            print(f"  NATIVE APPLICATION TARGET RESOLVED — WAITING FOR UI: {current_url}")
                            last_wait_log_url = current_url
                            last_wait_log_elapsed = elapsed
                        if await _has_application_surface(source_page, original_page=True):
                            print(f"  NATIVE APPLICATION SURFACE DETECTED: {current_url}")
                            return source_page
                        # Keep waiting on the same tab; URL transition alone is not readiness.
                        continue
                    if await _has_application_surface(source_page, original_page=True):
                        print(f"  NATIVE APPLICATION SURFACE DETECTED: {current_url}")
                        return source_page

            except Exception:
                pass

            try:
                await source_page.wait_for_timeout(poll_ms)
            except Exception:
                try:
                    await asyncio.sleep(poll_ms / 1000)
                except Exception:
                    pass
            elapsed += poll_ms

        # Preserve a newly created application tab for inspection, but never run the
        # application engine against the original job page just because Apply remains.
        if last_candidate is not None and not last_candidate.is_closed():
            try:
                candidate_url = (last_candidate.url or "").strip()
                if candidate_url and candidate_url.lower() != "about:blank" and "indeed." in candidate_url.lower():
                    print(f"  APPLICATION TAB OPENED BUT NOT READY: {candidate_url}")
                    return None
            except Exception:
                pass

        print("  NATIVE APPLICATION TAB/STATE NOT DETECTED AFTER WAIT; leaving job tab open.")
        return None

    async def wait_for_application_ready(self, page, timeout_ms=20000):
        """Wait for Indeed's post-Apply transition to actually render.

        The first native Apply click can trigger a short navigation/modal/render
        phase before the application controls or first question exist. A fixed
        sleep is too brittle here, so poll for concrete application-state signals.
        This never treats a missing question during the loading window as failure.
        """
        if page is None or page.is_closed():
            return False

        elapsed = 0
        poll_ms = 300
        while elapsed < timeout_ms:
            try:
                if page.is_closed():
                    return False

                # Let a normal navigation finish if one is underway, but do not
                # wait on network-idle because Indeed may keep background requests open.
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=1500)
                except Exception:
                    pass

                if await self.detect_blocker(page):
                    print("  APPLICATION TRANSITION REACHED A SECURITY CHECK.")
                    return True

                body = await self.get_job_text(page)
                if self.completed(body):
                    return True

                # These are concrete application-state signals.
                if await self.current_question(page):
                    print("  APPLICATION UI READY: question detected.")
                    return True

                if re.search(r"review your application|submit your application", body or "", re.I):
                    print("  APPLICATION UI READY: review/submit state detected.")
                    return True

                try:
                    controls = page.locator(
                        "button:visible,a:visible,[role='button']:visible,"
                        "input[type='submit']:visible,input[type='button']:visible"
                    )
                    count = min(await controls.count(), 120)
                    for i in range(count):
                        label = re.sub(r"\s+", " ", await self._control_label(controls.nth(i))).strip()
                        if re.fullmatch(
                            r"(continue|next|review|apply|apply now|apply again|"
                            r"save|done|submit|submit your application|send application)",
                            label,
                            re.I,
                        ):
                            print(f"  APPLICATION UI READY: CTA detected ({label}).")
                            return True
                except Exception:
                    pass

                # Indeed's application form containers are also useful signals,
                # even when the first question has not rendered yet.
                try:
                    form_signal = page.locator(
                        "[role='dialog']:visible, "
                        "[class*='ia-ApplyForm']:visible, "
                        "form:visible, "
                        "[class*='apply']:visible"
                    )
                    if await form_signal.count():
                        for i in range(min(await form_signal.count(), 20)):
                            try:
                                if await form_signal.nth(i).is_visible():
                                    txt = (await form_signal.nth(i).inner_text()).strip()
                                    if txt:
                                        print("  APPLICATION UI READY: form/dialog rendered.")
                                        return True
                            except Exception:
                                pass
                except Exception:
                    pass

            except Exception:
                pass

            try:
                await page.wait_for_timeout(poll_ms)
            except Exception:
                return False
            elapsed += poll_ms

        print(f"  APPLICATION UI STILL LOADING after {timeout_ms/1000:.1f}s — entering application engine without skipping.")
        return True

    async def _click_exact_resume_edit(self, page):
        """Click Indeed's Resume-card Edit control across page and child frames.

        SmartApply can render the resume card inside an iframe while the top-level
        URL still remains the applybyapplyablejobid/review URL. Search every
        application scope and rank exact ``Edit`` controls by nearby Resume text.
        """
        candidates = []

        # Exact SmartApply review-module selector observed in the saved Indeed HTML:
        # <section data-testid="resumeSection"> ...
        #   <button aria-label="Edit resume">Edit</button>
        # This is more reliable than generic "Edit" text because Indeed renders
        # other Edit buttons (contact information, etc.) on the same page.
        exact_resume_edit_selector = 'section[data-testid="resumeSection"] button[aria-label="Edit resume"]'
        for frame in self._application_scopes(page):
            try:
                exact_loc = frame.locator(exact_resume_edit_selector)
                count = min(await exact_loc.count(), 10)
            except Exception:
                continue
            for i in range(count):
                el = exact_loc.nth(i)
                try:
                    if not await el.is_visible() or await el.is_disabled():
                        continue
                    candidates.append((1000, self._frame_index(page, frame), i, frame, el, {
                        "resumeText": "resume",
                        "text": "edit resume",
                        "top": 0,
                        "left": 0,
                        "exactSelector": True,
                    }))
                except Exception:
                    continue

        selectors = (
            "button:visible, a:visible, [role='button']:visible, "
            "[role='link']:visible, [role='menuitem']:visible, "
            "[role='tab']:visible, [onclick]:visible, [tabindex]:visible, "
            "[aria-label*='edit' i]:visible, [title*='edit' i]:visible, "
            "[data-testid*='edit' i]:visible, [data-test*='edit' i]:visible"
        )
        for frame in self._application_scopes(page):
            try:
                loc = frame.locator(selectors)
                count = min(await loc.count(), 180)
            except Exception:
                continue

            for i in range(count):
                el = loc.nth(i)
                try:
                    if not await el.is_visible() or await el.is_disabled():
                        continue
                    label = re.sub(r"\s+", " ", await self._control_label(el)).strip()
                    label_l = label.lower()
                    edit_like = (
                        label_l == "edit"
                        or bool(re.search(r"(?:^|\s)edit(?:\s|$)", label_l))
                        or "edit resume" in label_l
                        or "edit cv" in label_l
                    )
                    if not edit_like:
                        continue

                    details = await el.evaluate(r"""e => {
                        const clean = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
                        const rect = e.getBoundingClientRect();
                        let bestResumeDistance = 999999;
                        let resumeText = '';
                        let n = e.parentElement;
                        for (let depth = 0; n && depth < 10; depth++, n = n.parentElement) {
                            const t = clean(n.innerText || n.textContent || '');
                            if (t.includes('resume')) {
                                resumeText = t.slice(0, 1800);
                                const rr = n.getBoundingClientRect();
                                const dx = rect.left - rr.left;
                                const dy = rect.top - rr.bottom;
                                bestResumeDistance = Math.min(bestResumeDistance, Math.abs(dx) + Math.abs(dy));
                                break;
                            }
                        }
                        const text = clean(e.closest('section,article,li,div')?.innerText || '');
                        return {bestResumeDistance, resumeText, text, top: rect.top, left: rect.left};
                    }""")
                    score = 0
                    resume_context = details.get("resumeText") or ""
                    local_text = details.get("text") or ""
                    if "resume" in resume_context:
                        score += 100
                    if "resume" in local_text:
                        score += 30
                    distance = float(details.get("bestResumeDistance", 999999))
                    if distance < 2500:
                        score += max(0, int(40 - distance / 100))
                    if float(details.get("top", 0)) > 250:
                        score += 5
                    candidates.append((score, self._frame_index(page, frame), i, frame, el, details))
                except Exception:
                    continue

        candidates.sort(key=lambda x: (x[0], x[5].get("top", 0)), reverse=True)

        # SmartApply hydrates the Review/Resume card asynchronously after the
        # application question shell becomes visible. Do not fail immediately
        # when the Edit button is not present in the first DOM snapshot. Keep
        # polling page + child frames for the exact Resume edit control.
        if not candidates:
            for poll in range(80):  # 20s at 250ms
                try:
                    if page.is_closed():
                        return False
                except Exception:
                    pass
                for frame in self._application_scopes(page):
                    try:
                        exact_loc = frame.locator(exact_resume_edit_selector)
                        count = min(await exact_loc.count(), 10)
                    except Exception:
                        continue
                    for i in range(count):
                        el = exact_loc.nth(i)
                        try:
                            if not await el.is_visible() or await el.is_disabled():
                                continue
                            candidates.append((1000, self._frame_index(page, frame), i, frame, el, {
                                "resumeText": "resume",
                                "text": "edit resume",
                                "top": 0,
                                "left": 0,
                                "exactSelector": True,
                            }))
                        except Exception:
                            continue
                if candidates:
                    candidates.sort(key=lambda x: (x[0], x[5].get("top", 0)), reverse=True)
                    print(f"  INDEED RESUME: Resume -> Edit detected after wait (poll={poll})")
                    break
                await page.wait_for_timeout(250)

        for score, frame_idx, i, frame, el, details in candidates:
            try:
                await el.scroll_into_view_if_needed()
                try:
                    await el.click(timeout=8000)
                except Exception:
                    await el.click(timeout=5000, force=True)
                print(
                    f"  INDEED RESUME: clicked Resume -> Edit "
                    f"(score={score}, frame={frame_idx}, candidate={i})"
                )

                for _ in range(40):
                    try:
                        url = (page.url or "").lower()
                        if "resume-selection-module" in url:
                            return True
                        for scope in self._application_scopes(page):
                            hits = scope.get_by_text(re.compile(r"^CV options$", re.I))
                            for j in range(min(await hits.count(), 20)):
                                if await hits.nth(j).is_visible():
                                    return True
                    except Exception:
                        pass
                    await page.wait_for_timeout(250)
            except Exception:
                continue

        # Fallback: exact Edit text across every application scope.
        for frame in self._application_scopes(page):
            try:
                exact = frame.get_by_text(re.compile(r"^Edit$", re.I))
                count = min(await exact.count(), 40)
                for i in range(count - 1, -1, -1):
                    el = exact.nth(i)
                    if not await el.is_visible():
                        continue
                    await el.scroll_into_view_if_needed()
                    try:
                        await el.click(timeout=6000)
                    except Exception:
                        await el.click(timeout=4000, force=True)
                    print(f"  INDEED RESUME: clicked exact Edit text fallback (frame={self._frame_index(page, frame)})")
                    for _ in range(32):
                        try:
                            if "resume-selection-module" in (page.url or "").lower():
                                return True
                            for scope in self._application_scopes(page):
                                hits = scope.get_by_text(re.compile(r"^CV options$", re.I))
                                for j in range(min(await hits.count(), 20)):
                                    if await hits.nth(j).is_visible():
                                        return True
                        except Exception:
                            pass
                        await page.wait_for_timeout(250)
            except Exception:
                continue
        return False

    async def _click_cv_upload_option(self, page):
        """Open Indeed's CV-options toggle and reliably click its floating upload menu.

        Observed recordings show ``CV options`` is a toggle. Clicking it creates a
        floating/portal-style menu containing ``Upload a different file``. That menu
        may live in a different application frame, may not expose a standard ARIA
        role, and may briefly animate before becoming clickable.

        Order:
          1) Use an already-visible upload menu item if present.
          2) Find the visible CV-options toggle nearest the Resume card and click it.
          3) Re-scan page + every frame for the floating menu using several DOM
             strategies, including exact text/XPath and portal/popover selectors.
        """
        cv_pat = re.compile(r"^\s*CV\s+options\s*$", re.I)
        upload_pat = re.compile(r"Upload\s+a\s+different\s+file", re.I)
        upload_text = "Upload a different file"

        async def _candidate_visible(el):
            try:
                return bool(await el.is_visible()) and not bool(await el.is_disabled())
            except Exception:
                return False

        async def _upload_candidates(frame):
            """Yield strong candidates for the floating upload item.

            Playwright text/role locators are supplemented with exact XPath and
            popover/menu container selectors because Indeed's popup is a floating
            overlay rather than a normal descendant of the CV button.
            """
            locators = []
            try:
                locators.extend([
                    frame.get_by_role("menuitem", name=upload_pat),
                    frame.get_by_role("button", name=upload_pat),
                    frame.get_by_role("link", name=upload_pat),
                    frame.get_by_text(upload_pat, exact=False),
                    frame.get_by_text(upload_text, exact=False),
                    frame.locator(f"text={upload_text}"),
                    frame.locator(
                        "xpath=//*[normalize-space(.)='Upload a different file']"
                    ),
                ])
            except Exception:
                pass

            # Common floating-menu/popover implementations. Search inside these
            # containers as well as the document root.
            try:
                popovers = frame.locator(
                    "[role='menu']:visible, [role='listbox']:visible, "
                    "[popover]:visible, [data-radix-popper-content-wrapper]:visible, "
                    "[data-popper-placement]:visible, [data-floating-ui-portal]:visible, "
                    "[class*='popover']:visible, [class*='menu']:visible"
                )
                for i in range(min(await popovers.count(), 40)):
                    pop = popovers.nth(i)
                    try:
                        locators.extend([
                            pop.get_by_text(upload_pat, exact=False),
                            pop.get_by_text(upload_text, exact=False),
                            pop.locator("text=" + upload_text),
                        ])
                    except Exception:
                        continue
            except Exception:
                pass

            seen = set()
            for loc in locators:
                try:
                    count = min(await loc.count(), 100)
                except Exception:
                    continue
                for i in range(count):
                    try:
                        el = loc.nth(i)
                        if not await _candidate_visible(el):
                            continue
                        # Reject giant ancestor/body matches. Prefer the smallest
                        # exact-text clickable element.
                        meta = await el.evaluate("""e => {
                            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                            const r = e.getBoundingClientRect();
                            const txt = norm(e.innerText || e.textContent || '');
                            const tag = (e.tagName || '').toLowerCase();
                            return {text: txt, tag, area: r.width * r.height, w: r.width, h: r.height};
                        }""")
                        if upload_text.lower() not in meta.get("text", "").lower():
                            continue
                        key = (str(meta.get("tag")), round(float(meta.get("area", 0)), 2), i)
                        if key in seen:
                            continue
                        seen.add(key)
                        yield el
                    except Exception:
                        continue

        async def _find_upload(frame):
            async for el in _upload_candidates(frame):
                return el
            return None

        async def _visible_cv_candidates(frame):
            locators = []
            try:
                locators.extend([
                    frame.get_by_role("button", name=cv_pat),
                    frame.get_by_role("link", name=cv_pat),
                    frame.get_by_text(cv_pat, exact=True),
                ])
            except Exception:
                pass
            try:
                locators.append(frame.locator(
                    "[aria-label*='CV options' i]:visible, [title*='CV options' i]:visible, "
                    "[data-testid*='cv-options' i]:visible, [data-test*='cv-options' i]:visible"
                ))
            except Exception:
                pass

            out = []
            seen_handles = set()
            for loc in locators:
                try:
                    count = min(await loc.count(), 80)
                except Exception:
                    continue
                for i in range(count):
                    try:
                        el = loc.nth(i)
                        if not await _candidate_visible(el):
                            continue
                        meta = await el.evaluate("""e => {
                            const clean = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                            const r = e.getBoundingClientRect();
                            let n = e;
                            let resumeDistance = 999999;
                            let context = '';
                            for (let d = 0; n && d < 10; d++, n = n.parentElement) {
                                const t = clean(n.innerText || n.textContent || '');
                                if (t.includes('resume')) {
                                    context = t.slice(0, 1500);
                                    const rr = n.getBoundingClientRect();
                                    resumeDistance = Math.abs(r.left - rr.left) + Math.abs(r.top - rr.bottom);
                                    break;
                                }
                            }
                            return {
                                text: clean(e.innerText || e.textContent || e.getAttribute('aria-label') || ''),
                                role: clean(e.getAttribute('role') || ''),
                                expanded: e.getAttribute('aria-expanded'),
                                top: r.top,
                                left: r.left,
                                area: r.width * r.height,
                                resumeDistance,
                                context
                            };
                        }""")
                        if "cv options" not in (meta.get("text") or ""):
                            continue
                        # Prefer candidates visually associated with Resume and with
                        # a realistic button-sized box. A real toggle is usually not
                        # the largest ancestor returned by text locators.
                        score = 0
                        if "resume" in (meta.get("context") or ""):
                            score += 100
                        if meta.get("expanded") in ("false", "true"):
                            score += 25
                        if 20 <= float(meta.get("area", 0)) <= 200000:
                            score += 10
                        dist = float(meta.get("resumeDistance", 999999))
                        if dist < 2000:
                            score += max(0, int(30 - dist / 100))
                        out.append((score, el, meta))
                    except Exception:
                        continue
            out.sort(key=lambda x: (x[0], -float(x[2].get("top", 0))), reverse=True)
            return [x[1] for x in out]

        # 1) Upload popup may already be open.
        for frame in self._application_scopes(page):
            upload = await _find_upload(frame)
            if upload is not None:
                try:
                    await upload.scroll_into_view_if_needed()
                except Exception:
                    pass
                print("  INDEED RESUME: Upload a different file already visible; using it directly")
                return upload

        # 2) Find the correct visible CV-options toggle, prioritizing the one attached
        # to the Resume card rather than an unrelated duplicate/hidden clone.
        cv = None
        for poll in range(80):  # 20s at 250ms; SmartApply may hydrate this late.
            for frame in self._application_scopes(page):
                candidates = await _visible_cv_candidates(frame)
                if candidates:
                    cv = candidates[0]
                    break
            if cv is not None:
                if poll:
                    print(f"  INDEED RESUME: CV options toggle detected after wait (poll={poll})")
                break
            # The popup itself can also appear without the toggle being re-rendered.
            for frame in self._application_scopes(page):
                upload = await _find_upload(frame)
                if upload is not None:
                    try:
                        await upload.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    print(f"  INDEED RESUME: Upload a different file appeared while waiting for CV options (poll={poll})")
                    return upload
            await page.wait_for_timeout(250)

        if cv is None:
            print("  INDEED RESUME: visible CV options toggle was not found after wait")
            return None

        try:
            await cv.scroll_into_view_if_needed()
            # Use a real Playwright click; Indeed's popup needs the actual pointer
            # activation to open its floating menu and preserve user activation for
            # the later file-picker step.
            try:
                await cv.click(timeout=8000)
            except Exception:
                await cv.click(timeout=5000, force=True)
            print("  INDEED RESUME: clicked CV options toggle; waiting for floating upload menu")
        except Exception as exc:
            print(f"  INDEED RESUME: CV options click failed: {type(exc).__name__}: {exc}")
            return None

        # 3) Popup animation/rendering can take a few frames. Re-scan the *whole*
        # document and every child frame instead of assuming the menu is a child of
        # the button. Check immediately, then poll long enough for slow SmartApply UI.
        for poll in range(100):  # 25 seconds max at 250 ms
            for frame in self._application_scopes(page):
                upload = await _find_upload(frame)
                if upload is not None:
                    try:
                        await upload.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    print(f"  INDEED RESUME: Upload a different file detected after CV options (poll={poll})")
                    return upload
            try:
                await page.wait_for_timeout(250)
            except Exception:
                try:
                    await asyncio.sleep(0.25)
                except Exception:
                    pass

        print("  INDEED RESUME: floating 'Upload a different file' menu did not appear after CV options")
        return None

    async def _visible_resume_filename(self, page):
        """Return the exact resume filename currently rendered by Indeed.

        The native review page exposes this through data-testid=fileName and/or
        the Download resume anchor's ``download`` attribute.  Checking this
        exact identity prevents a stale previously-selected resume from being
        mistaken for the newly uploaded job-specific PDF.
        """
        selectors = (
            "section[data-testid='resumeSection'] [data-testid='fileName']",
            "section[data-testid='resumeSection'] [data-testid='fileMetadata'] [data-testid='fileName']",
            "section[data-testid='resumeSection'] a[data-testid='fileDownload'][download]",
            "section[data-testid='resumeSection'] a[download][href*='attachment']",
        )
        for scope in self._application_scopes(page):
            for selector in selectors:
                try:
                    loc = scope.locator(selector)
                    count = min(await loc.count(), 10)
                    for i in range(count):
                        el = loc.nth(i)
                        try:
                            if not await el.is_visible():
                                continue
                        except Exception:
                            continue
                        for attr in ("download", None):
                            try:
                                value = await el.get_attribute(attr) if attr else await el.inner_text()
                            except Exception:
                                value = None
                            value = re.sub(r"\s+", " ", str(value or "")).strip()
                            if value:
                                # Keep only the filename portion when Indeed returns a path.
                                value = value.replace("\\", "/").rsplit("/", 1)[-1]
                                if value.lower().endswith(".pdf"):
                                    return value
                except Exception:
                    continue
        return None

    async def _wait_for_exact_resume_filename(self, page, expected_name, timeout_ms=15000):
        """Wait until Indeed visibly reports exactly ``expected_name``."""
        expected = Path(expected_name).name.strip().lower()
        elapsed = 0
        while elapsed <= timeout_ms:
            try:
                actual = await self._visible_resume_filename(page)
                if actual and actual.strip().lower() == expected:
                    return actual
                if actual:
                    print(
                        f"  INDEED RESUME: visible resume filename mismatch: "
                        f"expected={Path(expected_name).name} actual={actual}"
                    )
            except Exception:
                pass
            try:
                await page.wait_for_timeout(250)
            except Exception:
                return None
            elapsed += 250
        return None

    async def _upload_tailored_resume_on_indeed_review(self, page):
        """Replace the selected Indeed resume using the exact observed native flow.

        Observed live sequence:
            Resume -> Edit
            -> CV options
            -> Upload a different file
            -> native Windows file chooser
            -> uploaded resume appears
            -> Continue
            -> review application surface

        The function does not mark the replacement complete until the post-upload
        UI is actually visible again.
        """
        resume = str(self.current_resume_path or "").strip()

        # A tailored build can legitimately be unavailable (for example when an
        # optional PDF verifier is missing).  The native Indeed flow still has
        # a proven upload path, so fall back to the configured master resume
        # instead of failing the whole application.
        if not resume or not Path(resume).is_file():
            try:
                fallback_resume = await self._find_resume()
            except Exception as exc:
                fallback_resume = None
                print(
                    f"  INDEED RESUME: master-resume lookup failed "
                    f"({type(exc).__name__}: {exc})"
                )
            if fallback_resume and Path(fallback_resume).is_file():
                resume = str(fallback_resume)
                print(
                    "  INDEED RESUME: tailored PDF unavailable; "
                    f"using master resume fallback {Path(resume).name}"
                )
            else:
                print(
                    "  INDEED RESUME: no usable tailored or master resume; "
                    "cannot replace resume."
                )
                return False

        if getattr(self, "_indeed_resume_replaced", False):
            return True

        print(f"  INDEED RESUME: targeted PDF = {Path(resume).name}")

        # Preserve the proven native Indeed sequence exactly:
        # Resume -> Edit -> CV options -> Upload a different file.
        # Use a job-specific upload filename so Indeed cannot treat the new
        # file as an indistinguishable re-selection of the existing resume.pdf.
        upload_resume = resume
        try:
            upload_dir = PLATFORM_DIR.parent.parent / "webapp" / "runtime" / "indeed_resume_uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            source = Path(resume)
            job_token = hashlib.sha256(f"{page.url}|{resume}".encode("utf-8")).hexdigest()[:10]
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
            upload_resume_path = upload_dir / f"Anuroop_Kudire_{source_sha}_{job_token}_tailored_resume.pdf"
            print(f"  INDEED RESUME: source PDF sha256={source_sha}")
            if source.resolve() != upload_resume_path.resolve():
                shutil.copy2(source, upload_resume_path)
            upload_resume = str(upload_resume_path)
            print(f"  INDEED RESUME: upload copy = {upload_resume_path.name}")
        except Exception as exc:
            print(f"  INDEED RESUME: upload-copy preparation failed ({type(exc).__name__}: {exc}); using source PDF.")

        # The observed native recordings have two valid entry states:
        #   A) Resume card -> Edit -> resume-selection-module
        #   B) already on resume-selection-module/resume-selection
        #      (e.g. after the Indeed redirect/review transition).
        # In state B, clicking Edit again is wrong; go directly to CV options.
        current_url = ""
        try:
            current_url = (page.url or "").lower()
        except Exception:
            pass

        # URL alone is not a reliable indicator of which controls are actually rendered.
        # First try to find/upload directly from the visible UI, then fall back to Edit.
        upload_control = await self._click_cv_upload_option(page)

        if upload_control is None:
            if not await self._click_exact_resume_edit(page):
                print("  INDEED RESUME: Resume -> Edit control was not found.")
                return False

            if await self.detect_blocker(page):
                if not await self.pause_for_human_verification(page, "application-resume-edit"):
                    return False

            upload_control = await self._click_cv_upload_option(page)

        if upload_control is None:
            print("  INDEED RESUME: 'Upload a different file' did not become visible after CV options.")
            return False

        if await self.detect_blocker(page):
            if not await self.pause_for_human_verification(page, "application-cv-options"):
                return False
            upload_control = await self._click_cv_upload_option(page)
            if upload_control is None:
                print("  INDEED RESUME: Upload option unavailable after human verification.")
                return False

        chooser_handled = False
        try:
            async with page.expect_file_chooser(timeout=10000) as chooser_info:
                try:
                    await upload_control.click(timeout=10000)
                except Exception:
                    await upload_control.click(timeout=5000, force=True)
            chooser = await chooser_info.value
            await chooser.set_files(upload_resume)
            chooser_handled = True
            print(
                f"  INDEED RESUME: native file chooser handled; selected {Path(upload_resume).name}"
            )
        except Exception as exc:
            print(
                f"  INDEED RESUME: native chooser unavailable "
                f"({type(exc).__name__}: {exc}); trying DOM file input."
            )

        if not chooser_handled:
            try:
                ranked = []
                for frame in self._application_scopes(page):
                    file_inputs = frame.locator("input[type='file']")
                    count = await file_inputs.count()
                    for i in range(count):
                        el = file_inputs.nth(i)
                        try:
                            label = re.sub(r"\s+", " ", await self._control_label(el)).lower()
                        except Exception:
                            label = ""
                        try:
                            visible = await el.is_visible()
                        except Exception:
                            visible = False
                        ranked.append((
                            ("resume" in label or "upload" in label),
                            visible,
                            self._frame_index(page, frame),
                            i,
                            el,
                        ))
                ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3]), reverse=True)
                for _, _, frame_idx, _, el in ranked:
                    try:
                        await el.set_input_files(upload_resume)
                        chooser_handled = True
                        print(
                            f"  INDEED RESUME: DOM file input handled; frame={frame_idx}; "
                            f"selected {Path(upload_resume).name}"
                        )
                        break
                    except Exception:
                        continue
            except Exception as exc:
                print(f"  INDEED RESUME: DOM upload failed: {type(exc).__name__}: {exc}")

        if not chooser_handled:
            return False

        if await self.detect_blocker(page):
            if not await self.pause_for_human_verification(page, "application-upload"):
                return False

        # Wait for Indeed to register the selected PDF. We accept several
        # observed confirmation signals rather than assuming a fixed delay.
        upload_confirmed = False
        target_name = Path(upload_resume).name.lower()
        for _ in range(80):
            try:
                if await self.detect_blocker(page):
                    if not await self.pause_for_human_verification(page, "application-upload-wait"):
                        return False
                body = re.sub(r"\s+", " ", await self.get_job_text(page)).lower()
                if target_name in body:
                    upload_confirmed = True
                    break

                # A selected file can be confirmed through a visible file input.
                # Confirm the selected file in the main document and in any
                # application iframe before relying on the Continue CTA.
                frames = [page] + [f for f in page.frames if f is not page.main_frame]
                for frame in frames:
                    try:
                        inputs = frame.locator("input[type='file']")
                        for i in range(await inputs.count()):
                            el = inputs.nth(i)
                            try:
                                names = await el.evaluate(
                                    """e => Array.from(e.files || []).map(f => f.name.toLowerCase())"""
                                )
                                if target_name in names:
                                    upload_confirmed = True
                                    break
                            except Exception:
                                pass
                        if upload_confirmed:
                            break
                    except Exception:
                        pass
                if upload_confirmed:
                    break

                # Indeed may render the accepted filename as text in the resume
                # card instead of exposing the file input after upload.
                try:
                    filename_hits = page.get_by_text(re.compile(re.escape(Path(upload_resume).name), re.I))
                    if await filename_hits.count():
                        for i in range(min(await filename_hits.count(), 20)):
                            if await filename_hits.nth(i).is_visible():
                                upload_confirmed = True
                                break
                except Exception:
                    pass
                if upload_confirmed:
                    break

            except Exception:
                pass
            await page.wait_for_timeout(250)

        if not upload_confirmed:
            print("  INDEED RESUME: upload was triggered but selection could not be verified.")
            return False

        # Now click the real Continue control and verify navigation back toward
        # the review/application surface.  Do not mark success before this point.
        continue_clicked = False
        try:
            for frame in self._application_scopes(page):
                cont = frame.get_by_role("button", name=re.compile(r"^Continue$", re.I))
                count = min(await cont.count(), 30)
                for i in range(count - 1, -1, -1):
                    el = cont.nth(i)
                    if await el.is_visible() and not await el.is_disabled():
                        await el.scroll_into_view_if_needed()
                        try:
                            await el.click(timeout=10000)
                        except Exception:
                            await el.click(timeout=5000, force=True)
                        continue_clicked = True
                        print(
                            f"  INDEED RESUME: clicked Continue after tailored PDF upload "
                            f"(frame={self._frame_index(page, frame)})"
                        )
                        break
                if continue_clicked:
                    break
        except Exception as exc:
            print(f"  INDEED RESUME: Continue lookup failed: {type(exc).__name__}: {exc}")

        if not continue_clicked:
            print("  INDEED RESUME: Continue was not clickable after verified upload.")
            return False

        if await self.detect_blocker(page):
            if not await self.pause_for_human_verification(page, "application-continue"):
                return False

        # Verify the flow moved on. The exact target may be /review-module,
        # "Review your application", or the final Submit checkpoint.
        for _ in range(60):
            try:
                if await self.detect_blocker(page):
                    if not await self.pause_for_human_verification(page, "application-post-continue"):
                        return False
                url = (page.url or "").lower()
                scopes = self._application_scopes(page)
                body_chunks = []
                for scope in scopes:
                    try:
                        body_chunks.append(re.sub(r"\s+", " ", await self.get_job_text(scope)).lower())
                    except Exception:
                        continue
                combined_body = " ".join(body_chunks)
                final_submit = False
                for scope in scopes:
                    try:
                        if await self._has_final_submit_control(scope):
                            final_submit = True
                            break
                    except Exception:
                        continue
                if (
                    "review-module" in url
                    or "review your application" in combined_body
                    or "submit your application" in combined_body
                    or final_submit
                ):
                    actual_name = await self._wait_for_exact_resume_filename(
                        page, Path(upload_resume).name, timeout_ms=2500
                    )
                    if actual_name:
                        self._indeed_resume_replaced = True
                        print(
                            "  INDEED RESUME: tailored resume replacement COMPLETE; "
                            f"verified filename={actual_name}"
                        )
                        return True
                    print(
                        "  INDEED RESUME: review state reached, but the visible resume "
                        f"is not the requested file {Path(upload_resume).name}; refusing to "
                        "mark replacement complete."
                    )
                    return False
            except Exception:
                pass
            await page.wait_for_timeout(250)

        print("  INDEED RESUME: upload/Continue completed but review destination was not confirmed.")
        return False

    async def _is_indeed_review_state(self, page, body=""):
        """Detect Indeed's native review/resume-selection state even when the
        page body does not contain the exact phrase "Review your application".

        In the observed native flow, Indeed can land on
        smartapply.indeed.com/.../review-module with no employer questions.
        That state still requires replacing the selected resume and then using
        the final Submit CTA.
        """
        try:
            url = (page.url or "").lower()
            if "smartapply.indeed.com" in url and any(token in url for token in (
                "/review-module", "/review", "review-module",
                "resume-selection-module", "resume-selection"
            )):
                return True
        except Exception:
            pass
        text = re.sub(r"\s+", " ", body or "").strip().lower()
        if re.search(r"review your application|resume.*edit|cv options|upload a different file", text, re.I):
            return True
        return False

    async def _page_is_closed_safe(self, page):
        if page is None:
            return True
        try:
            result = page.is_closed()
            if hasattr(result, "__await__"):
                result = await result
            return bool(result)
        except Exception:
            return False

    async def run_application(self, page, job_url):
        """Run one of exactly two native Indeed application routes.

        ROUTE 1 — direct_submit
          Apply with Indeed -> native review/direct-submit state -> (replace
          tailored resume when the review module exposes it) -> Submit -> verify.

        ROUTE 2 — questions_to_submit
          Apply with Indeed -> answer/verify each real application question or
          field -> Next/Continue/Review -> repeat -> final Submit -> verify.

        The two routes share the same final submission gate, and neither route
        closes the native application tab on an unresolved/partial state.
        """
        self.answered = set()
        self._last_answer_value = None
        self._indeed_resume_replaced = False
        no_progress = 0
        active_route = None

        for _ in range(160):
            if await self._page_is_closed_safe(page):
                return "application_page_closed"

            # Indeed can inject a human-verification challenge in the middle of
            # the native flow, including after Edit/CV options/upload. Pause at
            # the exact point where it appears, keep the application tab alive,
            # let the operator clear the challenge manually, require ENTER as the
            # explicit acknowledgement, then resume the same route.
            if await self.detect_blocker(page):
                print("  BLOCKED MID-FLOW: CAPTCHA/OTP/security verification detected.")
                cleared = await self.pause_for_human_verification(page, "application")
                if not cleared:
                    print("  HUMAN VERIFICATION NOT CLEARED — preserving application tab.")
                    return "human_intervention"
                no_progress = 0
                continue

            body = await self.get_job_text(page)
            if self.completed(body):
                return "applied" if not self.dry_run else "dry_run_complete"

            # --- Route 1: native review / direct submit ---------------------
            # The supplied Indeed recording lands on /review-module, then the
            # resume-selection module, and finally the Review your application
            # surface. This is still a direct-submit route when no unanswered
            # employer fields remain.
            if await self._is_indeed_review_state(page, body):
                if active_route != "direct_submit":
                    active_route = "direct_submit"
                    print("  NATIVE ROUTE: direct_submit")

                if not getattr(self, '_indeed_resume_replaced', False):
                    if not await self._upload_tailored_resume_on_indeed_review(page):
                        print("  INDEED RESUME: replacement failed; preserving native application tab.")
                        return "resume_upload_failed"
                    body = await self.get_job_text(page)

                if self.dry_run:
                    print("  DRY RUN: direct_submit route reached final review; Submit intentionally NOT clicked.")
                    return "ready_to_submit"

                if await self.submit(page):
                    await page.wait_for_timeout(1200)
                    if self.completed(await self.get_job_text(page)):
                        print("  NATIVE ROUTE: direct_submit CONFIRMED.")
                        return "applied"
                    print("  NATIVE ROUTE: direct_submit clicked but confirmation was not detected; preserving tab.")
                    return "submission_unconfirmed"

                # Some review surfaces expose a final Continue/Review CTA before
                # the final Submit appears. This is still the direct route because
                # there are no unanswered employer questions.
                if await self.click_continue(page):
                    no_progress = 0
                    await page.wait_for_timeout(700)
                    continue
                print("  NATIVE ROUTE: direct_submit reached review state but final Submit was not found.")
                return "submit_not_found"

            # --- Route detection -------------------------------------------
            route = await self._detect_native_route(page)
            # Once Route 2 has started, keep the state machine in
            # `questions_to_submit` through its final Submit checkpoint.
            # The final page may contain no fields and only a Submit button, but
            # that is still the terminal step of Route 2 rather than a third route.
            if active_route == "questions_to_submit" and route == "direct_submit":
                route = "questions_to_submit"
            if route:
                if route != active_route:
                    active_route = route
                    print(f"  NATIVE ROUTE: {active_route}")

            # Route 1 can also be a one-click final Submit without the review
            # module text being present. This is checked before question routing.
            if route == "direct_submit":
                direct_submit_status = await self._handle_direct_submit(page)
                if direct_submit_status is not None:
                    return direct_submit_status

            # Prefer field-based discovery: Indeed's SmartApply "Answer these
            # questions from the employer" screen often shows several plain
            # -labeled fields together (e.g. "LinkedIn Profile", "Name as
            # per Aadhar Card", "Website", a Yes/No consent field) rather
            # than one question-phrased sentence per screen. current_question()
            # only recognises question-shaped text, so it misses those.
            # form_field_groups() reads labels straight off each control,
            # regardless of phrasing, and already excludes anything answered.
            next_field = await self.next_unanswered_field(page)
            q = next_field["label"] if next_field else await self.current_question(page)
            if q:
                fp = self.fingerprint(q)
                if fp in self.answered:
                    if await self.click_continue(page):
                        no_progress = 0
                    else:
                        no_progress += 1
                    await page.wait_for_timeout(250)
                    if no_progress > 12:
                        return "no_progress"
                    continue
                options = next_field["options"] if next_field and next_field.get("options") else await self.visible_options(page)
                evidence = self.engine.evidence(q)
                print("  PROFILE EVIDENCE USED:")
                for line in evidence.splitlines()[:8]:
                    print("   ", line)
                value, field, kind = self.engine.answer(q, options)
                # Indeed salary forms may ask for the currency separately.
                # This project profile is India-based, so keep this field deterministic
                # instead of depending on an LLM to infer the currency from locale.
                nq = re.sub(r"\s+", " ", q.lower())
                if "currency" in nq and any(x in nq for x in ("salary", "ctc", "compensation", "pay")):
                    value, field, kind = "INR", "compensation.currency", "single_select"
                if kind is None and next_field:
                    kind = next_field.get("kind")
                if value is None:
                    print("  UNKNOWN / UNVERIFIED QUESTION:", q)
                    print("  Visible options:", options)
                    return "unknown_question"
                print("  Q:", q); print("  A:", value)
                self._last_answer_value = value
                if not await self.fill_answer_in_panel(page, value, kind, question=q, options=options):
                    print("  ANSWER COULD NOT BE SAFELY FILLED/VERIFIED")
                    return "fill_failed"
                # Verification still runs and is logged, but no longer
                # aborts the application on mismatch - fill_answer_in_panel()
                # already reporting success is trusted; this is just a
                # diagnostic signal now.
                if not await self.verify_answer_in_panel(page, value, kind, question=q):
                    print("  NOTE: could not re-confirm answer in the Indeed form (continuing anyway)")
                else:
                    print("  ANSWER VERIFIED IN INPUT/CONTROL")
                qa_value = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, tuple)) else str(value)
                qa(self.con, job_url, q, qa_value, field)
                self.answered.add(fp)
                # On a combined multi-field screen the page itself does not
                # change between fields, so wait_for_question_change() (which
                # waits for different page text) has nothing to detect here —
                # go straight to checking for another unanswered field first.
                if await self.next_unanswered_field(page):
                    no_progress = 0
                elif await self.wait_for_question_change(page, q, timeout_ms=4000):
                    no_progress = 0
                elif await self.click_continue(page):
                    no_progress = 0
                else:
                    no_progress += 1
            else:
                if await self.click_continue(page):
                    no_progress = 0
                    await page.wait_for_timeout(600)
                else:
                    no_progress += 1
                    await page.wait_for_timeout(300)

            # No unanswered fields. We may be between question pages, on a
            # question page with no input yet, or at a final submit checkpoint.
            if route == "questions_to_submit" or await self._has_question_progression_control(page):
                active_route = "questions_to_submit"

                if await self._has_final_submit_control(page):
                    if self.dry_run:
                        return "ready_to_submit"
                    if await self.submit(page):
                        await page.wait_for_timeout(1200)
                        if self.completed(await self.get_job_text(page)):
                            print("  NATIVE ROUTE: questions_to_submit CONFIRMED at final Submit.")
                            return "applied"
                        return "submission_unconfirmed"
                    return "submit_not_found"

                if await self.click_continue(page):
                    no_progress = 0
                    await page.wait_for_timeout(700)
                    continue

            # Final direct-submit checkpoint. This is deliberately after field
            # discovery so a page containing a real unanswered question can never
            # be mistaken for a one-click submission route.
            direct_submit_status = await self._handle_direct_submit(page)
            if direct_submit_status is not None:
                active_route = "direct_submit"
                print("  NATIVE ROUTE: direct_submit")
                return direct_submit_status

            no_progress += 1
            await page.wait_for_timeout(300)
            if no_progress > 8:
                # Native application has been opened and remains usable; never
                # close it from this engine merely because route detection stalled.
                return "native_flow_stalled"

        return "timeout"

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
        """Extract the employer name from the current Indeed job page.

        Prefer explicit employer/company attributes and known Indeed containers;
        never infer a company name from arbitrary body text.
        """
        selectors = (
            "[data-company-name]",
            "[data-testid='inlineHeader-companyName']",
            "[data-testid='company-name']",
            ".jobsearch-InlineCompanyRating-companyHeader",
            ".jobsearch-CompanyInfoWithoutHeaderImage-companyInfo",
            ".jobsearch-JobInfoHeader-companyName",
            "a[data-tn-element='companyName']",
            "[class*='companyName']",
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
        # Many current Indeed job pages expose the employer in JobPosting JSON-LD.
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
            if not await self.is_indeed_url(page):
                self.external_skipped += 1
                status = "external_skipped"
                print(f"  SKIPPED EXTERNAL DESTINATION: {page.url}")
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
                    title=title, jd_text=body, platform="indeed", job_url=url, company=company
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
                print("  MATCHED, but no native Indeed Apply button found. Leaving tab open; moving to next job.")
                return status

            # DRY_RUN blocks only final submission.  Clicking native Apply,
            # answering fields, and advancing intermediate steps are required
            # to exercise the real question → answer → fill → verify loop.
            if self.dry_run:
                print("  DRY RUN: native Apply and form filling are allowed; final Submit remains blocked.")

            # Snapshot tabs BEFORE Apply so a newly opened Indeed application tab
            # can be identified reliably after the click.
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
            print(f"  *** APPLY WITH INDEED CLICKED ({self.direct_applications}/{self.target_direct_applications}) ***")

            # IMPORTANT: the new Indeed application tab can appear AFTER a short
            # delay. Never run the form engine against the original job page while
            # it still shows the same job-page Apply CTA. Wait for a real native
            # application target first.
            application_page = await self._wait_for_native_application_target(
                context, page, pages_before, url, timeout_ms=60000
            )
            if application_page is None:
                status = "application_transition_timeout"
                print("  NATIVE APPLICATION DID NOT OPEN/RENDER IN TIME — leaving tab open; moving to next job.")
                return status

            # Only now wait for the application UI to become internally ready.
            await self.wait_for_application_ready(
                application_page, timeout_ms=20000
            )

            if await self.detect_blocker(application_page):
                if not await self.pause_for_human_verification(application_page, "application"):
                    status = "blocked"
                    return status

            print("  APPLICATION FORM ENGINE: scanning fields/questions...")
            # Indeed may require an intermediate "Apply again"/"Apply" click
            # before the next question becomes visible. run_application() handles
            # those intermediate CTAs through click_continue(), while explicit
            # final Submit remains separately gated.
            application_status = await self.run_application(application_page, url)
            # Propagate the real application state to the outer lifecycle.
            # Without this assignment, status remains "error", so finally()
            # treats a legitimate application-form result such as
            # answer_not_verified/unknown_question as disposable and may close
            # the application tab.
            status = application_status
            print(f"  APPLICATION RESULT: {application_status}")
            return application_status

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

    async def run_search(self, context, search_url):
        # Keep one dedicated search tab. Job tabs can remain open without stealing
        # the navigation tab used for pagination/role changes.
        if self.search_page is None or self.search_page.is_closed():
            live = [p for p in context.pages if not p.is_closed()]
            self.search_page = live[-1] if live else await asyncio.wait_for(context.new_page(), timeout=15)
        page = self.search_page
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
