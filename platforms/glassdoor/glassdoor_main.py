import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus
from playwright.async_api import async_playwright
try:
    from .application_engine import GlassdoorApplicationEngine
except ImportError:
    from application_engine import GlassdoorApplicationEngine

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9222"
BASE = "https://www.glassdoor.co.in"
BASE_DIR = Path(__file__).resolve().parent
os.environ.setdefault("OLLAMA_ENABLED", "0")

def load_role_config():
    return json.loads((BASE_DIR / "role_config.json").read_text(encoding="utf-8"))

def build_search_url(role: str) -> str:
    # Mirrors the India search shape visible in the supplied recording.
    return f"{BASE}/Job/jobs.htm?sc.keyword={quote_plus(role)}&locT=C&locId=115&applicationType=1"

def build_search_plan():
    cfg=load_role_config()
    roles=[str(x).strip() for x in cfg.get("primary",[]) if str(x).strip()]
    if not roles:
        raise RuntimeError("role_config.json has no primary roles")
    return [{"role":r,"url":build_search_url(r)} for r in roles]

async def main():
    print("GLASSDOOR AGENT: Glassdoor search + Easy Apply -> Indeed SmartApply native flow")
    print("EXTERNAL ROUTE: click Apply -> Skip for now -> leave external destination open")
    async with async_playwright() as p:
        print(f"Connecting ONLY to existing Chrome at {CDP_URL} ...")
        browser=await asyncio.wait_for(p.chromium.connect_over_cdp(CDP_URL),timeout=15)
        if not browser.contexts:
            raise RuntimeError("Connected to Chrome, but no browser context exists.")
        context=browser.contexts[0]
        print(f"Attached. Existing tabs: {len(context.pages)}")
        engine=GlassdoorApplicationEngine()
        cfg=load_role_config()
        plan=build_search_plan()
        print(f"SEARCH PLAN: {len(plan)} role searches")
        for item in plan:
            if engine.agent.direct_applications >= engine.agent.target_direct_applications:
                break
            print(f"\
=== ROLE SEARCH: {item['role']} ===")
            print(f"    {item['url']}")
            await engine.run(context,item['url'])
        print(f"\
FINAL: native={engine.agent.direct_applications}/{engine.agent.target_direct_applications} | external_skipped={engine.agent.external_skipped} | low-match={engine.agent.low_match_skipped} | tabs left open={sum(1 for p in context.pages if not p.is_closed())}")

if __name__ == "__main__":
    asyncio.run(main())
