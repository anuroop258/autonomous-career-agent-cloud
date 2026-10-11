import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from platforms.indeed.indeed_agent import IndeedAgent


DIRECT_HTML = """
<!doctype html><html><body>
  <h1>Review your application</h1>
  <button id="submit">Submit application</button>
  <script>
    document.getElementById('submit').onclick = () => {
      document.body.innerText = 'Your application has been submitted';
    };
  </script>
</body></html>
"""

QUESTIONS_HTML = """
<!doctype html><html><body>
  <div id="app">
    <label for="q1">Why do you want this role?</label>
    <textarea id="q1"></textarea>
    <button id="next">Next</button>
  </div>
  <script>
    document.getElementById('next').onclick = () => {
      const v = document.getElementById('q1').value.trim();
      if (!v) return;
      document.getElementById('app').innerHTML = `
        <label for="q2">Describe your AI experience.</label>
        <textarea id="q2"></textarea>
        <button id="next2">Next</button>`;
      document.getElementById('next2').onclick = () => {
        const v2 = document.getElementById('q2').value.trim();
        if (!v2) return;
        document.getElementById('app').innerHTML = `<button id="submit">Submit application</button>`;
        document.getElementById('submit').onclick = () => {
          document.body.innerText = 'Your application has been submitted';
        };
      };
    };
  </script>
</body></html>
"""


async def _browser():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
    return p, browser


def main():
    async def run():
        # Route 1: direct submit.
        p, browser = await _browser()
        try:
            page = await browser.new_page()
            await page.set_content(DIRECT_HTML)
            agent = IndeedAgent()
            status = await agent.run_application(page, "https://in.indeed.com/viewjob?jk=direct")
            assert status == "applied", status
            assert "submitted" in (await page.locator("body").inner_text()).lower()
        finally:
            await browser.close()
            await p.stop()

        # Route 2: answer questions, Next until final Submit.
        p, browser = await _browser()
        try:
            page = await browser.new_page()
            await page.set_content(QUESTIONS_HTML)
            agent = IndeedAgent()

            # Keep the reasoner deterministic for the test surface.
            def answer(q, options):
                return ("I want to apply my AI and software engineering skills to the role.", "q", "text")
            agent.engine.answer = answer
            agent.engine.evidence = lambda q: "deterministic test evidence"

            status = await agent.run_application(page, "https://in.indeed.com/viewjob?jk=questions")
            assert status == "applied", status
            assert "submitted" in (await page.locator("body").inner_text()).lower()
        finally:
            await browser.close()
            await p.stop()

    asyncio.run(run())
    print("PASS: Indeed native direct-submit and questions-to-submit routes")


if __name__ == "__main__":
    main()
