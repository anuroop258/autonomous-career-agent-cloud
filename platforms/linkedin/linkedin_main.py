import asyncio
import json
import os
import sys
from urllib.parse import quote_plus
from playwright.async_api import async_playwright
from application_engine import LinkedInApplicationEngine

CDP_URL = "http://127.0.0.1:9232"

# Deterministic mode: external LLMs are disabled by default.
os.environ.setdefault("OLLAMA_ENABLED", "0")


def build_search_urls():
    cfg = json.load(open("linkedin_config.json", encoding="utf-8"))

    urls = []

    # No job-search location filter: search across all locations.
    # Keep all other LinkedIn search filters unchanged.
    for role in cfg.get("primary", []):
        urls.append(
            "https://www.linkedin.com/jobs/search/?keywords="
            + quote_plus(role)
            + "&f_TPR=r604800&f_E=2"
        )

    return urls


async def main():
    print("LINKEDIN AGENT — exact Naukri flow adapter")
    print(f"Connecting ONLY to existing Chrome at {CDP_URL} ...")
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        import os
        os.environ["LINKEDIN_DRY_RUN"] = "true"
        os.environ["COMPANY_WEBSITE_DRY_RUN"] = "true"
        sys.argv = [a for a in sys.argv if a != "--dry-run"]

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        if not browser.contexts:
            raise RuntimeError("Connected to Chrome, but no browser context exists.")
        context = browser.contexts[0]
        print(f"Attached. Existing tabs: {len(context.pages)}")

        # The facade owns the platform-specific LinkedInAgent.
        engine = LinkedInApplicationEngine()

        if len(sys.argv) > 1:
            await engine.run(context, sys.argv[1])
        else:
            for url in build_search_urls():
                # Counters belong to the underlying LinkedInAgent, not the facade.
                if engine.agent.native_applications >= engine.agent.target_applications:
                    break
                await engine.run(context, url)


if __name__ == "__main__":
    asyncio.run(main())
