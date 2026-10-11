import asyncio
import sys
from platforms.timesjobs.timesjobs_agent import TimesJobsAgent, ROOT, PLATFORM_DIR
from playwright.async_api import async_playwright
import os


async def main():
    port = int(os.environ.get("TIMESJOBS_CDP_PORT", "9222"))
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        if not browser.contexts:
            raise RuntimeError("Connected to Chrome, but no browser context exists.")
        context = browser.contexts[0]
        agent = TimesJobsAgent(ROOT, PLATFORM_DIR)
        target = sys.argv[1] if len(sys.argv) > 1 else None
        await agent.run(context, target=target)
        print(f"FINAL: applied={agent.applied}/{agent.target_applications} processed={agent.processed} skipped={agent.skipped} errors={agent.errors}")


if __name__ == "__main__":
    asyncio.run(main())
