import re
import os
from pathlib import Path

# IMPORTANT: attach-only mode. Never create Playwright/Chromium when using an existing Chrome.
async def connect_to_real_chrome_only(playwright, cdp_url):
    try:
        browser = await asyncio.wait_for(
            playwright.chromium.connect_over_cdp(cdp_url), timeout=15
        )
    except asyncio.TimeoutError as e:
        raise RuntimeError(f"Timed out connecting to Chrome CDP at {cdp_url}.") from e
    except Exception as e:
        raise RuntimeError(
            f"Could not attach to the existing Chrome at {cdp_url}. "
            "Start your REAL Google Chrome with --remote-debugging-port=9222, "
            "then run the agent. The agent will NOT launch Chromium/Chrome for Testing." 
        ) from e
    return browser

import asyncio, os, re, sys, hashlib, json
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from qa_engine import AnswerEngine
from storage import db, seen, app, qa
from jd_matcher import JDMatcher
from src.application.common.company_website_agent import CompanyWebsiteAgent

BASE = "https://www.naukri.com"

# Keyword -> profile-field rules used to fill unknown third-party/company
# career-site forms. Order matters: more specific patterns are checked
# before generic ones (e.g. "first name" before a bare "name" match).
EXTERNAL_FIELD_RULES = [
    (["first name"], "first_name"),
    (["last name", "surname", "family name"], "last_name"),
    (["full name", "your name", "candidate name", "applicant name", "legal name"], "full_name"),
    (["email"], "email"),
    (["phone", "mobile", "contact number", "contact no", "contactno", "phone no", "phone number", "mobile no", "mobile number"], "phone"),
    (["pin code", "zip code", "postal code", "zipcode"], "pin_code"),
    (["city"], "city"),
    (["state", "province"], "state"),
    (["country"], "country"),
    (["current company", "current employer"], "current_company"),
    (["notice period"], "notice_period"),
    (["expected ctc", "expected salary", "expected compensation"], "expected_ctc"),
    (["current ctc", "current salary"], "current_ctc"),
    (["total experience", "years of experience", "work experience", "relevant experience"], "total_experience"),
    (["linkedin"], "linkedin"),
]

class NaukriAgent:


    def fingerprint(self, url, title=""):
        """Stable job identity used for deduplication."""
        import hashlib
        key = (url or "").strip().lower()
        if key:
            return hashlib.sha256(key.encode("utf-8")).hexdigest()
        return hashlib.sha256((title or "").strip().lower().encode("utf-8")).hexdigest()


    def completed(self, body):
        """Only a confirmed Naukri submission counts as application success."""
        text=(body or "").lower()
        return any(x in text for x in (
            "you have successfully applied to",
            "successfully applied to",
            "application submitted successfully",
        ))

    def application_incomplete(self, body):
        """Detect Naukri's explicit incomplete-mandatory-information state.

        This is a stop-point, not a failure that should trigger more clicks.
        The current application tab is deliberately preserved so the user can
        inspect/fill the remaining information manually.
        """
        text = re.sub(r"\s+", " ", body or "").lower()
        return any(phrase in text for phrase in (
            "your application was not accepted due to incomplete information",
            "application was not accepted due to incomplete information",
            "please answer all mandatory questions when reapplying",
        ))

    def __init__(self):
        self.engine = AnswerEngine()
        self.con = db()
        self.dry_run = True  # Intentionally never submit; leave native application tab open and move to next job.
        self.max_jobs = int(os.getenv("MAX_JOBS", "3"))
        cfg_path = os.path.join(os.path.dirname(__file__), "role_config.json")
        try:
            cfg = json.load(open(cfg_path, encoding="utf-8"))
        except Exception:
            cfg = {"target_native_applications": self.max_jobs, "max_total_candidates": 100}
        self.cfg = cfg
        self.target_native_applications = int(cfg.get("target_native_applications", self.max_jobs))
        self.max_total_candidates = int(cfg.get("max_total_candidates", 100))
        self.native_jobs_found = 0
        self.external_jobs_skipped = 0
        self.external_jobs_filled = 0
        self.external_jobs_errored = 0
        self.low_match_skipped = 0
        self.naukri_apply_errors = 0
        self.seen_urls = set()
        self.answered = set()
        self.last_question = None
        self.matcher = JDMatcher(os.path.dirname(__file__))
        self.current_resume_path = None


    @staticmethod
    def _clean_company_candidate(value):
        value = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n-|•")
        if not value or len(value) > 160:
            return ""
        lowered = value.lower()
        blocked = {"naukri", "jobs", "apply", "apply now", "login", "register", "save", "share", "similar jobs"}
        if lowered in blocked:
            return ""
        return value

    async def _extract_company_name(self, page, title_hint="") -> str:
        """Extract employer deterministically from Naukri job-page metadata/UI."""
        selectors = (
            "[data-company-name]",
            "[data-testid*='company' i]",
            "[itemprop='hiringOrganization'] [itemprop='name']",
            "a[href*='/company/']:visible",
            "a[class*='comp-name']:visible",
            "a[class*='company']:visible",
            "div[class*='comp-name']:visible",
            "span[class*='comp-name']:visible",
            "div[class*='company']:visible",
            "span[class*='company']:visible",
        )
        for sel in selectors:
            try:
                loc = page.locator(sel)
                count = min(await loc.count(), 12)
                for i in range(count):
                    candidate = self._clean_company_candidate(await loc.nth(i).inner_text(timeout=1200))
                    if candidate:
                        return candidate
            except Exception:
                continue

        # Naukri and ATS-backed pages frequently expose JobPosting JSON-LD.
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
                        candidate = self._clean_company_candidate(org.get("name"))
                        if candidate:
                            return candidate
        except Exception:
            pass

        # Search structured microdata directly.
        try:
            loc = page.locator("[itemprop='hiringOrganization'] [itemprop='name'], [itemprop='hiringOrganization']")
            for i in range(min(await loc.count(), 8)):
                candidate = self._clean_company_candidate(await loc.nth(i).inner_text(timeout=1000))
                if candidate:
                    return candidate
        except Exception:
            pass

        # Naukri document titles commonly follow: Role - Location - Company - X to Y years...
        title = self._clean_company_candidate(title_hint)
        if title and title.lower() not in {"naukri", "jobs"}:
            parts = [p.strip() for p in re.split(r"\s+-\s+", title) if p.strip()]
            if len(parts) >= 3:
                experience_index = next((i for i, part in enumerate(parts) if re.search(r"\b\d+\s*(?:to|-|–)\s*\d+\s*(?:years?|yrs?)\b", part, re.I)), None)
                if experience_index is not None and experience_index >= 2:
                    candidate = self._clean_company_candidate(parts[experience_index - 1])
                    if candidate:
                        return candidate
                # Some Naukri titles end with just Location - Company.
                if len(parts) >= 3:
                    candidate = self._clean_company_candidate(parts[-1])
                    if candidate and not re.search(r"\b(years?|yrs?)\b", candidate, re.I):
                        return candidate
        return ""

    async def is_logged_in(self, page):
        try:
            body = (await page.locator("body").inner_text()).lower()
            if any(x in body for x in [
                "login / register", "login/register", "sign in", "register now"
            ]):
                return False

            signals = [
                "my naukri", "profile", "applications", "my jobs",
                "view profile", "logout", "sign out"
            ]
            if any(x in body for x in signals):
                return True

            for sel in [
                "[class*='profile']:visible",
                "[class*='avatar']:visible",
                "[aria-label*='profile' i]:visible"
            ]:
                try:
                    if await page.locator(sel).count():
                        return True
                except:
                    pass
        except:
            pass
        return False

    async def collect_job_urls(self, page):
        """Collect Naukri job URLs without relying on a fragile card selector."""
        found = set()

        # Give the SPA several chances to render its result list.
        for delay in (1000, 1800, 2500):
            try:
                await page.wait_for_timeout(delay)
            except Exception:
                break

            # 1. Rendered anchors.
            try:
                items = await page.locator("a[href]").evaluate_all(
                    """els => els.map(a => ({
                        href: a.href || "",
                        dataUrl: a.getAttribute("data-url") || "",
                        text: (a.innerText || a.textContent || "").trim()
                    }))"""
                )
            except Exception:
                items = []

            for item in items:
                for raw in (
                    item.get("href", ""),
                    item.get("dataUrl", ""),
                ):
                    if not raw:
                        continue
                    if "naukri.com" not in raw.lower():
                        continue
                    if "/job-listings-" in raw.lower() or "/job/" in raw.lower():
                        clean = raw.split("#", 1)[0].split("?", 1)[0]
                        found.add(clean)

            if found:
                break

            # Trigger lazy loading.
            try:
                await page.mouse.wheel(0, 1400)
            except Exception:
                pass

        # 2. HTML fallback for links not exposed by the rendered locator.
        if not found:
            try:
                html = await page.content()
                for raw in re.findall(
                    r"https?://(?:www\.)?naukri\.com/[^\"'<>\s]+",
                    html,
                    flags=re.I,
                ):
                    raw = raw.replace("\\/", "/").rstrip("),;")
                    low = raw.lower()
                    if "/job-listings-" in low or "/job/" in low:
                        found.add(raw.split("#", 1)[0].split("?", 1)[0])
            except Exception:
                pass

        # 3. Diagnostic instead of silently cycling roles.
        if not found:
            try:
                print(f"  SEARCH PAGE URL: {page.url}")
                print(f"  SEARCH PAGE TITLE: {(await page.title()).strip()[:120]}")
                body = " ".join(
                    (await page.locator("body").inner_text(timeout=5000)).split()
                )
                print(f"  SEARCH PAGE TEXT: {body[:700]}")
            except Exception:
                pass

        if not found:
            print("  No job URLs found; continuing to next role without applying.")
        return list(found)


    async def _filter_applied_search_urls(self, page, urls):
        """Filter explicit Applied cards before opening job tabs.

        Naukri's result markup varies. Find the smallest ancestor containing
        exactly one wanted job link and inspect the whole rendered card,
        including short aria/title/status badges that may sit beside the link.
        """
        if not urls:
            return []

        wanted = [u.split("#", 1)[0].split("?", 1)[0].rstrip("/") for u in urls]
        wanted_set = set(wanted)
        rows = []
        try:
            rows = await asyncio.wait_for(
                page.locator("a[href]").evaluate_all(
                    """(els, wanted) => {
                        const wantedSet = new Set(wanted);
                        const norm = u => (u || '').split('#')[0].split('?')[0].replace(/\\/$/, '');
                        const markerText = e => {
                            if (!e) return '';
                            const parts = [e.innerText || '', e.textContent || ''];
                            for (const a of ['aria-label','title','data-state','data-status','data-apply-status']) {
                                parts.push(e.getAttribute(a) || '');
                            }
                            return parts.join(' ');
                        };
                        const countWanted = root => [...root.querySelectorAll('a[href]')]
                            .reduce((n, x) => n + (wantedSet.has(norm(x.href || x.getAttribute('href'))) ? 1 : 0), 0);
                        return els.map(a => {
                            const href = norm(a.href || a.getAttribute('href'));
                            if (!wantedSet.has(href)) return null;
                            let best = a;
                            let n = a.parentElement;
                            for (let depth = 0; n && depth < 15; depth++, n = n.parentElement) {
                                const count = countWanted(n);
                                if (count === 1) best = n;
                                if (n.matches('article,li') || /job.?tuple|srp.?job|list.?item|job.?card|tuple/i.test(String(n.className || ''))) {
                                    if (count === 1) best = n;
                                    break;
                                }
                            }
                            const descendants = [best, ...best.querySelectorAll('*')].slice(0, 300);
                            return {href, text: descendants.map(markerText).join(' ')};
                        }).filter(Boolean);
                    }""",
                    wanted,
                ),
                timeout=6.0,
            )
        except Exception:
            rows = []

        applied = set()
        marker_re = re.compile(
            r"(?<![a-z])(?:already\s+applied|application\s+submitted|"
            r"you\s+have\s+applied|applied(?:\s+for)?)(?![a-z])",
            re.I,
        )
        for row in rows:
            href = str(row.get("href") or "").rstrip("/")
            if href not in wanted_set:
                continue
            text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip()
            if marker_re.search(text):
                applied.add(href)

        if applied:
            print(f"  SEARCH PRE-FILTER: ignoring {len(applied)} already-applied job(s).")
            for u in sorted(applied):
                print(f"    APPLIED CARD IGNORED: {u}")

        return [u for u in urls if u.split("#", 1)[0].split("?", 1)[0].rstrip("/") not in applied]

    async def record_result(self, url, title, status, company="", description="", match=None):
        """Persist the job outcome plus deterministic job metadata."""
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
            print(f"  Warning: could not record application result: {e}")

    async def _click_external_apply_from_naukri(self, page):
        """Click only the verified external/company-site Apply CTA on a Naukri job page."""
        selectors = [
            page.get_by_role("button", name=re.compile(r"apply", re.I)),
            page.get_by_role("link", name=re.compile(r"apply", re.I)),
            page.get_by_text(re.compile(r"apply\s+(on|via)\s+(company|employer)\s+site", re.I)),
            page.locator("[class*='apply']:visible"),
        ]
        external_markers = (
            "apply on company site", "apply on employer site", "company site",
            "employer site", "external application", "external site",
            "apply externally", "redirect to employer",
        )
        for loc in selectors:
            try:
                count = min(await loc.count(), 30)
            except Exception:
                continue
            for i in range(count):
                el = loc.nth(i)
                try:
                    if not await el.is_visible() or await el.is_disabled():
                        continue
                    meta = " ".join([
                        await el.inner_text(),
                        await el.get_attribute("aria-label") or "",
                        await el.get_attribute("title") or "",
                        await el.get_attribute("href") or "",
                        await el.get_attribute("data-url") or "",
                        await el.get_attribute("data-href") or "",
                        await el.get_attribute("data-apply-url") or "",
                        await el.get_attribute("onclick") or "",
                    ]).lower()
                    if not any(marker in meta for marker in external_markers):
                        continue
                    await el.scroll_into_view_if_needed()
                    await asyncio.sleep(150 / 1000)
                    await el.click(timeout=10000)
                    return True
                except Exception:
                    continue
        return False

    async def _native_apply_target_is_external(self, page):
        """Classify an Apply control that must route to the company-form flow."""
        try:
            controls = page.locator("a:visible, button:visible, [role='button']:visible")
            count = min(await controls.count(), 40)
            for i in range(count):
                el = controls.nth(i)
                try:
                    try:
                        text = (await el.inner_text()).strip().lower()
                        aria = (await el.get_attribute("aria-label") or "").strip().lower()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        continue
                    if "apply" not in text and "apply" not in aria:
                        continue
                    try:
                        href = await el.get_attribute("href")
                        data_url = (
                            await el.get_attribute("data-url")
                            or await el.get_attribute("data-href")
                            or await el.get_attribute("data-apply-url")
                        )
                        onclick = (await el.get_attribute("onclick") or "").strip().lower()
                        title_attr = (await el.get_attribute("title") or "").strip().lower()
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        continue
                    target = (href or data_url or "").strip()
                    descriptor = " ".join([text, aria, title_attr, target.lower(), onclick])
                    # This is a routing check. The verified CTA is clicked by
                    # _click_external_apply_from_naukri(), then its owned tab
                    # is handed to the canonical CompanyWebsiteAgent.
                    external_markers = (
                        "apply on company site", "apply on employer site",
                        "company site", "employer site", "external application",
                        "external site", "apply externally", "redirect to employer",
                    )
                    if any(marker in descriptor for marker in external_markers):
                        return True
                    if target and not target.startswith(("mailto:", "javascript:", "#")):
                        if not (target.startswith("/") or "naukri.com" in target.lower()):
                            return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def db_applied(self, url):
        """Only a confirmed native 'applied' row is persistent dedup."""
        try:
            row = self.con.execute(
                "SELECT status FROM applications WHERE job_url=?",
                (url,),
            ).fetchone()
            return bool(
                row
                and str(row[0]).strip().lower() == "applied"
            )
        except Exception:
            return False

    async def live_applied_state(self, page):
        """Detect a confirmed live Applied state with bounded batched DOM reads."""
        phrases = (
            "you have already applied",
            "already applied for this job",
            "already applied to this job",
            "application already submitted",
            "you have successfully applied to",
            "application submitted successfully",
        )
        try:
            body = await asyncio.wait_for(page.locator("body").inner_text(timeout=3000), timeout=4.0)
            body = re.sub(r"\s+", " ", body or "").lower()
            if any(p in body for p in phrases):
                return True
        except Exception:
            pass

        try:
            values = await asyncio.wait_for(
                page.locator("button:visible, a:visible, [role='button']:visible").evaluate_all(
                    """els => els.slice(0, 160).map(e => [
                        e.innerText || '', e.getAttribute('aria-label') || '',
                        e.getAttribute('title') || '', e.getAttribute('data-state') || '',
                        e.getAttribute('data-status') || ''
                    ].join(' '))"""
                ),
                timeout=4.0,
            )
            for value in values:
                text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
                if re.search(r"(?<![a-z])(?:applied|already applied|application submitted|applied successfully)(?![a-z])", text):
                    return True
        except Exception:
            pass
        return False

    async def fill_external_with_company_agent(
        self,
        page,
        source_url,
    ):
        """Run the dedicated CompanyWebsiteAgent on the external page."""
        try:
            profile_path = os.path.join(
                os.path.dirname(__file__),
                "profile.json",
            )

            resume_path = self.current_resume_path
            if not resume_path or not Path(str(resume_path)).exists():
                print("  EXTERNAL RESUME: job-specific tailored resume is unavailable; refusing generic resume.pdf fallback.")
                return "external_error"
            print(f"  EXTERNAL RESUME TARGET: {Path(str(resume_path)).name}")

            # CompanyWebsiteAgent treats this explicit path as authoritative;
            # it will not replace it with the profile's master resume.
            dry_run = (
                os.getenv(
                    "COMPANY_WEBSITE_DRY_RUN",
                    "true",
                ).strip().lower()
                not in {"0", "false", "no", "off"}
            )

            print(
                "  COMPANY WEBSITE FILLER:",
                f"dry_run={dry_run}",
            )

            filler = CompanyWebsiteAgent(
                dry_run=dry_run,
                profile_path=profile_path,
                resume_path=resume_path,
            )

            result = await filler.apply(
                page,
                page.url or source_url,
                application_opened=True,
            )

            state = str(
                result.get("status", "")
            ).upper()

            print(
                "  COMPANY WEBSITE RESULT:",
                state,
            )

            if state in {
                "READY_TO_SUBMIT",
                "EXTERNAL_FILLED",
            }:
                return "external_filled"

            if state in {
                "SUBMITTED",
                "SUCCESS",
                "APPLIED",
            }:
                return "external_submitted"

            if state in {
                "CAPTCHA_REQUIRED",
                "HUMAN_INTERVENTION",
                "SECURITY_CHECK",
                "LOGIN_REQUIRED",
            }:
                return "external_blocked"

            return "external_error"

        except Exception as exc:
            print(
                "  COMPANY WEBSITE FILLER ERROR:",
                type(exc).__name__,
                exc,
            )
            return "external_error"

    async def process_job(self, context, url):
        # TAB OWNERSHIP CONTRACT:
        # - One fresh page per job.
        # - Never select/close a pre-existing user tab.
        # - Matching external/company-site jobs stay in their original job tab.
        # - Once Apply is clicked, the owned application tab(s) remain open.
        try:
            page = await asyncio.wait_for(context.new_page(), timeout=15)
        except asyncio.TimeoutError:
            print("  Timed out creating a Naukri job tab; continuing to the next job.")
            return "tab_creation_timeout"
        title = url
        company = ""
        body = ""
        match = {}
        status = "not_applied"
        leave_page_open = False
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self.wait_stable(page)
            title = (await page.title()).strip() or url
            company = await self._extract_company_name(page, title)
            if company:
                print(f"  COMPANY: {company}")
            else:
                print("  COMPANY: NOT FOUND ON JOB PAGE")
            print(f"  Opened: {title[:100]}")

            if await self.live_applied_state(page):
                status = "already_applied"
                print(
                    "  LIVE APPLICATION STATE: Applied. "
                    "Not clicking Apply."
                )
                return status

            if await self.detect_blocker(page):
                status = "blocked"
                print("  BLOCKED: CAPTCHA/OTP/security verification.")
                return status

            if "naukri.com" not in page.url.lower():
                # A search result must begin on Naukri. Do not treat an
                # arbitrary redirect as a validated application handoff: the
                # external path below is entered only after its actual Naukri
                # Apply CTA has been inspected and clicked.
                status = "untrusted_external_job_url"
                print(f"  UNEXPECTED EXTERNAL JOB URL (no verified Apply CTA): {page.url}")
                return status

            try:
                jd_body = (await page.locator("body").inner_text(timeout=10000)).strip()
            except Exception:
                jd_body = ""
            body = jd_body
            match = self.matcher.match(title, jd_body)
            print(
                f"  JD MATCH: {match['score']}/{match['threshold']} | "
                f"eligible={match['eligible']} | "
                f"matched skills={len(match['matched_skills'])}"
            )
            if match["matched_skills"]:
                print("  MATCHED:", ", ".join(match["matched_skills"][:12]))
            if match["experience_note"]:
                print("  EXPERIENCE:", match["experience_note"])
            if match.get("ai_signal_hits"):
                print("  AI SIGNALS:", ", ".join(match["ai_signal_hits"][:10]))
            if not match.get("ai_relevant", True):
                print("  AI RELEVANCE: no meaningful GenAI/AI/ML signal detected.")

            if not match["eligible"]:
                status = "low_match" if match["experience_ok"] else "experience_mismatch"
                print("  SKIPPED: job does not meet the configured JD match criteria.")
                return status

            if await self._apply_is_mailto(page):
                status = "mailto_skipped"
                print("  SKIPPED: application requires email client; no Outlook/mail client will be opened.")
                return status

            # Matching Naukri jobs may route to an external/company ATS.
            # Click only the validated external Apply CTA, then hand the
            # resulting page to the canonical company-site form engine.
            if await self._native_apply_target_is_external(page):
                leave_page_open = True
                print(
                    "  MATCHED JOB HAS EXTERNAL/COMPANY-SITE APPLY CTA — "
                    "preparing job-specific tailored resume before opening external application."
                )

                # IMPORTANT: tailor BEFORE leaving the Naukri job page.
                # This guarantees that the external/company-site flow receives
                # the current job's tailored PDF instead of the account/master resume.
                try:
                    from resume_integration import build_tailored_resume
                    tailored = build_tailored_resume(
                        profile_path=str(Path(__file__).with_name("profile.json")),
                        title=title,
                        jd_text=body,
                        platform="naukri",
                        job_url=url,
                        company=company,
                    )
                except Exception as exc:
                    tailored = None
                    print(f"  NAUKRI EXTERNAL RESUME TAILORING ERROR: {type(exc).__name__}: {exc}")

                if not tailored or not Path(str(tailored)).exists():
                    self.current_resume_path = None
                    status = "external_resume_tailoring_failed"
                    print(
                        "  EXTERNAL APPLY BLOCKED: job-specific tailored resume could not be created; "
                        "generic resume.pdf will NOT be used."
                    )
                    return status

                self.current_resume_path = str(Path(str(tailored)).resolve())
                print(f"  NAUKRI EXTERNAL RESUME READY: {Path(self.current_resume_path).name}")
                pages_before_external = list(context.pages)
                external_clicked = await self._click_external_apply_from_naukri(page)
                if not external_clicked:
                    status = "external_apply_not_found"
                    print("  EXTERNAL APPLY: matching external CTA could not be clicked; leaving job tab open.")
                    return status

                active_external = page
                for _ in range(20):
                    try:
                        new_pages = [
                            p for p in context.pages
                            if p not in pages_before_external and not p.is_closed()
                        ]
                        for candidate in reversed(new_pages):
                            u = (candidate.url or "").lower()
                            if u and u != "about:blank" and "naukri.com" not in u:
                                active_external = candidate
                                break
                        if active_external is not page:
                            break

                        current = (page.url or "").lower()
                        if current and current != (url or "").lower() and "naukri.com" not in current:
                            active_external = page
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(250 / 1000)

                try:
                    if "naukri.com" in (active_external.url or "").lower():
                        # Some Naukri external CTAs navigate the current tab only
                        # after a delayed browser event. Do not guess or adopt an
                        # unrelated pre-existing tab. Leave the job tab open.
                        status = "external_apply_not_reached"
                        print("  EXTERNAL APPLY: external destination did not open; leaving tab open.")
                        return status
                except Exception:
                    status = "external_apply_not_reached"
                    return status

                # The external engine owns only this job's newly opened/redirected
                # page. It handles resume upload, profile-backed fields, CAPTCHA/OTP
                # stop-points, unknown fields, and final submission according to its
                # existing dry-run configuration. Never close the page here.
                result = await self.fill_external_with_company_agent(
                    active_external,
                    url,
                )
                status = result
                leave_page_open = True
                if status == "external_submitted":
                    self.external_jobs_filled += 1
                elif status == "external_filled":
                    self.external_jobs_filled += 1
                elif status == "external_blocked":
                    self.external_jobs_errored += 1
                else:
                    self.external_jobs_errored += 1
                print(
                    "  EXTERNAL APPLICATION TAB LEFT OPEN — "
                    "continuing to the next job."
                )
                return status

            if self.native_jobs_found >= self.target_native_applications:
                status = "application_target_reached"
                print(
                    f"  SKIPPED APPLY: application target reached "
                    f"({self.native_jobs_found}/{self.target_native_applications}); continuing job scan."
                )
                return status

            # Remember tabs before Apply so a native Naukri application opened
            # in a popup/new tab can be targeted instead of accidentally continuing
            # on the original job-detail tab.
            pages_before_apply = list(context.pages)

            clicked = await self.click_apply_for_current_job(page)
            if not clicked:
                status = "apply_not_found"
                print("  Apply control not found.")
                return status

            # From this point onward the current job/application tab belongs to the
            # application attempt and must not be closed on error, timeout, or unknown
            # question. The next job always gets a new tab.
            leave_page_open = True

            print("  Apply clicked. Checking Naukri response and actual browser destination...")
            await asyncio.sleep(800 / 1000)

            if await self.detect_naukri_apply_error(page):
                print("  APPLY ERROR: Naukri returned a processing error. Retrying Apply once...")
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(1000 / 1000)
                except Exception:
                    pass

                retry_clicked = await self.click_apply_for_current_job(page)
                if not retry_clicked:
                    status = "naukri_apply_error"
                    print("  APPLY FAILED: Apply control unavailable after retry. Not applied.")
                    return status

                await asyncio.sleep(1200 / 1000)
                if await self.detect_naukri_apply_error(page):
                    status = "naukri_apply_error"
                    print("  APPLY FAILED: Naukri returned the processing error again. Not applied.")
                    return status

                print("  Apply retry accepted; checking application flow...")

            # If Apply redirects/opens another tab, identify the actual target.
            # External tabs take priority; otherwise prefer a newly opened Naukri
            # tab that looks like an application flow.
            active = page
            new_naukri_application = None
            new_external_tab = None

            # CRITICAL TAB OWNERSHIP RULE:
            # Only a page created after THIS job's Apply click belongs to this job's
            # application flow. Never inspect/adopt/close arbitrary pre-existing tabs.
            for _ in range(16):
                pages = list(context.pages)
                new_pages = [p for p in pages if p not in pages_before_apply and not p.is_closed()]

                for candidate in reversed(new_pages):
                    try:
                        u = (candidate.url or "").lower()
                        if u and u != "about:blank" and "naukri.com" not in u:
                            new_external_tab = candidate
                            break
                    except Exception:
                        pass

                if new_external_tab is not None:
                    active = new_external_tab
                    break

                for candidate in reversed(new_pages):
                    try:
                        u = (candidate.url or "").lower()
                        if not u or u == "about:blank" or "naukri.com" not in u:
                            continue
                        body = (await candidate.locator("body").inner_text(timeout=1500)).lower()
                        application_signals = (
                            "save", "continue", "next", "submit application",
                            "years of experience", "notice period", "graduation year",
                        )
                        if any(signal in body for signal in application_signals):
                            new_naukri_application = candidate
                            break
                    except Exception:
                        pass

                if new_naukri_application:
                    active = new_naukri_application
                    break

                # Naukri may redirect the ORIGINAL job page instead of opening a new
                # tab. That page is still owned by this job, so it is safe to inspect.
                try:
                    current = (page.url or "").lower()
                    if current and current != (url or "").lower() and current != "about:blank":
                        active = page
                        break
                except Exception:
                    pass

                await asyncio.sleep(250 / 1000)

                try:
                    if await self.detect_naukri_apply_error(page):
                        status = "naukri_apply_error"
                        print("  NAUKRI APPLY ERROR: Naukri reported an error while processing the request.")
                        return status
                except Exception:
                    pass

                try:
                    if "naukri.com" not in page.url.lower() and page.url not in ("", "about:blank"):
                        active = page
                        break
                except Exception:
                    pass
                await asyncio.sleep(250 / 1000)

            # A native application popup/tab is kept open. The original job-detail
            # tab is ALSO kept open. We never close a job/application tab merely because
            # Naukri opened another tab; this prevents the "replace/close" failure mode.
            if new_naukri_application is not None and active is not page:
                page = active

            try:
                dest = (active.url or "").lower()
            except Exception:
                dest = ""

            if dest and "naukri.com" not in dest and dest != "about:blank":
                # Defense in depth: a dynamic Naukri control may redirect after
                # the preflight classification. That is still an intended external
                # application and must be handed to the company-site engine.
                print(f"  EXTERNAL APPLY DESTINATION DETECTED: {active.url}")

            # Native Naukri application path.
            # Keep the application tab open after filling/submitting so the user
            # can inspect the saved state. The next job is opened in a fresh tab.
            # This also preserves partially filled answers when QA encounters a
            # question the agent cannot answer safely.
            leave_page_open = True
            await self.wait_stable(active)
            print("  Naukri-native application flow detected. Leaving this tab open after processing.")
            flow_status = await self.run_application_panel(active, url)

            if flow_status == "applied":
                status = "applied"
                self.native_jobs_found += 1
                print(f"  APPLICATION RECORDED: applied ({self.native_jobs_found}/{self.target_native_applications})")
            elif flow_status == "dry_run_complete":
                status = "native_dry_run"
                print("  DRY RUN NATIVE FLOW: success state observed, not counted as a real submission.")
            elif flow_status == "human_intervention":
                status = "blocked"
            elif flow_status == "unknown_question":
                status = "unknown_question"
            elif flow_status == "fill_failed":
                status = "fill_failed"
            elif flow_status == "answer_not_verified":
                status = "answer_not_verified"
            elif flow_status == "application_incomplete":
                status = "application_incomplete"
            else:
                status = "native_flow_stopped"
            return status
        finally:
            self.current_resume_path = None
            await self.record_result(url, title, status, company=company, description=body, match=match)
            try:
                if not leave_page_open and not page.is_closed():
                    await page.close()
            except Exception as cleanup_error:
                print(f"  TAB CLEANUP WARNING: {type(cleanup_error).__name__}: {cleanup_error}")

    def _external_field_values(self):
        """Truthful profile values for filling third-party application forms.
        Never invents anything not already present in profile.json."""
        profile = self.engine.reasoner.profile
        contact = profile.get("contact", {}) or {}
        candidate = profile.get("candidate", {}) or {}
        comp = profile.get("compensation", {}) or {}
        full_name = (contact.get("name") or "").strip()
        parts = full_name.split()
        return {
            "first_name": parts[0] if parts else "",
            "last_name": " ".join(parts[1:]) if len(parts) > 1 else (parts[0] if parts else ""),
            "full_name": full_name,
            "email": contact.get("email", "") or "",
            "phone": contact.get("phone", "") or "",
            "city": contact.get("city", "") or "",
            "state": contact.get("state", "") or "",
            "country": contact.get("country", "") or "",
            "pin_code": contact.get("pin_code", "") or "",
            "current_company": "N/A - Fresher / Graduate",
            "notice_period": str(candidate.get("notice_period_days", "") or ""),
            "expected_ctc": str(comp.get("expected_ctc", "") or ""),
            "current_ctc": str(comp.get("current_ctc", "") or ""),
            "total_experience": str(candidate.get("total_experience_years", "") or ""),
            "linkedin": contact.get("linkedin", "") or "",
        }

    async def _click_external_submit(self, page):
        """Best-effort submit/continue click on an unfamiliar company site."""
        names = ["Submit Application", "Submit", "Apply Now", "Apply",
                 "Continue", "Next", "Send Application", "Finish"]
        for text in names:
            for getter in (
                lambda t: page.get_by_role("button", name=re.compile(r"^" + re.escape(t) + r"$", re.I)),
                lambda t: page.get_by_role("button", name=re.compile(re.escape(t), re.I)),
            ):
                try:
                    loc = getter(text)
                    count = await loc.count()
                except Exception:
                    continue
                for i in range(count):
                    el = loc.nth(i)
                    try:
                        if not await el.is_visible() or await el.is_disabled():
                            continue
                        await el.scroll_into_view_if_needed()
                        await el.click(timeout=8000)
                        return True
                    except Exception:
                        continue
        return False


    def _resume_path(self):
        """Resolve the configured resume file, supporting either a file or a resume folder."""
        profile = getattr(self, "profile", {}) or {}
        resume = profile.get("resume", {}) or {}
        configured = resume.get("path")
        if not configured:
            return None

        path = os.path.expandvars(os.path.expanduser(str(configured)))
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(__file__), path)

        if os.path.isfile(path):
            return path

        if os.path.isdir(path):
            candidates = []
            for name in os.listdir(path):
                full = os.path.join(path, name)
                if not os.path.isfile(full):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in {".pdf", ".doc", ".docx"}:
                    continue
                # Prefer likely resume filenames, then PDF, then alphabetical.
                low = name.lower()
                score = (
                    (100 if "resume" in low else 0) +
                    (80 if "cv" in low else 0) +
                    (30 if "anuroop" in low else 0) +
                    (10 if ext == ".pdf" else 0)
                )
                candidates.append((score, name.lower(), full))

            if candidates:
                candidates.sort(key=lambda x: (-x[0], x[1]))
                selected = candidates[0][2]
                print(f"RESUME SELECTED: {selected}")
                return selected

        print(f"RESUME NOT FOUND: {path}")
        return None


    async def _upload_external_resume(self, page) -> bool:
        """Upload configured resume via direct input or one controlled upload-button click."""
        path = self._resume_path()
        if not path:
            print("EXTERNAL RESUME: no configured resume file found.")
            return False
        filename = os.path.basename(path)

        async def try_file_inputs():
            try:
                inputs = page.locator('input[type="file"]')
                total = await inputs.count()
                for i in range(total):
                    el = inputs.nth(i)
                    try:
                        if await el.is_disabled():
                            continue
                    except Exception:
                        pass
                    context = ""
                    try:
                        context = await el.evaluate("""e=>{
                            let n=e,s="";
                            for(let i=0;i<6&&n;i++,n=n.parentElement)
                                s+=" "+(n.innerText||"")+" "+
                                   (n.getAttribute("aria-label")||"")+" "+
                                   (n.getAttribute("title")||"");
                            return s;
                        }""")
                    except Exception:
                        pass
                    hay = re.sub(r"\s+", " ", context).lower()
                    if any(k in hay for k in ("resume","cv","upload","attach")) or total == 1:
                        await el.set_input_files(path)
                        print(f"EXTERNAL RESUME UPLOADED: {filename}")
                        return True
            except Exception as exc:
                print(f"EXTERNAL DIRECT RESUME INPUT ERROR: {exc}")
            return False

        if await try_file_inputs():
            return True

        try:
            controls = page.locator(
                'button:visible, [role="button"]:visible, label:visible, '
                'a:visible, [aria-label]:visible'
            )
            phrases = (
                "resume upload","upload resume","upload cv","attach resume",
                "attach cv","upload from device","upload from computer",
                "choose file","browse files","select resume","select cv"
            )
            matches=[]
            for i in range(await controls.count()):
                el=controls.nth(i)
                if not await el.is_visible():
                    continue
                vals=[]
                for attr in ("aria-label","title","value"):
                    v=await el.get_attribute(attr)
                    if v: vals.append(v)
                try: vals.append(await el.inner_text())
                except Exception: pass
                txt=re.sub(r"\s+"," "," ".join(vals).strip()).lower()
                if any(p in txt for p in phrases):
                    matches.append((el,txt))

            if not matches:
                print("EXTERNAL RESUME: upload-from-device control not found.")
                return False

            el,txt=matches[0]
            print(f"EXTERNAL RESUME CONTROL FOUND: {txt[:120]}")
            try:
                async with page.expect_file_chooser(timeout=5000) as fc_info:
                    await el.click(force=True)
                chooser=await fc_info.value
                await chooser.set_files(path)
                print(f"EXTERNAL RESUME UPLOADED VIA FILE CHOOSER: {filename}")
                return True
            except Exception as exc:
                print(f"EXTERNAL RESUME FILE CHOOSER NOT CAPTURED: {exc}")
                # One re-scan handles controls that create the file input after click.
                return await try_file_inputs()
        except Exception as exc:
            print(f"EXTERNAL RESUME UPLOAD ERROR: {exc}")
            return False


    async def _external_form_diagnostics(self, page):
        """Expose the real external controls when a form field is missed."""
        try:
            controls=page.locator('input:visible, textarea:visible, select:visible')
            found=[]
            for i in range(min(await controls.count(),100)):
                el=controls.nth(i)
                typ=(await el.get_attribute("type") or "").lower()
                if typ in {"hidden","submit","button","image","reset"}:
                    continue
                vals=[]
                for attr in ("name","id","placeholder","aria-label"):
                    v=await el.get_attribute(attr)
                    if v: vals.append(f"{attr}={v}")
                try:
                    tag=await el.evaluate("e=>e.tagName.toLowerCase()")
                    if tag=="select": vals.append("select")
                except Exception:
                    pass
                found.append(" | ".join(vals) or "unnamed-control")
            if found:
                print("EXTERNAL FORM CONTROLS:", found)
        except Exception:
            pass

    async def _verify_external_resume_upload(self, page, filename: str) -> bool:
        """Best-effort verification that the configured filename is visible after upload."""
        try:
            body = await page.locator("body").inner_text(timeout=3000)
            normalized_body = re.sub(r"\s+", " ", body).lower()
            if filename.lower() in normalized_body:
                print(f"EXTERNAL RESUME VERIFIED: {filename}")
                return True

            # Common upload success indicators.
            if any(x in normalized_body for x in (
                "uploaded successfully", "upload successful",
                "resume uploaded", "cv uploaded", "file uploaded"
            )):
                print("EXTERNAL RESUME VERIFIED: upload success indicator found.")
                return True
        except Exception:
            pass
        return False

    async def _click_external_apply(self, page):
        """Click one genuine external Apply control, skipping mailto/security links."""
        controls=page.locator(
            "button:visible,[role='button']:visible,a:visible,"
            "input[type='submit']:visible,input[type='button']:visible"
        )
        phrases=("apply now","apply for this job","apply for job","apply online",
                 "start application","start applying","submit application","apply")
        for i in range(await controls.count()):
            el=controls.nth(i)
            try:
                if not await el.is_visible() or await el.is_disabled():
                    continue
            except Exception:
                continue
            vals=[]
            for at in ("aria-label","title","value"):
                v=await el.get_attribute(at)
                if v: vals.append(v)
            try: vals.append(await el.inner_text())
            except Exception: pass
            text=re.sub(r"\s+"," "," ".join(vals).strip())
            low=text.lower()
            href=(await el.get_attribute("href") or "").lower()
            onclick=(await el.get_attribute("onclick") or "").lower()
            if href.startswith("mailto:") or "mailto:" in onclick:
                continue
            if any(p in low for p in phrases):
                await el.scroll_into_view_if_needed()
                await el.click(timeout=7000)
                print(f"  EXTERNAL APPLY CLICKED: {text[:100]}")
                return True
        print("  EXTERNAL APPLY: no genuine Apply control found.")
        return False

    async def _external_has_candidate_form(self, page):
        try:
            controls=page.locator("input:visible,textarea:visible,select:visible")
            meaningful=0
            for i in range(min(await controls.count(),100)):
                el=controls.nth(i)
                typ=(await el.get_attribute("type") or "").lower()
                if typ not in {"hidden","submit","button","file","checkbox","radio","password","reset","image"}:
                    meaningful+=1
            body=(await page.locator("body").inner_text()).lower()
            return meaningful>=2 or ("resume upload" in body and "submit" in body)
        except Exception:
            return False

    async def fill_external_application(self, page):
        """External application state machine: landing -> form -> upload -> fill -> submit."""
        try:
            try:
                await page.wait_for_load_state("domcontentloaded",timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(2500 / 1000)

            if await self.intervention(page):
                print("  EXTERNAL SECURITY CHECK: manual intervention required; leaving tab open.")
                return "external_blocked"

            # Landing page: click one genuine Apply control only when no form is present.
            if not await self._external_has_candidate_form(page):
                await self._click_external_apply(page)
                await asyncio.sleep(2200 / 1000)

            if await self.intervention(page):
                print("  EXTERNAL SECURITY CHECK AFTER APPLY: leaving tab open.")
                return "external_blocked"

            # Actual form: upload first, then fill candidate fields.
            await self._upload_external_resume(page)

            values=self._external_field_values()
            filled=[]
            controls=page.locator("input:visible,textarea:visible,select:visible")
            for i in range(await controls.count()):
                el=controls.nth(i)
                try:
                    if not await el.is_visible() or await el.is_disabled():
                        continue
                    tag=(await el.evaluate("e=>e.tagName.toLowerCase()"))
                    typ=(await el.get_attribute("type") or "").lower()
                    if tag!="select" and typ in {"hidden","submit","button","checkbox","radio","file","password","reset","image"}:
                        continue
                    try:
                        if (await el.input_value()).strip():
                            continue
                    except Exception:
                        pass

                    vals=[]
                    for at in ("name","id","placeholder","aria-label","title"):
                        v=await el.get_attribute(at)
                        if v: vals.append(v)
                    eid=await el.get_attribute("id")
                    if eid:
                        try:
                            lab=page.locator(f"label[for='{eid}']")
                            if await lab.count(): vals.append(await lab.first.inner_text())
                        except Exception:
                            pass
                    try:
                        vals.append(await el.evaluate("""e=>{
                            let p=e.parentElement,s="";
                            for(let i=0;i<6&&p;i++,p=p.parentElement)s+=" "+(p.innerText||"");
                            return s;
                        }"""))
                    except Exception:
                        pass

                    hay=re.sub(r"\s+"," "," ".join(vals)).lower()
                    key=None
                    for keywords,k in EXTERNAL_FIELD_RULES:
                        if any(w in hay for w in keywords):
                            key=k
                            break
                    if not key:
                        continue

                    value=values.get(key)
                    if value in (None,""):
                        continue
                    if await self._set_control_value(el,str(value)):
                        item=f"{key}={value}"
                        if item not in filled:
                            filled.append(item)
                except Exception:
                    continue

            if filled:
                print("  EXTERNAL FORM FILLED:",", ".join(filled))
            else:
                print("  EXTERNAL FORM: no recognizable profile-backed fields found.")

            rp=self._resume_path()
            if rp:
                await self._verify_external_resume_upload(page,os.path.basename(rp))

            if self.dry_run:
                print("  DRY_RUN=true: external form filled; final Submit remains blocked.")
                return "external_filled"

            if await self._click_external_submit(page):
                print("  EXTERNAL SUBMIT CONTROL CLICKED.")
                return "external_submitted"

            print("  EXTERNAL: final Submit not found; leaving tab open.")
            return "external_filled"

        except Exception as exc:
            print(f"  EXTERNAL FORM ERROR: {type(exc).__name__}: {exc}")
            print("  EXTERNAL: leaving tab open and continuing to next job.")
            return "external_error"

    async def detect_blocker(self, page):
        try:
            text=(await page.locator("body").inner_text(timeout=5000)).lower()
        except Exception:
            return False
        return any(x in text for x in [
            "captcha", "enter otp", "one time password",
            "verify you're human", "security verification"
        ])

    async def detect_naukri_apply_error(self, page):
        """Detect Naukri's transient/application-level error banner after Apply."""
        try:
            text = (await page.locator("body").inner_text(timeout=3000)).lower()
        except Exception:
            return False

        error_phrases = [
            "there was an error while processing your request",
            "error while processing your request",
            "please try again later",
            "something went wrong while processing",
            "unable to process your request",
        ]
        return any(x in text for x in error_phrases)

    async def _apply_is_mailto(self, page) -> bool:
        """Detect email/mailto application routes before clicking them."""
        try:
            loc = page.locator('a[href^="mailto:"], [href^="mailto:"], [onclick*="mailto:"]')
            for i in range(await loc.count()):
                el = loc.nth(i)
                if await el.is_visible():
                    print("  MAILTO APPLY DETECTED: refusing to open external mail client.")
                    return True

            # Also inspect visible Apply-ish controls for mailto hrefs.
            controls = page.locator('a:visible, button:visible, [role="button"]:visible')
            for i in range(min(await controls.count(), 150)):
                el = controls.nth(i)
                try:
                    txt=(await el.inner_text()).strip().lower()
                except Exception:
                    txt=""
                if "apply" not in txt:
                    continue
                href=(await el.get_attribute("href") or "").lower()
                onclick=(await el.get_attribute("onclick") or "").lower()
                if href.startswith("mailto:") or "mailto:" in onclick:
                    print("  MAILTO APPLY DETECTED: refusing to open external mail client.")
                    return True
        except Exception:
            pass
        return False

    async def click_apply_for_current_job(self, page):
        """Perform a verified Apply click using the visible job-page control.
        Tries an exact "Apply" match first (most precise), then falls back
        to common real-world variants ("Apply Now", "Apply for this Job",
        "Apply on company site", icon buttons with an apply-ish aria-label),
        then finally any control whose visible text merely contains "apply"."""
        exact_candidates = [
            page.get_by_role("button", name=re.compile(r"^apply$", re.I)),
            page.get_by_role("link", name=re.compile(r"^apply$", re.I)),
            page.get_by_text("Apply", exact=True),
            # Naukri sometimes renders the CTA as a styled div/span rather than
            # a semantic button/link. Keep these selectors narrowly scoped.
            page.locator(r"text=/^\s*apply\s*$/i"),
            page.locator("[class*='apply-button']:visible"),
            page.locator("[class*='applyButton']:visible"),
        ]
        variant_names = [
            r"^apply now$", r"^apply for this job$", r"^apply on company site$",
            r"^easy apply$", r"^quick apply$", r"^apply here$",
        ]
        broad_candidates = [
            page.get_by_role("button", name=re.compile(v, re.I)) for v in variant_names
        ] + [
            page.get_by_role("link", name=re.compile(v, re.I)) for v in variant_names
        ] + [
            # Last resort: any visible button/link whose text merely contains "apply".
            page.get_by_role("button", name=re.compile(r"apply", re.I)),
            page.get_by_role("link", name=re.compile(r"apply", re.I)),
        ]

        for loc in exact_candidates + broad_candidates:
            try:
                count = await loc.count()
            except Exception:
                continue
            for i in range(min(count, 10)):
                el = loc.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    if await el.is_disabled():
                        continue
                    # A class-based selector can match a wrapper. Prefer an
                    # actually actionable descendant when available.
                    try:
                        nested = el.locator("button, a, [role='button']")
                        if await nested.count():
                            for ni in range(min(await nested.count(), 3)):
                                cand = nested.nth(ni)
                                if await cand.is_visible() and not await cand.is_disabled():
                                    el = cand
                                    break
                    except Exception:
                        pass
                    # Defense in depth: even if preflight missed a dynamic control,
                    # never click an explicitly external/company-site Apply control.
                    meta = " ".join([
                        (await el.inner_text() or ""),
                        (await el.get_attribute("aria-label") or ""),
                        (await el.get_attribute("title") or ""),
                        (await el.get_attribute("href") or ""),
                        (await el.get_attribute("data-url") or ""),
                        (await el.get_attribute("data-href") or ""),
                        (await el.get_attribute("data-apply-url") or ""),
                    ]).lower()
                    if any(marker in meta for marker in (
                        "apply on company site", "apply on employer site",
                        "company site", "employer site", "external application",
                        "external site", "apply externally",
                    )):
                        continue
                    href = (await el.get_attribute("href") or "").lower()
                    if href and "naukri.com" not in href and not href.startswith(("/", "#", "javascript:")):
                        continue
                    await el.scroll_into_view_if_needed()
                    await asyncio.sleep(250 / 1000)
                    await el.click(timeout=10000)
                    return True
                except Exception:
                    continue

        # Nothing matched at all: dump visible button/link-like text so the
        # next fix targets the real control instead of guessing again.
        try:
            dump = await page.evaluate(
                """() => {
                    const els = [...document.querySelectorAll('button, a, [role="button"]')];
                    return els.filter(e => {
                        const r = e.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    }).map(e => (e.innerText || e.getAttribute('aria-label') || '').trim())
                      .filter(t => t.length > 0 && t.length < 60)
                      .slice(0, 40);
                }"""
            )
            print("  APPLY CONTROL NOT FOUND — visible button/link text on page:", json.dumps(dump, ensure_ascii=False))
        except Exception:
            pass
        return False

    async def run_application_panel(self, page, job_url):
        # Question fingerprints are scoped to a single application.
        # Do not carry answered questions from one job into the next job:
        # otherwise a repeated question such as current CTC can be skipped
        # on the next application.
        self.answered.clear()
        self.last_question = None
        no_progress = 0

        for _ in range(120):
            if await self.intervention(page):
                print("CAPTCHA/OTP/security verification detected. Pausing.")
                return "human_intervention"

            body = (await page.locator("body").inner_text()).strip()

            if self.application_incomplete(body):
                print("  APPLICATION INCOMPLETE: Naukri says mandatory information is missing.")
                print("  No further controls will be clicked and this application tab will remain open.")
                return "application_incomplete"

            if self.completed(body):
                if self.dry_run:
                    print("DRY RUN: Naukri displayed a success state; no real submission was performed.")
                    return "dry_run_complete"
                print("APPLICATION SUCCESS")
                return "applied"

            q = await self.current_question(page)

            if q:
                fingerprint = self.fingerprint(q)
                if fingerprint in self.answered:
                    # We have already answered this exact prompt. Do not sit in a
                    # passive retry loop: immediately try the visible intermediate
                    # control and verify that the panel moves to a new state.
                    clicked = await self.click_continue(page)
                    if clicked:
                        if await self.wait_for_question_change(page, q, timeout_ms=7000):
                            no_progress = 0
                        else:
                            no_progress += 1
                    else:
                        no_progress += 1
                    if no_progress > 6:
                        return "no_progress"
                    continue

                options = await self.visible_options(page, q)
                value, field, kind = self.engine.answer(q, options)

                # Keep the semantic answer for persistence, but separately map it
                # to the exact visible Naukri option when the UI uses ranges/buckets.
                ui_value = self._map_answer_to_visible_option(q, value, options)
                self._last_answer_value = ui_value

                if value is None:
                    print("UNKNOWN / UNVERIFIED QUESTION:", q)
                    print("  visible_options seen:", options)
                    print("Configure the truthful answer in profile.json.")
                    return "unknown_question"

                print("Q:", q)
                print("A:", value)
                if str(ui_value) != str(value):
                    print("  UI OPTION MAPPED:", ui_value)

                filled = await self.fill_answer_in_panel(page, ui_value, kind, question=q, options=options)
                if not filled:
                    print("Could not safely locate the conversational answer control.")
                    print("  kind:", kind, "| visible_options seen:", options)
                    try:
                        # Dump the visible inputs/textareas/contenteditable on the
                        # whole page so the next fix targets the real selector
                        # instead of guessing again.
                        dump = await page.evaluate(
                            """() => {
                                const els = [...document.querySelectorAll('input, textarea, [contenteditable]')];
                                return els.filter(e => {
                                    const r = e.getBoundingClientRect();
                                    return r.width > 0 && r.height > 0;
                                }).map(e => ({
                                    tag: e.tagName,
                                    placeholder: e.getAttribute('placeholder'),
                                    type: e.getAttribute('type'),
                                    cls: e.getAttribute('class'),
                                    contenteditable: e.getAttribute('contenteditable')
                                }));
                            }"""
                        )
                        print("  VISIBLE INPUT-LIKE ELEMENTS ON PAGE:", json.dumps(dump, ensure_ascii=False))
                    except Exception as e:
                        print("  (diagnostic dump failed:", e, ")")
                    return "fill_failed"

                self.answered.add(fingerprint)
                # SQLite stores scalar values; multi-select answers are
                # persisted as a stable JSON string rather than a Python list.
                qa_value = json.dumps(value, ensure_ascii=False) if isinstance(value, (list, tuple)) else str(value)
                qa(self.con, job_url, q, qa_value, field)

                # The native Naukri panel can render the next question asynchronously.
                # First wait for the conversational state to advance naturally; if
                # it does not, click the real intermediate CTA and then wait again.
                if await self.wait_for_question_change(page, q, timeout_ms=7000):
                    no_progress = 0
                else:
                    clicked = await self.click_continue(page)
                    if clicked and await self.wait_for_question_change(page, q, timeout_ms=7000):
                        no_progress = 0
                    elif clicked:
                        no_progress += 1
                    else:
                        no_progress += 1
            else:
                # When there is no next question, the panel may be waiting for
                # a final Continue/Submit/Apply action. Do not just time out.
                if not self.dry_run:
                    if await self.click_continue(page):
                        no_progress = 0
                        await asyncio.sleep(700 / 1000)
                        continue
                await asyncio.sleep(300 / 1000)
                no_progress += 1

            if no_progress > 25:
                # Re-read the DOM rather than endlessly hammering the page.
                if self.completed((await page.locator("body").inner_text()).strip()):
                    return "applied" if not self.dry_run else "dry_run_complete"
                return "no_progress"

        return "timeout"

    async def current_question(self, page):
        # Prefer visible text inside likely conversational containers.
        container_selectors = [
            "[role='dialog']:visible",
            "[class*='chat']:visible",
            "[class*='conversation']:visible",
            "[class*='apply']:visible"
        ]
        texts = []
        for sel in container_selectors:
            try:
                loc = page.locator(sel)
                for i in range(await loc.count()):
                    el = loc.nth(i)
                    if await el.is_visible():
                        t = (await el.inner_text()).strip()
                        if t:
                            texts.append(t)
            except:
                pass

        source = "\n".join(texts) if texts else await page.locator("body").inner_text()
        lines = [x.strip() for x in source.splitlines() if x.strip()]

        candidates = []
        for line in lines:
            # Most conversational questions end in '?', but some Naukri
            # variants render field prompts without punctuation.
            low_line = line.lower()
            question_like = "?" in line or any(token in low_line for token in (
                "graduation year", "year of graduation", "year did you graduate",
                "pass out", "passing year", "years of experience",
                "current ctc", "expected ctc",
                "gpa", "cgpa", "grade point",
                "10th", "10th standard", "ssc", "class x",
                "12th", "12th standard", "intermediate", "hsc", "class xii",
                "percentage", "percent", "marks",
                "which skills", "what skills", "skills", "skill",
                "salutation", "github",
            ))
            if not question_like or not (5 <= len(line) <= 350):
                continue
            if self.fingerprint(line) in self.answered:
                continue
            # Exclude obvious site-wide questions/marketing text.
            low = line.lower()
            if any(x in low for x in ["what are you looking for", "search jobs"]):
                continue
            candidates.append(line)

        return candidates[-1] if candidates else None

    async def visible_options(self, page, question=None):
        """Discover actual answer choices from the active application UI."""
        options = []

        # IMPORTANT: Naukri keeps earlier answers in the same conversational
        # panel. A prior "Yes" bubble can be exposed as a visible button even
        # when the current question is an open text question. Scope answer-choice
        # discovery to controls rendered at/after the current question so prior
        # transcript bubbles cannot become false options.
        question_box = None
        if question:
            try:
                qloc = page.get_by_text(str(question).strip(), exact=True)
                for i in range(min(await qloc.count(), 8)):
                    qel = qloc.nth(i)
                    if not await qel.is_visible():
                        continue
                    box = await qel.bounding_box()
                    if box:
                        question_box = box
                        break
            except Exception:
                question_box = None

        selectors = [
            "[role='dialog']:visible [role='option']",
            "[role='dialog']:visible [role='radio']",
            "[role='dialog']:visible [role='checkbox']",
            "[role='dialog']:visible button",
            "[role='dialog']:visible label",
            "[role='dialog']:visible [role='button']",
            "[class*='chat']:visible [role='option']",
            "[class*='chat']:visible [role='radio']",
            "[class*='chat']:visible [role='checkbox']",
            "[class*='chat']:visible button",
            "[class*='chat']:visible label",
            "[class*='apply']:visible [role='option']",
            "[class*='apply']:visible [role='radio']",
            "[class*='apply']:visible [role='checkbox']",
            "[class*='apply']:visible button",
            "[class*='apply']:visible label",
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                for i in range(await loc.count()):
                    el = loc.nth(i)
                    if await el.is_visible():
                        # When a current question is known, ignore controls that
                        # are physically above it (previous answers/questions).
                        # Keep a generous horizontal band because Naukri's answer
                        # bubbles can be right-aligned relative to the question.
                        if question_box is not None:
                            try:
                                box = await el.bounding_box()
                                if not box:
                                    continue
                                q_left = question_box["x"] - 100
                                q_right = question_box["x"] + question_box["width"] + 100
                                q_bottom = question_box["y"] + question_box["height"]
                                if box["y"] + box["height"] < q_bottom - 6:
                                    continue
                                if box["y"] > q_bottom + 320:
                                    continue
                                center_x = box["x"] + box["width"] / 2
                                if center_x < q_left or center_x > q_right:
                                    continue
                            except Exception:
                                pass
                        t = re.sub(r"\s+", " ", (await el.inner_text()).strip())
                        action_text = re.sub(r"\s+", " ", t).strip().lower()
                        action_tokens = {
                            "continue", "next", "submit", "submit application",
                            "apply", "apply now", "send", "send application",
                            "save", "skip", "finish", "done", "back", "cancel"
                        }
                        if (
                            t and len(t) < 180
                            and action_text not in action_tokens
                            and not action_text.startswith(("save ", "continue ", "submit "))
                        ):
                            options.append(t)
            except Exception:
                pass
        return list(dict.fromkeys(options))[:50]

    async def _visible_form_controls(self, page):
        """Discover visible/editable/clickable controls without depending on Naukri CSS."""
        js = """() => {
            const visible = e => {
                const r = e.getBoundingClientRect();
                const s = getComputedStyle(e);
                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' &&
                       s.display !== 'none' && s.opacity !== '0';
            };
            const els = [...document.querySelectorAll(
                'input, textarea, select, button, [contenteditable="true"], ' +
                '[role="textbox"], [role="combobox"], [role="radio"], [role="checkbox"], ' +
                '[role="option"], [role="button"], label, [tabindex]'
            )].filter(visible);

            return els.map((e, i) => {
                const r = e.getBoundingClientRect();
                const parentText = (e.parentElement?.innerText || '').trim().replace(/\\s+/g,' ');
                return {
                    i, tag:e.tagName.toLowerCase(),
                    type:(e.getAttribute('type')||'').toLowerCase(),
                    role:e.getAttribute('role')||'',
                    placeholder:e.getAttribute('placeholder')||'',
                    aria:e.getAttribute('aria-label')||'',
                    text:(e.innerText || e.textContent || '').trim().replace(/\\s+/g,' ').slice(0,200),
                    name:e.getAttribute('name')||'',
                    value:e.value ?? '',
                    checked:!!e.checked,
                    disabled:!!e.disabled,
                    editable:e.isContentEditable || !e.disabled,
                    x:r.x,y:r.y,w:r.width,h:r.height,
                    parentText:parentText.slice(0,500)
                };
            });
        }"""
        try:
            return await page.evaluate(js)
        except Exception:
            return []

    async def _set_control_value(self, el, value):
        """Set native or contenteditable controls using Playwright plus DOM events."""
        value = str(value)
        try:
            await el.scroll_into_view_if_needed()
            await el.click()
        except Exception:
            pass

        # fill() works for input/textarea/contenteditable in modern Playwright.
        try:
            await el.fill(value)
        except Exception:
            try:
                await el.evaluate(
                    """(e, v) => {
                        if (e.isContentEditable) {
                            e.textContent = v;
                        } else {
                            const proto = e instanceof HTMLTextAreaElement
                              ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                            if (setter) setter.call(e, v); else e.value = v;
                        }
                        e.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:v}));
                        e.dispatchEvent(new Event('change', {bubbles:true}));
                    }""", value)
            except Exception:
                return False

        # Verify before submitting.
        try:
            if (await el.get_attribute("contenteditable") == "true" or await el.is_editable()):
                try:
                    cur = (await el.input_value()).strip()
                except Exception:
                    cur = (await el.inner_text()).strip()
                if cur == value:
                    return True
                # Numeric normalization
                try:
                    if float(cur.replace(",", "")) == float(value.replace(",", "")):
                        return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    async def _control_is_relevant(self, el, question):
        """Score a control by proximity/label text so unrelated page inputs are ignored."""
        try:
            meta = await el.evaluate("""e => {
                const txt = (e.parentElement?.innerText || '').replace(/\\s+/g,' ').trim();
                const aria = e.getAttribute('aria-label') || '';
                const ph = e.getAttribute('placeholder') || '';
                const lab = e.labels?.[0]?.innerText || '';
                return (txt + ' ' + aria + ' ' + ph + ' ' + lab).toLowerCase();
            }""")
        except Exception:
            return 0
        qwords = set(re.findall(r"[a-z0-9]+", question.lower()))
        mwords = set(re.findall(r"[a-z0-9]+", meta))
        overlap = len(qwords & mwords)
        score = overlap
        if "ctc" in question.lower() and any(x in meta for x in ("ctc","salary","compensation","package")):
            score += 20
        if any(x in question.lower() for x in ("years", "experience")) and any(x in meta for x in ("experience","years","year")):
            score += 15
        return score

    async def _fill_text_input(self, page, value, question=None):
        """Adaptive text/number entry: discover the best visible control dynamically."""
        controls = await self._visible_form_controls(page)
        candidates = []

        for item in controls:
            tag = item.get("tag","")
            typ = item.get("type","")
            role = item.get("role","")
            if item.get("disabled") or typ in ("hidden","submit","button","file","image","checkbox","radio"):
                continue
            if not (tag in ("input","textarea","select") or item.get("editable") or role in ("textbox","combobox")):
                continue

            try:
                loc = page.locator("xpath=(//body//*[self::input or self::textarea or self::select or @contenteditable='true' or @role='textbox' or @role='combobox'])[%d]" % (item["i"]+1))
                # The XPath index is only a fallback; prefer semantic attributes below.
                candidates.append((loc, item))
            except Exception:
                pass

        # Re-query directly with broad selectors; newest/visible controls first.
        selectors = [
            "textarea:visible",
            "input:visible",
            "[contenteditable='true']:visible",
            "[role='textbox']:visible",
            "[role='combobox']:visible"
        ]
        allc = []
        for sel in selectors:
            try:
                loc = page.locator(sel)
                for i in range(await loc.count()-1, -1, -1):
                    el = loc.nth(i)
                    if not await el.is_visible() or not await el.is_editable():
                        continue
                    allc.append(el)
            except Exception:
                pass

        # Prefer controls whose surrounding label/container resembles the question.
        scored = []
        for el in allc:
            score = await self._control_is_relevant(el, question or "")
            try:
                ph = (await el.get_attribute("placeholder") or "").lower()
                aria = (await el.get_attribute("aria-label") or "").lower()
                if "type message" in ph or "type message" in aria:
                    score += 100
            except Exception:
                pass
            scored.append((score, el))

        # Highest relevance first, then DOM order.
        scored.sort(key=lambda x: x[0], reverse=True)

        for _, el in scored:
            if await self._set_control_value(el, value):
                # Do NOT press Enter automatically. Naukri recruiter-question
                # panels commonly expose a Save button; Enter can submit/clear
                # the field or advance the wrong UI state. The normal application
                # loop verifies the value, then clicks Save/Next/Continue safely.
                return True

        return False

    async def _click_option(self, page, value, question=None, multi=False):
        """Select a Naukri questionnaire option robustly and verify the UI state."""
        target = re.sub(r"\s+", " ", str(value).strip()).lower()
        if not target:
            return False

        qroots = []
        if question:
            try:
                qloc = page.get_by_text(str(question).strip(), exact=True)
                for i in range(min(await qloc.count(), 5)):
                    q = qloc.nth(i)
                    if await q.is_visible():
                        qroots.append(q)
            except Exception:
                pass

        selectors = [
            "[role='radio']:visible", "[role='option']:visible",
            "[role='button']:visible", "button:visible",
            "label:visible", "li:visible",
            "input[type='radio']:visible", "input[type='checkbox']:visible"
        ]

        async def collect(scope):
            out = []
            for sel in selectors:
                try:
                    loc = scope.locator(sel)
                    for i in range(await loc.count() - 1, -1, -1):
                        el = loc.nth(i)
                        if not await el.is_visible():
                            continue
                        vals = []
                        for attr in ("aria-label", "value", "title", "data-value"):
                            v = await el.get_attribute(attr)
                            if v:
                                vals.append(v)
                        try:
                            vals.append(await el.inner_text())
                        except Exception:
                            pass
                        txt = re.sub(r"\s+", " ", " ".join(vals).strip()).lower()
                        if (
                            txt == target
                            or txt.startswith(target + " ")
                            or txt.startswith(target + ",")
                            or txt.startswith(target + ":")
                            or txt.startswith(target + ".")
                        ):
                            out.append(el)
                except Exception:
                    pass
            return out

        candidates = []
        for q in qroots:
            for xp in (
                "xpath=ancestor::*[self::fieldset or @role='group' or @role='radiogroup' "
                "or contains(@class,'question') or contains(@class,'Question')][1]",
                "xpath=parent::*",
                "xpath=ancestor::*[1]"
            ):
                try:
                    c = q.locator(xp)
                    if await c.count() and await c.first.is_visible():
                        candidates.extend(await collect(c.first))
                except Exception:
                    pass

        if not candidates:
            for scope in (
                page.locator("[role='dialog']:visible").last,
                page.locator("[class*='chat']:visible").last,
                page.locator("body")
            ):
                try:
                    if await scope.count():
                        candidates.extend(await collect(scope))
                        if candidates:
                            break
                except Exception:
                    pass

        async def is_selected(el):
            try:
                typ = (await el.get_attribute("type") or "").lower()
                if typ in ("radio", "checkbox") and await el.is_checked():
                    return True
            except Exception:
                pass
            for attr in ("aria-checked", "aria-selected", "aria-pressed"):
                try:
                    if (await el.get_attribute(attr) or "").lower() in ("true", "1"):
                        return True
                except Exception:
                    pass
            try:
                cls = (await el.get_attribute("class") or "").lower()
                if any(k in cls for k in ("selected", "active", "checked", "chosen")):
                    return True
            except Exception:
                pass
            return False

        for el in candidates:
            for _ in range(3):
                try:
                    await el.scroll_into_view_if_needed()
                    typ = (await el.get_attribute("type") or "").lower()
                    if typ in ("radio", "checkbox"):
                        try:
                            await el.check(force=True)
                        except Exception:
                            await el.click(force=True)
                    else:
                        await el.click(force=True)
                    await asyncio.sleep(150 / 1000)
                    if await is_selected(el):
                        return True

                    parent = el.locator(
                        "xpath=ancestor::*[self::label or self::button or "
                        "@role='radio' or @role='option' or @role='button'][1]"
                    )
                    if await parent.count():
                        p = parent.first
                        await p.click(force=True)
                        await asyncio.sleep(150 / 1000)
                        if await is_selected(p) or await is_selected(el):
                            return True
                except Exception:
                    await asyncio.sleep(100 / 1000)

        try:
            loc = page.get_by_text(str(value).strip(), exact=True)
            for i in range(await loc.count() - 1, -1, -1):
                el = loc.nth(i)
                if not await el.is_visible():
                    continue
                try:
                    await el.click(force=True)
                    await asyncio.sleep(150 / 1000)
                except Exception:
                    pass
                parent = el.locator(
                    "xpath=ancestor::*[self::button or @role='button' or "
                    "@role='radio' or @role='option' or self::label][1]"
                )
                if await parent.count():
                    try:
                        await parent.first.click(force=True)
                        await asyncio.sleep(150 / 1000)
                    except Exception:
                        pass
                if await self._verify_current_answer(page, value):
                    return True
        except Exception:
            pass
        return False

    async def _select_dropdown(self, page, value):
        """Handle native and custom Naukri dropdowns and verify the result."""
        target = re.sub(r"\s+", " ", str(value).strip()).lower()

        try:
            sels = page.locator("select:visible")
            for i in range(await sels.count() - 1, -1, -1):
                el = sels.nth(i)
                try:
                    await el.select_option(label=str(value))
                except Exception:
                    try:
                        await el.select_option(str(value))
                    except Exception:
                        continue
                await asyncio.sleep(120 / 1000)
                try:
                    cur = (await el.input_value()).strip().lower()
                    if cur == target or target in cur:
                        return True
                except Exception:
                    pass
                try:
                    cur = re.sub(r"\s+", " ", (await el.locator("option:checked").inner_text()).strip()).lower()
                    if cur == target or target in cur:
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        try:
            combos = page.locator("[role='combobox']:visible")
            for i in range(await combos.count() - 1, -1, -1):
                el = combos.nth(i)
                try:
                    await el.click(force=True)
                    await asyncio.sleep(150 / 1000)
                    if await self._click_option(page, value):
                        for _ in range(5):
                            await asyncio.sleep(100 / 1000)
                            vals = []
                            for attr in ("value", "aria-label", "aria-valuetext"):
                                v = await el.get_attribute(attr)
                                if v:
                                    vals.append(v)
                            try:
                                vals.append(await el.inner_text())
                            except Exception:
                                pass
                            if target in re.sub(r"\s+", " ", " ".join(vals).strip()).lower():
                                return True
                            if await self._verify_current_answer(page, value):
                                return True
                except Exception:
                    pass
        except Exception:
            pass
        return False

    def _normalize_answer_text(self, value):
        return re.sub(r"[^a-z0-9.+%-]+", " ", str(value or "").strip().lower()).strip()

    def _option_contains_skill(self, option, skill):
        """Match a profile skill to a visible Naukri option without inventing skills."""
        o = self._normalize_answer_text(option)
        s = self._normalize_answer_text(skill)
        if not o or not s:
            return False
        if o == s:
            return True
        # Remove common UI qualifiers such as "(Programming Language)".
        base_o = re.sub(r"\s*\([^)]*\)\s*", " ", o).strip()
        base_s = re.sub(r"\s*\([^)]*\)\s*", " ", s).strip()
        return base_o == base_s or (
            len(base_s) >= 3 and re.search(r"(?<![a-z0-9])" + re.escape(base_s) + r"(?![a-z0-9])", base_o)
        )

    def _map_answer_to_visible_option(self, question, value, options):
        """
        Convert the semantic/profile answer into the ACTUAL visible Naukri option.

        Examples:
          95 + "More than 90%" -> "More than 90%"
          94 + "More than 90%" -> "More than 90%"
          6.8 + ["Less than 7", ...] -> "Less than 7"
          ["Python","SQL"] + visible skill choices -> matching visible choices

        This is deliberately UI-only: the stored QA answer remains the semantic value.
        """
        opts = [str(o).strip() for o in (options or []) if str(o).strip()]
        if not opts:
            return value

        q = str(question or "").lower()
        normalized_opts = [(o, self._normalize_answer_text(o)) for o in opts]

        # Multi-select skills: map each semantic profile skill to the exact visible label.
        if isinstance(value, (list, tuple)) or any(k in q for k in ("which skills", "what skills", "select the skills", "skills")):
            values = list(value) if isinstance(value, (list, tuple)) else [
                x.strip() for x in re.split(r"[,;|]\s*", str(value)) if x.strip()
            ]
            mapped = []
            for item in values:
                for option, no in normalized_opts:
                    if self._option_contains_skill(option, item):
                        if option not in mapped:
                            mapped.append(option)
                        break
            if mapped:
                return mapped if isinstance(value, (list, tuple)) or len(mapped) > 1 else mapped[0]

        # Exact answer is always preferred.
        nv = self._normalize_answer_text(value)
        for option, no in normalized_opts:
            if no == nv:
                return option

        # Yes/No semantic answer against threshold/range choices.
        if nv in {"yes", "no"}:
            positive = ("more than", "greater than", "above", "over ", "at least",
                        "90+", "95+", "80+", ">= ", "or more", "and above", "yes", "true")
            negative = ("less than", "below", "under", "at most", "up to", "<= ",
                        "no", "false", "not ")
            if nv == "yes":
                for option, no in normalized_opts:
                    if any(p in no for p in positive):
                        return option
            else:
                for option, no in normalized_opts:
                    if any(p in no for p in negative):
                        return option

        # Numeric answer against visible ranges, e.g. GPA 6.8 -> "Less than 7".
        try:
            number = float(str(value).replace(",", "").strip().rstrip("%"))
        except Exception:
            number = None

        if number is not None:
            for option, no in normalized_opts:
                # "between 7 and 8"
                m = re.search(r"between\s+(-?\d+(?:\.\d+)?)\s*(?:and|-)\s*(-?\d+(?:\.\d+)?)", no)
                if m:
                    lo, hi = float(m.group(1)), float(m.group(2))
                    if lo <= number <= hi:
                        return option

                m = re.search(r"(?:less than|below|under)\s+(-?\d+(?:\.\d+)?)", no)
                if m and number < float(m.group(1)):
                    return option

                m = re.search(r"(?:greater than|more than|above|over)\s+(-?\d+(?:\.\d+)?)", no)
                if m and number > float(m.group(1)):
                    return option

                m = re.search(r"(?:at least|minimum of)\s+(-?\d+(?:\.\d+)?)", no)
                if m and number >= float(m.group(1)):
                    return option

                m = re.search(r"(?:up to|at most)\s+(-?\d+(?:\.\d+)?)", no)
                if m and number <= float(m.group(1)):
                    return option

        # Percentage threshold question where the semantic engine returned a raw
        # numeric profile value but Naukri exposes percentage buckets.
        if number is not None and any(k in q for k in ("10th", "12th", "ssc", "hsc", "intermediate", "percentage", "percent", "marks")):
            for option, no in normalized_opts:
                if re.search(r"(?:more than|greater than|above|over)\s*90\s*%?", no) and number > 90:
                    return option
                if re.search(r"(?:less than|below|under)\s*80\s*%?", no) and number < 80:
                    return option
                m = re.search(r"between\s*80\s*%?\s*(?:and|-)\s*90\s*%?", no)
                if m and 80 <= number <= 90:
                    return option

        return value

    async def fill_answer_in_panel(self, page, value, kind, question=None, options=None):
        """
        Adaptive dispatcher. The semantic answer does not dictate the UI.
        The DOM decides whether this is text, numeric, choice, dropdown, etc.
        """
        options = options or []

        # Multi-select answers are semantic lists; click each matching visible option.
        if kind == "multi_select" and isinstance(value, (list, tuple)):
            clicked = 0
            for item in value:
                if await self._click_option(page, item, question, multi=True):
                    clicked += 1
            if clicked:
                # Some custom forms expose a Continue/Next/Submit action after
                # selecting chips/checkboxes; let the normal flow handle it too.
                await asyncio.sleep(150 / 1000)
                return True
            return False

        # If visible options contain the exact answer, prefer clicking them.
        if any(re.sub(r"\s+"," ",str(o).strip()).lower() == str(value).strip().lower() for o in options):
            if await self._click_option(page, value, question):
                return True

        # Open-ended recruiter questions should never touch unrelated page
        # comboboxes/search widgets. Text/number controls are handled first.
        if kind in ("text", "number"):
            if await self._fill_text_input(page, value, question):
                return True
            if kind == "number" and await self._select_dropdown(page, value):
                return True
            return await self._click_option(page, value, question)

        # Dropdowns are appropriate for explicit choice fields.
        if await self._select_dropdown(page, value):
            return True

        if kind == "yes_no":
            if await self._click_option(page, value, question):
                return True
            return await self._fill_text_input(page, value, question)

        if kind in ("number", "text"):
            if await self._fill_text_input(page, value, question):
                return True
            return await self._click_option(page, value, question)

        if await self._click_option(page, value, question):
            return True
        return await self._fill_text_input(page, value, question)

    async def verify_answer_in_panel(self, page, value, kind, question=None):
        expected = str(value).strip()

        # Current visible control value.
        selectors = [
            "textarea:visible", "input:visible",
            "[contenteditable='true']:visible",
            "[role='textbox']:visible", "[role='combobox']:visible"
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                for i in range(await loc.count()-1, -1, -1):
                    el = loc.nth(i)
                    if not await el.is_visible():
                        continue
                    try:
                        current = (await el.input_value()).strip()
                    except Exception:
                        current = (await el.inner_text()).strip()
                    if current == expected:
                        return True
                    if kind == "number":
                        try:
                            if float(current.replace(",","")) == float(expected.replace(",","")):
                                return True
                        except Exception:
                            pass
            except Exception:
                pass

        # Submitted conversational answer often appears as an exact transcript line.
        try:
            body = (await page.locator("body").inner_text()).strip()
            lines = [x.strip() for x in body.splitlines() if x.strip()]
            if expected in lines:
                return True
        except Exception:
            pass

        # Selected/checked state.
        target = re.sub(r"\s+", " ", expected).lower()
        for sel in [
            "[role='radio']:visible", "[role='option']:visible",
            "[role='button']:visible", "button:visible",
            "label:visible", "li:visible", "span:visible", "div:visible"
        ]:
            try:
                loc = page.locator(sel)
                for i in range(await loc.count()-1, -1, -1):
                    el = loc.nth(i)
                    if not await el.is_visible():
                        continue
                    txt = re.sub(r"\s+", " ", (await el.inner_text()).strip()).lower()
                    if txt != target:
                        continue
                    aria = (await el.get_attribute("aria-checked") or "").lower()
                    aria_sel = (await el.get_attribute("aria-selected") or "").lower()
                    aria_pressed = (await el.get_attribute("aria-pressed") or "").lower()
                    cls = (await el.get_attribute("class") or "").lower()
                    if aria in ("true","1") or aria_sel in ("true","1") or aria_pressed in ("true","1") or any(
                        x in cls for x in ("selected","active","checked","chosen")
                    ):
                        return True
            except Exception:
                pass

        # A successful answer can immediately advance the question, so verify that
        # the old question disappeared/changed.
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
            if await self.intervention(page) or self.completed((await page.locator("body").inner_text()).strip()):
                return True
            q = await self.current_question(page)
            if q and self.fingerprint(q) != old_fp:
                return True
            await asyncio.sleep(250 / 1000)
            elapsed += 250
        return False


    async def _click_semantic_yes_no(self, page, answer: str) -> bool:
        """Click the actual Yes/No answer control, including long labels."""
        target = re.sub(r"\s+", " ", str(answer).strip()).lower()
        if target not in {"yes", "no"}:
            return False

        selectors = [
            'button:visible',
            '[role="button"]:visible',
            '[role="radio"]:visible',
            '[role="option"]:visible',
            'label:visible',
            'input[type="button"]:visible',
            'input[type="radio"]:visible',
            '[aria-label]:visible'
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel)
                for i in range(await loc.count() - 1, -1, -1):
                    el = loc.nth(i)
                    if not await el.is_visible():
                        continue

                    parts = []
                    for attr in ("aria-label", "value", "title"):
                        v = await el.get_attribute(attr)
                        if v:
                            parts.append(v)

                    try:
                        parts.append(await el.inner_text())
                    except Exception:
                        pass

                    txt = re.sub(r"\s+", " ", " ".join(parts).strip()).lower()
                    if not txt:
                        continue

                    # Never treat action controls as Yes/No answers.
                    if txt in {
                        "save", "continue", "next", "submit",
                        "submit application", "apply", "apply now",
                        "finish", "done", "cancel", "back", "skip"
                    }:
                        continue

                    first = txt.split(" ", 1)[0].rstrip(",:.;!?")
                    if (
                        first == target
                        or txt.startswith(target + " ")
                        or txt.startswith(target + ",")
                        or txt.startswith(target + ":")
                        or txt.startswith(target + ".")
                    ):
                        try:
                            typ = (await el.get_attribute("type") or "").lower()
                            if typ == "radio":
                                try:
                                    await el.check(force=True)
                                except Exception:
                                    await el.click(force=True)
                            else:
                                await el.scroll_into_view_if_needed()
                                await el.click(force=True)
                            return True
                        except Exception:
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

    async def _verify_current_answer(self, page, expected):
        """Verify the live control reflects the answer before advancing."""
        if expected is None:
            return False
        exp=str(expected).strip().lower()
        try:
            selectors=(
                "[role='dialog']:visible input:not([type='hidden']),"
                "[role='dialog']:visible textarea,"
                "[role='dialog']:visible select,"
                "[role='dialog']:visible [contenteditable='true'],"
                "[class*='chat']:visible input:not([type='hidden']),"
                "[class*='chat']:visible textarea,"
                "[class*='chat']:visible select,"
                "[class*='chat']:visible [contenteditable='true']"
            )
            controls=page.locator(selectors)
            for i in range(await controls.count()):
                el=controls.nth(i)
                if not await el.is_visible(): continue
                try:
                    val=(await el.input_value()).strip().lower()
                except Exception:
                    try: val=(await el.inner_text()).strip().lower()
                    except Exception: val=""
                if val and (val==exp or exp in val or val in exp):
                    print(f"  ANSWER VERIFIED IN INPUT: {expected}")
                    return True

            selected=page.locator(
                "[role='dialog']:visible [aria-selected='true'],"
                "[role='dialog']:visible [aria-checked='true'],"
                "[role='dialog']:visible input:checked,"
                "[class*='chat']:visible [aria-selected='true'],"
                "[class*='chat']:visible [aria-checked='true'],"
                "[class*='chat']:visible input:checked"
            )
            for i in range(await selected.count()):
                el=selected.nth(i)
                if not await el.is_visible(): continue
                vals=[]
                try: vals.append(await el.inner_text())
                except Exception: pass
                for at in ("aria-label","value","data-value"):
                    v=await el.get_attribute(at)
                    if v: vals.append(v)
                if exp in " ".join(vals).lower():
                    print(f"  ANSWER VERIFIED AS SELECTED: {expected}")
                    return True

            # Button/chip answers sometimes have no ARIA state. Compare the
            # current visual answer text in the question panel.
            visible=page.locator(
                "[role='dialog']:visible button,"
                "[role='dialog']:visible [role='option'],"
                "[class*='chat']:visible button,"
                "[class*='chat']:visible [role='option']"
            )
            for i in range(await visible.count()):
                el=visible.nth(i)
                if not await el.is_visible(): continue
                txt=""
                try: txt=(await el.inner_text()).strip().lower()
                except Exception: pass
                cls=(await el.get_attribute("class") or "").lower()
                if txt and exp==txt and any(k in cls for k in ("active","selected","checked","chosen")):
                    print(f"  ANSWER VERIFIED AS ACTIVE OPTION: {expected}")
                    return True
        except Exception:
            pass
        return False

    async def click_continue(self, page):
        # The answer fill operation is authoritative for progression. Do not
        # block a correctly filled native Naukri answer on a brittle secondary
        # DOM verification check; proceed to the visible intermediate control.

        # Prefer true progression controls over Save when several are visible.
        # Some Naukri forms keep a Save button mounted permanently; clicking it
        # repeatedly does not move the questionnaire forward. Save remains the
        # final fallback when Continue/Next are unavailable.
        for name in ("Continue", "Next", "Save"):
            try:
                loc=page.get_by_role("button",name=re.compile(r"^"+re.escape(name)+r"$",re.I))
                for i in range(await loc.count()-1,-1,-1):
                    el=loc.nth(i)
                    if await el.is_visible() and not await el.is_disabled():
                        await el.scroll_into_view_if_needed()
                        await el.click(timeout=5000)
                        print(f"  CLICKED INTERMEDIATE CONTROL: {name}")
                        return True
            except Exception:
                pass
            try:
                loc=page.get_by_text(name,exact=True)
                for i in range(await loc.count()-1,-1,-1):
                    el=loc.nth(i)
                    if await el.is_visible():
                        await el.click(timeout=5000)
                        print(f"  CLICKED INTERMEDIATE CONTROL: {name}")
                        return True
            except Exception:
                pass

        if self.dry_run:
            print("  DRY_RUN=true: intermediate control not found; final submission remains blocked.")
        return False

    async def wait_stable(self, page):
        if page is None or page.is_closed():
            return False
        try:
            await asyncio.sleep(500 / 1000)
            return True
        except Exception as e:
            if "TargetClosed" in type(e).__name__ or "TargetClosed" in str(e):
                return False
            raise

    async def intervention(self, page):
        """Detect a real human/security challenge, not incidental page text."""
        try:
            b = re.sub(r"\s+", " ", (await page.locator("body").inner_text()).lower())
        except Exception:
            return False

        strong_phrases = (
            "enter the captcha", "captcha verification", "captcha required",
            "verify you are human", "verify you're human", "i'm not a robot",
            "one time password", "enter otp", "otp verification",
            "security verification required", "complete the security check",
            "security check required",
        )
        if any(x in b for x in strong_phrases):
            return True

        # A bare "captcha" is only a blocker when an actual visible challenge/input
        # is present. This avoids stopping on unrelated text in the application DOM.
        try:
            challenge = page.locator(
                "iframe:visible[src*='captcha' i], "
                "[id*='captcha' i]:visible, [class*='captcha' i]:visible, "
                "input[name*='captcha' i]:visible, input[id*='captcha' i]:visible, "
                "input[placeholder*='captcha' i]:visible, "
                "input[name*='otp' i]:visible, input[id*='otp' i]:visible"
            )
            if await challenge.count():
                return True
        except Exception:
            pass
        return False


    async def _next_search_page_url(self, page, current_url, page_number, max_pages):
        """Return Naukri's actual next-page URL, preferring rendered pagination."""

        try:
            links = await page.locator("a[href], button, [role='button']").evaluate_all(
                """els => els.map((e, i) => ({
                    i,
                    tag: e.tagName.toLowerCase(),
                    href: e.href || e.getAttribute('href') || '',
                    rel: (e.getAttribute('rel') || '').toLowerCase(),
                    text: (e.innerText || e.textContent || '').trim(),
                    aria: (e.getAttribute('aria-label') || '').trim(),
                    title: (e.getAttribute('title') || '').trim()
                }))"""
            )
        except Exception:
            links = []

        current = current_url.split("#", 1)[0]
        candidates = []
        for item in links:
            href = (item.get("href") or "").strip()
            label = " ".join([
                item.get("text") or "",
                item.get("aria") or "",
                item.get("title") or "",
                item.get("rel") or "",
            ]).strip().lower()
            if not href or "naukri.com" not in href.lower():
                continue
            if href.split("#", 1)[0] == current:
                continue

            # Prefer an explicit rel=next / Next pagination control.
            score = 0
            if item.get("rel") == "next":
                score += 100
            if re.search(r"\bnext\b", label):
                score += 90

            # Naukri commonly exposes page=N in pagination hrefs.
            if re.search(r"[?&]page=\d+", href, flags=re.I):
                score += 50

            if score:
                candidates.append((score, href.split("#", 1)[0]))

        if candidates:
            candidates.sort(key=lambda x: (-x[0], x[1]))
            next_url = candidates[0][1]
            print(f"  NEXT PAGE TARGET: {next_url}")
            return next_url

        print("  NEXT PAGE TARGET: none exposed by rendered pagination.")
        return None

    async def run_with_context(self, context, search_url):
        # SEARCH-CONTROLLER OWNERSHIP CONTRACT:
        # Never assume the last Chrome tab belongs to this agent. With a real
        # browser the user may have unrelated Naukri, Gmail, company, or other
        # tabs open. Reuse an existing Naukri tab only; otherwise create one
        # controller tab owned by this run. Job tabs are created separately by
        # process_job() and are never used as the search controller.
        live_pages = [p for p in context.pages if not p.is_closed()]
        page = None
        for candidate in reversed(live_pages):
            try:
                u = (candidate.url or '').lower()
                if 'naukri.com' in u:
                    page = candidate
                    break
            except Exception:
                continue
        controller_owned = False
        if page is None:
            try:
                page = await asyncio.wait_for(context.new_page(), timeout=15)
                controller_owned = True
            except Exception as e:
                print(f"  Could not create a Naukri search controller tab: {type(e).__name__}: {e}")
                return
        print(f"  SEARCH CONTROLLER: {'new owned tab' if controller_owned else 'existing Naukri tab'}")

        current_url = search_url
        page_number = 0

        while True:
            page_number += 1
            # Search pagination must continue independently of the application target.
            # The target limits real submissions, not job discovery/evaluation.
            if len(self.seen_urls) >= self.max_total_candidates:
                print(f"  Candidate scan cap reached ({self.max_total_candidates}); ending this role.")
                break

            print(f"\n  SEARCH PAGE {page_number}: {current_url}")
            try:
                await page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"  SEARCH PAGE LOAD FAILED: {type(e).__name__}: {e}")
                break
            print("  Search page render wait...")
            try:
                await asyncio.sleep(1800 / 1000)
            except Exception:
                pass

            await self.wait_stable(page)

            # Capture the actual next-page target BEFORE process_job navigates
            # the same tab to individual job pages.
            next_url = await self._next_search_page_url(
                page, current_url, page_number, None
            )

            raw_urls = await self.collect_job_urls(page)
            unique_urls = [u for u in dict.fromkeys(raw_urls) if u not in self.seen_urls]
            urls = await self._filter_applied_search_urls(page, unique_urls)
            applied_prefiltered = len(unique_urls) - len(urls)
            print(
                f"Search results exposed: {len(raw_urls)} | "
                f"Unique new jobs: {len(unique_urls)} | "
                f"Applied ignored before opening: {applied_prefiltered} | "
                f"New candidates: {len(urls)}"
            )

            for url in urls:
                if len(self.seen_urls) >= self.max_total_candidates:
                    print(f"  Candidate scan cap reached ({self.max_total_candidates}); ending this role.")
                    break

                # Persistent application history is the cross-run dedup gate.
                # Only jobs already recorded in applications.db are skipped;
                # the search page itself is never bulk-marked as seen.
                if seen(self.con, url):
                    self.seen_urls.add(url)
                    print(f"  DB DEDUP -> already processed: {url}")
                    continue

                self.seen_urls.add(url)

                print(f"\nJOB CANDIDATE: {url}")
                try:
                    # One broken/stalled job must never terminate the complete run.
                    # Keep the timeout finite and continue to the next fresh job tab.
                    outcome = await asyncio.wait_for(
                        self.process_job(context, url),
                        timeout=120,
                    )
                    if outcome in ("external_filled", "external_blocked", "external_error", "external"):
                        self.external_jobs_skipped += 1
                        if outcome == "external_filled":
                            self.external_jobs_filled += 1
                        elif outcome == "external_error":
                            self.external_jobs_errored += 1
                    elif outcome in ("low_match", "experience_mismatch"):
                        self.low_match_skipped += 1
                    elif outcome == "naukri_apply_error":
                        self.naukri_apply_errors += 1
                except asyncio.TimeoutError:
                    print(
                        "  JOB TIMEOUT: this job exceeded 120 seconds. "
                        "Leaving its owned tab open and continuing to the next job."
                    )
                except Exception as e:
                    print(f"  SKIPPED due to error: {type(e).__name__}: {e}")

            if not next_url:
                print(f"  Pagination ended after page {page_number}.")
                break

            # If Naukri exposes a pagination link that resolves to the same URL,
            # do not loop forever.
            if next_url.split("#", 1)[0] == current_url.split("#", 1)[0]:
                print("  Pagination target is unchanged; stopping safely.")
                break

            current_url = next_url

        print(
            f"\nROLE SUMMARY: Naukri-native={self.native_jobs_found}/{self.target_native_applications}, "
            f"external attempted={self.external_jobs_skipped} (filled={self.external_jobs_filled}, "
            f"errored={self.external_jobs_errored}), low-match skipped={self.low_match_skipped}, "
            f"Naukri apply errors={self.naukri_apply_errors}"
        )
