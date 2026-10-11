import asyncio
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
PLATFORM_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from shine_agent import ShineAgent  # noqa: E402


async def main():
    port = int(os.environ.get("SHINE_CDP_PORT", "9222"))
    cdp_url = f"http://127.0.0.1:{port}"
    print("SHINE AGENT: backend-only native Shine flow")
    print(f"Connecting ONLY to existing Chrome at {cdp_url} ...")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError("Connected to Chrome, but no browser context exists.")
        context = browser.contexts[0]
        print(f"Attached. Existing tabs: {len(context.pages)}")
        agent = ShineAgent(ROOT, PLATFORM_DIR)
        target = sys.argv[1] if len(sys.argv) > 1 else None
        await agent.run(context, target=target)
        print(
            f"FINAL: applied={agent.direct_applications}/{agent.target_direct_applications} "
            f"processed={agent.processed_candidates} skipped={agent.skipped_candidates} "
            f"errors={agent.errors} tabs_open={sum(1 for page in context.pages if not page.is_closed())}"
        )


if __name__ == "__main__":
    asyncio.run(main())
