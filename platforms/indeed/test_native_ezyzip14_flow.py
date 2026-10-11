import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from playwright.async_api import async_playwright

from platforms.indeed.indeed_agent import IndeedAgent


HTML = """
<!doctype html><html><body>
<div id="app">
  <div><label for="website">Website</label><input id="website"></div>
  <fieldset>
    <legend>Do you have RAG experience?</legend>
    <label><input type="radio" name="rag" value="Yes">Yes</label>
    <label><input type="radio" name="rag" value="No">No</label>
  </fieldset>
  <div><label for="salary">Current salary</label><input id="salary"></div>
  <button id="next">Next</button>
</div>
<script>
const next = document.getElementById('next');
next.onclick = () => {
  if (!document.getElementById('website').value) return;
  if (!document.querySelector('input[name="rag"]:checked')) return;
  if (!document.getElementById('salary').value) return;
  document.getElementById('app').innerHTML = '<button id="submit">Submit application</button>';
  document.getElementById('submit').onclick = () => document.body.innerText = 'Your application has been submitted';
};
</script>
</body></html>
"""


class Engine:
    def evidence(self, _q):
        return "deterministic test evidence"

    def answer(self, q, options):
        q = q.lower()
        if "website" in q:
            return "https://example.test", "candidate.website", "text"
        if "rag" in q:
            return "Yes", "skills.RAG", "yes_no"
        if "salary" in q:
            return "0", "compensation.current_ctc", "number"
        raise AssertionError((q, options))


class QuestionAgent(IndeedAgent):
    def __init__(self):
        os.environ["DRY_RUN"] = "false"
        super().__init__()
        self.engine = Engine()

    async def detect_blocker(self, _page):
        return False

    async def _is_indeed_review_state(self, _page, _body):
        return False

    async def _detect_native_route(self, _page):
        return "questions_to_submit"

    async def _handle_direct_submit(self, _page):
        return None

    async def _has_question_progression_control(self, page):
        return await page.get_by_role("button", name="Next").count() > 0

    async def _has_final_submit_control(self, page):
        return await page.get_by_role("button", name="Submit application").count() > 0

    def completed(self, body):
        return "Your application has been submitted" in body


def main():
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
            try:
                page = await browser.new_page()
                await page.set_content(HTML)
                agent = QuestionAgent()
                status = await agent.run_application(page, "https://in.indeed.com/viewjob?jk=test")
                assert status == "applied", status
                body = await page.locator("body").inner_text()
                assert "submitted" in body.lower()
            finally:
                await browser.close()

    asyncio.run(run())
    print("Indeed ezyZip(14) native field-flow integration: PASS")


if __name__ == "__main__":
    main()
