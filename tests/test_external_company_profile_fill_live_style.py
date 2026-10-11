
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.application.common.company_website_agent import CompanyWebsiteAgent


HTML = """
<!doctype html><html><body>
<div><label>First Name *</label><input name="firstname" id="firstname"></div>
<div><label>Last Name *</label><input name="lastname" id="lastname"></div>
<div><label>Email *</label><input name="email" id="email"></div>
<div><label>Age *</label><input name="age" id="age"></div>
<div><label>City *</label><input name="city" id="city"></div>
<div><label>Position *</label><select name="position" id="position">
  <option value="">-- Select Position --</option>
  <option value="genai">Generative AI Engineer</option>
  <option value="ai">AI Engineer</option>
</select></div>
<div><label>Expected Salary *</label><input name="expected_salary" id="expected-salary"></div>
<div><label>Notice Period *</label><input name="notice_period" id="notice-period"></div>
<div><label>Website (if any) OR Links</label><input name="links" id="links"></div>
<div><label>Tell us about your relevant Experience *</label><textarea name="relevant_experience" id="relevant-experience"></textarea></div>
</body></html>
"""


async def main():
    profile = str(ROOT / "profile.json")
    agent = CompanyWebsiteAgent(profile_path=profile)
    agent.load_profile()
    agent.profile["application_job_role"] = "Generative AI Engineer"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        page = await browser.new_page()
        await page.set_content(HTML)

        filled = await agent.fill_external_profile_fields_deterministically(page)
        assert filled == 8, filled

        assert await page.locator("#firstname").input_value() == "Anuroop"
        assert await page.locator("#lastname").input_value() == "Kudire"
        assert await page.locator("#email").input_value() == "anuroop954@gmail.com"
        assert await page.locator("#city").input_value() == "Hyderabad"
        assert await page.locator("#position").input_value() == "genai"
        assert await page.locator("#expected-salary").input_value() == "400000"
        assert await page.locator("#notice-period").input_value() == "0"
        assert "linkedin.com/in/anuroop-kudire-b7a322268" in await page.locator("#links").input_value()

        # No age fact -> remain unresolved.
        assert await page.locator("#age").input_value() == ""

        # Narrative relevant experience must not inherit the numeric 0 years.
        assert await page.locator("#relevant-experience").input_value() == ""

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
    print("PASS: external company profile deterministic live-style form")
