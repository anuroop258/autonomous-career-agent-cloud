import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from src.application.common.ai_form_engine import AIFormEngine

ROOT = Path(__file__).resolve().parents[1]

HTML = """
<!doctype html><html><body>
<section>
  <h2>EDUCATION</h2>
  <div>
    <label for="highest">Highest Qualification</label>
    <select id="highest" name="highest_qualification">
      <option value="">Select...</option>
      <option value="12">High school (12th)</option>
      <option value="diploma">Diploma</option>
      <option value="be">B.Tech / B.E.</option>
      <option value="bsc">B.Sc</option>
    </select>
  </div>
  <div><label for="branch">Field / Branch</label><input id="branch" name="branch"></div>
  <div><label for="college">College / University</label><input id="college" name="college"></div>
  <div><label for="cgpa">CGPA / %</label><input id="cgpa" name="cgpa"></div>
  <div><label for="grad">Graduation Year</label><input id="grad" name="graduation_year"></div>
  <div><label for="study-year">Current Year of Study</label><input id="study-year" name="current_year_of_study"></div>
  <div><label for="studying">I'm currently studying — still pursuing this qualification.</label><input id="studying" name="currently_studying" type="checkbox"></div>
</section>
</body></html>
"""


def test_education_section_only_fills_the_requested_fields():
    async def run():
        profile = __import__("json").loads((ROOT / "profile.json").read_text(encoding="utf-8"))
        engine = AIFormEngine(profile=profile)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
            page = await browser.new_page()
            await page.set_content(HTML)
            engine.page = page
            await engine.inspect_form()
            result = await engine.fill_safe_fields()

            assert await page.locator("#highest").input_value() == "be"
            assert await page.locator("#branch").input_value() == "Electronics and Communication Engineering"
            assert await page.locator("#college").input_value() == "Vasavi College of Engineering"
            assert await page.locator("#cgpa").input_value() == "6.8"
            assert await page.locator("#grad").input_value() == "2026"
            assert await page.locator("#study-year").input_value() == "Final year"
            assert await page.locator("#studying").is_checked()
            assert result["fields_filled"] == 7
            await browser.close()

    asyncio.run(run())
