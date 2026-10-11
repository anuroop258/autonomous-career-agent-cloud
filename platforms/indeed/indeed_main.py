import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus
from playwright.async_api import async_playwright
from application_engine import IndeedApplicationEngine

if hasattr(sys.stdout, "reconfigure"):
    # Chrome/CDP runs are commonly started from a legacy Windows console.
    # Keep status output from aborting on ordinary Unicode punctuation.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP_URL = "http://127.0.0.1:9222"
BASE = "https://in.indeed.com"

# Deterministic mode: external LLMs are disabled by default.
os.environ.setdefault("OLLAMA_ENABLED", "0")
BASE_DIR = Path(__file__).resolve().parent


def load_role_config():
    return json.loads((BASE_DIR / "role_config.json").read_text(encoding="utf-8"))


def build_search_plan():
    """Build a role-first search plan with no location filter.

    Job roles remain the primary dimension. Search spans all locations.
    Every job still has to pass the independent entry-level/experience and JD gates.
    """
    cfg = load_role_config()
    roles = [str(r).strip() for r in cfg.get("primary", []) if str(r).strip()]
    locations = [str(x).strip() for x in cfg.get("preferred_locations", []) if str(x).strip()]
    if not roles:
        raise RuntimeError("role_config.json has no primary job roles configured.")
    if not locations:
        locations = [""]
    plan = []
    seen = set()
    for role in roles:
        for location in locations:
            key = (role.lower(), location.lower())
            if key in seen:
                continue
            seen.add(key)
            query = quote_plus(role)
            url = f"{BASE}/jobs?q={query}"
            if location:
                url += f"&l={quote_plus(location)}"
            plan.append({"role": role, "location": location, "url": url})
    return plan


def build_role_urls():
    return [item["url"] for item in build_search_plan()]


async def main():
    print("INDEED AGENT: platform-specific Indeed application flow")
    print("SEARCH STRATEGY: roles across all locations → entry-level/experience gate → JD match → Apply → leave open → next job")

    async with async_playwright() as p:
        print(f"Connecting ONLY to existing Chrome at {CDP_URL} ...")
        try:
            browser = await asyncio.wait_for(
                p.chromium.connect_over_cdp(CDP_URL),
                timeout=15,
            )
        except asyncio.TimeoutError as e:
            raise RuntimeError(
                f"Timed out connecting to Chrome CDP at {CDP_URL}. "
                "Start the matching Chrome with --remote-debugging-port=9222 and retry."
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Could not connect to Chrome CDP at {CDP_URL}. "
                "Start the matching Chrome with --remote-debugging-port=9222 and retry."
            ) from e
        if not browser.contexts:
            raise RuntimeError("Connected to Chrome, but no browser context exists.")
        context = browser.contexts[0]
        print(f"Attached. Existing tabs: {len(context.pages)}")
        engine = IndeedApplicationEngine()

        if len(sys.argv) > 1:
            await engine.run(context, sys.argv[1])
        else:
            plan = build_search_plan()
            cfg = load_role_config()
            print(f"SEARCH PLAN: {len(plan)} role/location search combinations")
            print("PREFERRED ROLES:")
            for role in cfg.get("primary", []):
                print(f"  - {role}")
            print(
                "ENTRY-LEVEL / EXPERIENCE: accepted ranges include 0-1, 0-2, and 0-3 years; "
                "minimum-experience-only requirements remain rejected."
            )
            print("LOCATION FILTER: none (all locations)")

            for item in plan:
                if engine.agent.direct_applications >= engine.agent.target_direct_applications:
                    break
                print(f"\n=== ROLE SEARCH: {item['role']} ===")
                print(f"    {item['url']}")
                await engine.run(context, item["url"])

        print(
            f"\nFINAL: Indeed-direct={engine.agent.direct_applications}/{engine.agent.target_direct_applications} "
            f"| external attempted={engine.agent.external_applications} filled={engine.agent.external_filled} errors={engine.agent.external_errors} "
            f"| low-match skipped={engine.agent.low_match_skipped} "
            f"| tabs left open={sum(1 for p in context.pages if not p.is_closed())}"
        )


if __name__ == "__main__":
    asyncio.run(main())
