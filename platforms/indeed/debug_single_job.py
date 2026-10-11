"""Single Indeed job diagnostic entry point.

This script is intentionally small and diagnostic-only.  It attaches to an
already-running Chrome/CDP session, checks whether one supplied Indeed job URL
exposes a native Indeed Apply control, and then delegates the actual application
attempt to the existing production path:

    IndeedAgent.process_job()
      -> direct_apply_control()
      -> wait_for_application_ready()
      -> run_application()

It does not implement a replacement form engine and does not run the external
company-site flow.  External/non-native jobs are reported clearly and left open.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
import importlib.util

from playwright.async_api import async_playwright

PLATFORM_DIR = Path(__file__).resolve().parent
while str(PLATFORM_DIR) in sys.path:
    sys.path.remove(str(PLATFORM_DIR))
sys.path.insert(0, str(PLATFORM_DIR))

# The platform qa_engine adapter may add the project root to sys.path while
# indeed_agent.py is importing, which can otherwise make ``from storage`` pick
# the root storage.py instead of platforms/indeed/storage.py.  Pin only this
# debug process to the platform storage module; production code is unchanged.
_STORAGE_SPEC = importlib.util.spec_from_file_location(
    "storage", PLATFORM_DIR / "storage.py"
)
if _STORAGE_SPEC is None or _STORAGE_SPEC.loader is None:
    raise ImportError("Could not load Indeed platform storage module.")
_STORAGE_MODULE = importlib.util.module_from_spec(_STORAGE_SPEC)
_STORAGE_SPEC.loader.exec_module(_STORAGE_MODULE)
sys.modules["storage"] = _STORAGE_MODULE

from indeed_agent import IndeedAgent


DEFAULT_CDP_URL = "http://127.0.0.1:9222"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def _open_preflight_tab(context, agent, job_url):
    page = await asyncio.wait_for(context.new_page(), timeout=15)
    print(f"DIAG SINGLE JOB: opening supplied URL: {job_url}")
    await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
    await agent.wait_stable(page)
    print(f"DIAG SINGLE JOB: opened page title={(await page.title()).strip()!r}")
    print(f"DIAG SINGLE JOB: opened page url={page.url!r}")
    return page


async def _preflight_native_apply(agent, page, job_url):
    if not agent._is_valid_job_url(job_url):
        print(f"DIAG SINGLE JOB: invalid/synthetic Indeed job URL; stopping: {job_url}")
        return False

    if await agent.detect_blocker(page):
        print("DIAG SINGLE JOB: security/human verification detected on job page.")
        if not await agent.pause_for_human_verification(page, "single-job diagnostic"):
            print("DIAG SINGLE JOB: verification not cleared; stopping with tab left open.")
            return False
        await agent.wait_stable(page)

    if not await agent.is_indeed_url(page):
        print(f"DIAG SINGLE JOB: supplied URL navigated away from Indeed; external/non-native destination: {page.url}")
        print("DIAG SINGLE JOB: stopping without running external flow. Tab left open.")
        return False

    if await agent.apply_target_is_external(page):
        print("DIAG SINGLE JOB: external/company-site Apply detected.")
        print("DIAG SINGLE JOB: stopping without running external flow. Job tab left open.")
        return False

    control = await agent.direct_apply_control(page)
    if not control:
        print("DIAG SINGLE JOB: no native Indeed Apply control found.")
        print("DIAG SINGLE JOB: stopping. Job tab left open for inspection.")
        return False

    try:
        label = await agent._control_label(control)
    except Exception:
        label = ""
    print(f"DIAG SINGLE JOB: native Indeed Apply control found: {label!r}")
    return True


async def _run_forced_native_debug(context, agent, page, job_url):
    """Bypass JD eligibility only inside this diagnostic script.

    The native Apply sequence mirrors the production process_job() native block
    while reusing the existing direct_apply_control(), wait_for_application_ready(),
    and run_application() methods.  It deliberately does not call JDMatcher.
    """
    print("DIAG SINGLE JOB: --force-native-debug enabled; JD eligibility will not run in this diagnostic script.")
    control = await agent.direct_apply_control(page)
    if not control:
        print("DIAG SINGLE JOB: native Apply control disappeared before forced click. Tab left open.")
        return "native_apply_not_found"

    if agent.dry_run:
        print("DIAG SINGLE JOB: DRY_RUN=true; native Apply/form filling allowed, final Submit blocked.")

    pages_before = set(context.pages)
    try:
        await control.scroll_into_view_if_needed()
        await control.click(timeout=10000)
    except Exception:
        try:
            await control.click(timeout=5000, force=True)
        except Exception as exc:
            print(f"DIAG SINGLE JOB: APPLY CLICK FAILED: {type(exc).__name__}: {exc}. Leaving tab open.")
            return "apply_click_failed"

    agent.direct_applications += 1
    print(f"DIAG SINGLE JOB: *** APPLY WITH INDEED CLICKED ({agent.direct_applications}/{agent.target_direct_applications}) ***")

    application_page = page
    try:
        new_pages = [pg for pg in context.pages if not pg.is_closed() and pg not in pages_before]
        for candidate in reversed(new_pages):
            try:
                await candidate.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            if "indeed." not in ((candidate.url or "").lower()):
                continue
            application_page = candidate
            print(f"DIAG SINGLE JOB: APPLICATION TAB DETECTED: {application_page.url}")
            break
    except Exception:
        pass

    await agent.wait_for_application_ready(application_page, timeout_ms=20000)

    if await agent.detect_blocker(application_page):
        if not await agent.pause_for_human_verification(application_page, "application"):
            print("DIAG SINGLE JOB: application verification not cleared. Application tab left open.")
            return "blocked"

    print("DIAG SINGLE JOB: APPLICATION FORM ENGINE: scanning fields/questions...")
    status = await agent.run_application(application_page, job_url)
    print(f"DIAG SINGLE JOB: forced native run_application returned status={status!r}")
    print(f"DIAG SINGLE JOB: application tab left open for inspection: {application_page.url}")
    return status


async def run_single_job(job_url, cdp_url=DEFAULT_CDP_URL, force_native_debug=False):
    # Diagnostic runs should exercise the real Apply/form path but must not
    # final-submit.  Respect an explicit operator value, otherwise choose the
    # safe diagnostic default.
    if "DRY_RUN" not in os.environ:
        os.environ["DRY_RUN"] = "true"
        print("DIAG SINGLE JOB: DRY_RUN not set; defaulting to true for diagnostic safety.")

    async with async_playwright() as p:
        print(f"DIAG SINGLE JOB: connecting to existing Chrome CDP at {cdp_url}")
        browser = await asyncio.wait_for(p.chromium.connect_over_cdp(cdp_url), timeout=15)
        if not browser.contexts:
            raise RuntimeError("Connected to Chrome CDP, but no browser context exists.")
        context = browser.contexts[0]
        print(f"DIAG SINGLE JOB: attached. Existing tabs={len(context.pages)}")

        agent = IndeedAgent()
        preflight_page = await _open_preflight_tab(context, agent, job_url)
        native = await _preflight_native_apply(agent, preflight_page, job_url)
        if not native:
            return "not_native_indeed_apply"

        if force_native_debug:
            return await _run_forced_native_debug(context, agent, preflight_page, job_url)

        # Keep the real diagnostic run on the production path.  Close only the
        # preflight tab so the subsequent process_job() tab is unambiguous; if
        # the close fails, process_job() still snapshots tabs before clicking.
        try:
            await preflight_page.close()
        except Exception:
            pass

        print("DIAG SINGLE JOB: invoking existing IndeedAgent.process_job() path.")
        print("DIAG SINGLE JOB: expected path: process_job -> direct_apply_control -> wait_for_application_ready -> run_application")
        status = await agent.process_job(context, job_url)
        print(f"DIAG SINGLE JOB: process_job returned status={status!r}")
        print("DIAG SINGLE JOB: if the application stopped, the existing agent policy leaves the application tab open.")
        return status


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run one known Indeed job URL through the existing native Apply diagnostic path."
    )
    parser.add_argument("job_url", help="Indeed job URL, e.g. https://in.indeed.com/viewjob?jk=...")
    parser.add_argument(
        "--cdp-url",
        default=os.getenv("INDEED_CDP_URL", DEFAULT_CDP_URL),
        help=f"Chrome CDP endpoint (default: {DEFAULT_CDP_URL}, or INDEED_CDP_URL).",
    )
    parser.add_argument(
        "--force-native-debug",
        action="store_true",
        help=(
            "Diagnostic-only: after verifying a valid Indeed job with native Apply, "
            "bypass JD eligibility in this script and run the existing native "
            "Apply/application flow. Does not final-submit."
        ),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    return asyncio.run(run_single_job(args.job_url, args.cdp_url, args.force_native_debug))


if __name__ == "__main__":
    main()