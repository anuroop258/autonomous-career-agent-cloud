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
  <section id="contact"><h2>Contact</h2><button>Edit</button></section>
  <section id="resume">
    <h2>Resume</h2>
    <a id="resume-edit">Edit</a>
    <div id="cv-card">
      <div id="cv-options">CV options</div>
      <div id="menu" style="display:none">
        <button id="upload-different" type="button">Upload a different file</button>
      </div>
      <input id="resume-file" type="file" style="display:none" />
    </div>
  </section>
  <button id="continue" style="display:none">Continue</button>
  <script>
    const edit = document.getElementById('resume-edit');
    edit.addEventListener('click', () => {
      document.body.dataset.resumeSelection = 'true';
    });
    document.getElementById('cv-options').addEventListener('click', () => {
      document.getElementById('menu').style.display = 'block';
    });
    document.getElementById('upload-different').addEventListener('click', () => {
      document.getElementById('resume-file').click();
    });
    document.getElementById('resume-file').addEventListener('change', () => {
      document.body.dataset.uploadedName = document.getElementById('resume-file').files?.[0]?.name || '';
      document.getElementById('continue').style.display = 'block';
    });
    document.getElementById('continue').addEventListener('click', () => {
      document.body.innerText = 'Review your application';
    });
  </script>
</body></html>
'''



def main():
    async def run():
        pdf = ROOT / 'test_indeed_tailored_resume.pdf'
        pdf.write_bytes(b'%PDF-1.4 test')
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
                page = await browser.new_page()
                await page.set_content(HTML)
                agent = IndeedAgent()
                agent.current_resume_path = str(pdf)
                agent._indeed_resume_replaced = False
                ok = await agent._upload_tailored_resume_on_indeed_review(page)
                assert ok is True
                assert agent._indeed_resume_replaced is True
                uploaded = await page.locator('body').get_attribute('data-uploaded-name')
                assert uploaded and uploaded.endswith("_tailored_resume.pdf"), uploaded
                assert 'Review your application' in await page.locator('body').inner_text()
                await browser.close()
        finally:
            pdf.unlink(missing_ok=True)
    asyncio.run(run())



if __name__ == '__main__':
    main()
    print('PASS: Indeed native resume upload flow')
