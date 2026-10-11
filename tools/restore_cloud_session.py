"""Restore a locally exported Playwright storage_state into the running CDP browser."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

PORTS = {"naukri": 9222, "indeed": 9222, "linkedin": 9232, "shine": 9222, "timesjobs": 9222, "glassdoor": 9222}
DOMAINS = {
    "naukri": ("naukri.com",), "indeed": ("indeed.com",), "linkedin": ("linkedin.com",),
    "shine": ("shine.com",), "timesjobs": ("timesjobs.com",), "glassdoor": ("glassdoor.co.in", "glassdoor.com"),
}

def belongs(host, domains): return any(host == d or host.endswith("." + d) for d in domains)

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--portal",choices=sorted(PORTS),required=True); ap.add_argument("--state",type=Path,required=True); args=ap.parse_args()
    if not args.state.is_file(): raise FileNotFoundError(f"Session state not found: {args.state}")
    state=json.loads(args.state.read_text(encoding="utf-8")); domains=DOMAINS[args.portal]
    cookies=[c for c in state.get("cookies",[]) if belongs(str(c.get("domain","")).lstrip("."),domains)]
    origins=[o for o in state.get("origins",[]) if belongs(urlparse(o.get("origin","")).hostname or "",domains)]
    if not cookies and not origins: raise RuntimeError("Encrypted bundle has no cookies/localStorage for the selected portal.")
    with sync_playwright() as p:
        browser=p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORTS[args.portal]}",timeout=10000)
        try:
            if not browser.contexts: raise RuntimeError("Chrome CDP connected without a browser context")
            context=browser.contexts[0]
            if cookies: context.add_cookies(cookies)
            for item in origins:
                origin=str(item.get("origin", ""))
                parsed=urlparse(origin)
                if parsed.scheme not in {"http","https"} or not parsed.hostname or not belongs(parsed.hostname,domains): continue
                page=context.new_page()
                try:
                    try: page.goto(origin, wait_until="domcontentloaded", timeout=25000)
                    except PlaywrightTimeoutError: pass
                    entries=item.get("localStorage", [])
                    if entries:
                        page.evaluate("items => { for (const item of items) localStorage.setItem(item.name, item.value); }", entries)
                finally:
                    try: page.close()
                    except Exception: pass
            print(f"Restored cookie/localStorage state for {args.portal} into remote Chromium.")
        finally:
            browser.close()
    return 0

if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"Session restore failed: {exc}", file=sys.stderr); raise SystemExit(1)
