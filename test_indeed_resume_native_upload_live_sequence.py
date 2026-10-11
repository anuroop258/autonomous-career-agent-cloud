import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "platforms" / "indeed"))
from indeed_agent import IndeedAgent


HTML = r"""
<!doctype html>
<html><body>
  <section id="job"><h2>Job</h2><button id="job-edit">Edit</button></section>
  <section id="resume">
    <h2>Resume</h2>
    <button id="resume-edit">Edit</button>
    <div id="cv-options">CV options</div>
    <div id="menu" style="display:none">
      <button id="upload-different" type="button">Upload a different file</button>
    </div>
    <input id="resume-file" type="file" style="display:none" />
    <button id="continue">Continue</button>
  </section>
  <script>
    document.getElementById("resume-edit").onclick = () => {
      document.body.dataset.resumeEdit = "clicked";
      setTimeout(() => {
        document.getElementById("cv-options").style.display = "block";
      }, 700);
    };
    document.getElementById("cv-options").onclick = () => {
      setTimeout(() => {
        document.getElementById("menu").style.display = "block";
      }, 650);
    };
    document.getElementById("upload-different").onclick = () => {
      document.getElementById("resume-file").click();
    };
    document.getElementById("resume-file").onchange = () => {
      document.body.dataset.uploaded = document.getElementById("resume-file").files[0].name;
    };
    document.getElementById("continue").onclick = () => {
      document.body.innerText = "Review your application Submit application";
    };
  </script>
</body></html>
"""


def main():
    async def run():
        pdf = ROOT / "test_indeed_live_sequence.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
                page = await browser.new_page()
                await page.set_content(HTML)
                # Open the resume section before the agent begins, then require the native
                # Resume -> Edit -> CV options -> Upload a different file sequence.
                await page.set_viewport_size({"width": 1200, "height": 900})
                agent = IndeedAgent()
                agent.current_resume_path = str(pdf)
                agent._indeed_resume_replaced = False
                ok = await agent._upload_tailored_resume_on_indeed_review(page)
                assert ok is True
                assert agent._indeed_resume_replaced is True
                assert await page.locator("body").get_attribute("data-resume-edit") == "clicked"
                uploaded = await page.locator("body").get_attribute("data-uploaded")
                assert uploaded and uploaded.endswith("_tailored_resume.pdf"), uploaded
                assert "Review your application" in await page.locator("body").inner_text()
                await browser.close()
        finally:
            pdf.unlink(missing_ok=True)

    asyncio.run(run())


if __name__ == "__main__":
    main()
    print("PASS: Indeed live-style resume selection sequence")
