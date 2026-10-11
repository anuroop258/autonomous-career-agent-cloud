import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'platforms' / 'indeed'))
from indeed_agent import IndeedAgent


HTML = r'''
<!doctype html>
<html><body>
  <section id="resume">
    <h2>Resume</h2>
    <button id="edit">Edit</button>
    <div id="cv-options">CV options</div>
    <div id="menu" style="display:block">
      <button id="upload">Upload a different file</button>
    </div>
    <input id="file" type="file" style="display:none">
    <button id="continue">Continue</button>
    <button id="submit" style="display:block">Submit application</button>
  </section>
  <script>
    document.getElementById('edit').onclick = () => {};
    document.getElementById('cv-options').onclick = () => {};
    document.getElementById('upload').onclick = () => document.getElementById('file').click();
    document.getElementById('continue').onclick = () => {};
    document.getElementById('submit').onclick = () => {
      document.body.innerText = 'Your application has been submitted';
    };
  </script>
</body></html>
'''


class FakePage:
    url = 'https://smartapply.indeed.com/beta/indeedapply/form/review-module'


def main():
    async def run():
        agent = IndeedAgent()
        assert await agent._is_indeed_review_state(FakePage(), '') is True

        pdf = ROOT / 'test_no_questions_resume.pdf'
        pdf.write_bytes(b'%PDF-1.4 test')
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
                page = await browser.new_page()
                await page.set_content(HTML)
                agent.current_resume_path = str(pdf)
                agent._indeed_resume_replaced = True

                # This is the state that previously became `no_questions` and
                # left the native review module without proceeding to Submit.
                status = await agent.run_application(page, 'https://in.indeed.com/rc/clk?jk=test')
                assert status == 'applied', status
                assert 'application has been submitted' in (await page.locator('body').inner_text()).lower()
                await browser.close()
        finally:
            pdf.unlink(missing_ok=True)

    asyncio.run(run())


if __name__ == '__main__':
    main()
    print('PASS: Indeed no-question review state proceeds to submit')
