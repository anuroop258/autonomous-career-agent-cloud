
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.application.common.adaptive_form_runtime import FormObserver
from src.application.common.ai_form_engine import AIFormEngine
from src.application.common.profile_reasoner import ProfileReasoner


HTML = """
<!doctype html>
<html><body>
<div class="grid">
  <div class="field"><label>Name *</label><input name="name" id="name"></div>
  <div class="field"><label>Email *</label><input name="email" id="email" type="email"></div>
  <div class="field"><label>Age *</label><input name="age" id="age"></div>
  <div class="field"><label>City *</label><input name="city" id="city"></div>
  <div class="field"><label>Position *</label><select name="position" id="position">
    <option value="">-- Select Position --</option>
    <option>Generative AI Engineer</option>
  </select></div>
</div>
</body></html>
"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        page = await browser.new_page()
        await page.set_content(HTML)

        observer = FormObserver()
        snap = await observer.snapshot_scope(page)
        by_id = {x["id"]: x for x in snap}

        assert by_id["email"]["label"] == "Email *", by_id["email"]
        assert by_id["age"]["label"] == "Age *", by_id["age"]
        assert by_id["city"]["label"] == "City *", by_id["city"]
        assert by_id["position"]["label"] == "Position *", by_id["position"]

        engine = AIFormEngine(page=page, profile={})
        assert engine._classify(
            name="email", field_id="email", field_type="email",
            label="Email *", placeholder="", aria_label="", tag="input",
            role="", context="", options=[]
        ) == "email"

        # A bare Age label must never become Email because Email happened to
        # appear earlier in a sibling column.
        age_semantic = engine._classify(
            name="age", field_id="age", field_type="number",
            label=by_id["age"]["label"], placeholder="", aria_label="",
            tag="input", role="", context="", options=[]
        )
        assert age_semantic == "unknown", age_semantic

        # Position must remain a job-role/select field, not inherit Email.
        position_semantic = engine._classify(
            name="position", field_id="position", field_type="",
            label=by_id["position"]["label"], placeholder="", aria_label="",
            tag="select", role="", context="", options=[]
        )
        assert position_semantic == "job_role", position_semantic

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
    print("PASS: external two-column label routing")
