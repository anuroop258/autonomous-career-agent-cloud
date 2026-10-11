"""Export the logged-in portal session from the expected local Chrome CDP port.

The JSON output is sensitive and must only be placed in the encrypted private bundle.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

PORTS = {"naukri": 9222, "indeed": 9222, "linkedin": 9232, "shine": 9222, "timesjobs": 9222, "glassdoor": 9222}
DOMAINS = {
    "naukri": ("naukri.com",), "indeed": ("indeed.com",), "linkedin": ("linkedin.com",),
    "shine": ("shine.com",), "timesjobs": ("timesjobs.com",), "glassdoor": ("glassdoor.co.in", "glassdoor.com"),
}


def belongs(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("portal", choices=sorted(PORTS))
    ap.add_argument("--output", default="", help="Defaults to cloud_private/sessions/<portal>.json")
    args = ap.parse_args()
    output = Path(args.output) if args.output else Path("cloud_private") / "sessions" / f"{args.portal}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORTS[args.portal]}", timeout=8000)
        try:
            if not browser.contexts: raise RuntimeError("Connected Chrome has no browser context")
            state = browser.contexts[0].storage_state()
        finally:
            browser.close()
    domains = DOMAINS[args.portal]
    state["cookies"] = [c for c in state.get("cookies", []) if belongs(c.get("domain", "").lstrip("."), domains)]
    state["origins"] = [o for o in state.get("origins", []) if belongs(urlparse(o.get("origin", "")).hostname or "", domains)]
    if not state["cookies"] and not state["origins"]:
        raise RuntimeError("No session state for this portal found. Sign in first using the Chrome profile on the matching CDP port.")
    output.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    try: output.chmod(0o600)
    except OSError: pass
    print(f"Saved {args.portal} session locally to {output}")
    print("DO NOT commit this plaintext file. Encrypt it with tools/private_bundle.py before uploading anything.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
