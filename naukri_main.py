import asyncio
import json
import os
import sys
from urllib.parse import quote_plus
from playwright.async_api import async_playwright
from platforms.naukri.application_engine import NaukriApplicationEngine

CDP_URL = "http://127.0.0.1:9222"

# Deterministic mode: external LLMs are disabled by default.
os.environ.setdefault("OLLAMA_ENABLED", "0")
BASE = "https://www.naukri.com"

def build_role_urls():
    cfg=json.load(open("role_config.json",encoding="utf-8"))
    urls=[]
    for role in cfg["primary"]:
        # Naukri search pages accept role text in the slug for common searches.
        slug=role.lower().replace("/","-").replace("&","and").replace(" ","-")
        urls.append(f"{BASE}/{slug}-jobs")
    return urls

async def main():
    print("QA ENGINE: v27 — clean consolidated universal flow")
    async with async_playwright() as p:
        print(f"Connecting ONLY to existing Chrome at {CDP_URL} ...")
        try:
            browser=await asyncio.wait_for(p.chromium.connect_over_cdp(CDP_URL), timeout=15)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"Timed out connecting to Chrome CDP at {CDP_URL}.") from exc
        except Exception as exc:
            raise RuntimeError(f"Could not connect to Chrome CDP at {CDP_URL}: {exc}") from exc
        if not browser.contexts:
            raise RuntimeError("Connected to Chrome, but no browser context exists.")
        context=browser.contexts[0]
        print(f"Attached. Existing tabs: {len(context.pages)}")
        engine=NaukriApplicationEngine()

        if len(sys.argv)>1:
            await engine.run(context, sys.argv[1])
        else:
            for search_url in build_role_urls():
                if engine.agent.native_jobs_found >= engine.agent.target_native_applications:
                    break
                print(f"\n=== ROLE SEARCH: {search_url} ===")
                await engine.run(context, search_url)

if __name__=="__main__":
    asyncio.run(main())
