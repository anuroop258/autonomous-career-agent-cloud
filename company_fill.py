from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent

PORTS = {
    "linkedin": 9232,
    "indeed": 9222,
    "naukri": 9222,
}


def _load_profile(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _default_profile(platform: str) -> Path:
    platform_profile = ROOT / "platforms" / platform / "profile.json"
    if platform_profile.exists():
        return platform_profile
    root_profile = ROOT / "profile.json"
    if root_profile.exists():
        return root_profile
    return platform_profile


def _default_resume(platform: str, profile: dict) -> Path:
    configured = profile.get("resume_path")
    if isinstance(configured, str) and configured.strip():
        p = Path(configured.strip())
        if not p.is_absolute():
            p = ROOT / p
        if p.exists():
            return p.resolve()

    documents = profile.get("documents") or {}
    if isinstance(documents, dict):
        configured = documents.get("resume")
        if isinstance(configured, str) and configured.strip():
            p = Path(configured.strip())
            if not p.is_absolute():
                p = ROOT / p
            if p.exists():
                return p.resolve()
        elif isinstance(configured, dict):
            candidate = configured.get("path")
            if isinstance(candidate, str) and candidate.strip():
                p = Path(candidate.strip())
                if not p.is_absolute():
                    p = ROOT / p
                if p.exists():
                    return p.resolve()

    resume = ROOT / "platforms" / platform / "resume" / "resume.pdf"
    if resume.exists():
        return resume.resolve()

    resume = ROOT / "resume" / "resume.pdf"
    return resume.resolve()


async def run(url: str, platform: str, port: int, profile_path: Path, resume_path: Path, submit: bool) -> int:
    # Canonical company-site engine already used by the existing platform agents.
    from src.application.common.company_website_agent import CompanyWebsiteAgent

    # Gemini stays enabled (per .env) so unknown company-site questions get answered.
    os.environ["OLLAMA_ENABLED"] = "0"
    os.environ["COMPANY_WEBSITE_DRY_RUN"] = "0" if submit else "1"

    print("COMPANY SITE DIRECT FILL")
    print(f"PLATFORM: {platform}")
    print(f"CDP PORT: {port}")
    print(f"URL: {url}")
    print(f"PROFILE: {profile_path}")
    print(f"RESUME: {resume_path}")
    print(f"SUBMIT: {submit}")
    print(f"Connecting ONLY to existing Chrome at http://127.0.0.1:{port} ...")

    async with async_playwright() as playwright:
        browser = await asyncio.wait_for(
            playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}"),
            timeout=15,
        )
        if not browser.contexts:
            raise RuntimeError("Connected to Chrome, but no browser context exists.")

        context = browser.contexts[0]
        print(f"Attached. Existing tabs: {len(context.pages)}")

        page = None
        target = url.split("#", 1)[0].rstrip("/")
        for candidate in context.pages:
            try:
                current = (candidate.url or "").split("#", 1)[0].rstrip("/")
                if current == target:
                    page = candidate
                    break
            except Exception:
                continue

        if page is None:
            page = await context.new_page()

        agent = CompanyWebsiteAgent(
            dry_run=not submit,
            profile_path=str(profile_path),
            resume_path=str(resume_path),
        )

        result = await agent.apply(
            page,
            url,
            application_opened=False,
        )

        print("\n" + "=" * 70)
        print("COMPANY SITE RESULT")
        print("=" * 70)
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        print(f"\nAPPLICATION TAB LEFT OPEN: {page.url}")
        print("Chrome remains open; Playwright only disconnects.")

        status = str(result.get("status", "")).upper()
        return 1 if status in {"FAILED", "FORM_ERROR", "QUESTION_UNRESOLVED"} else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Directly fill one company application URL using the existing CompanyWebsiteAgent."
    )
    parser.add_argument("url", help="Exact company application URL")
    parser.add_argument("--platform", choices=["linkedin", "indeed", "naukri"], default="linkedin")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--resume", default=None)
    parser.add_argument("--submit", action="store_true", help="Allow final submit; default is fill-only")
    args = parser.parse_args()

    port = args.port or PORTS[args.platform]
    profile_path = Path(args.profile).resolve() if args.profile else _default_profile(args.platform)
    profile = _load_profile(profile_path)
    resume_path = Path(args.resume).resolve() if args.resume else _default_resume(args.platform, profile)

    return asyncio.run(
        run(
            args.url,
            args.platform,
            port,
            profile_path,
            resume_path,
            args.submit,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
