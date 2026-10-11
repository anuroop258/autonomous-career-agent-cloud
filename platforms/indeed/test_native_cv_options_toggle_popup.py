import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from platforms.indeed.indeed_agent import IndeedAgent


MAIN_TOGGLE_HTML = r'''
<!doctype html><html><body>
  <button id="cv" aria-label="CV options">⚙ CV options</button>
  <script>
    document.getElementById("cv").addEventListener("click", () => {
      document.body.insertAdjacentHTML("beforeend",
        `<div id="floating-upload" style="position:fixed;right:20px;bottom:20px;background:white;z-index:9999;padding:20px;border:1px solid #ccc">
          <button id="upload-different">⇧ Upload a different file</button>
        </div>`
      );
    });
  </script>
</body></html>
'''


IFRAME_HTML = r'''
<!doctype html><html><body>
  <iframe id="app" srcdoc='<!doctype html><html><body>
    <button id="cv" aria-label="CV options">⚙ CV options</button>
    <script>
      document.getElementById("cv").addEventListener("click", () => {
        document.body.insertAdjacentHTML("beforeend",
          `<div id="floating-upload" style="position:fixed;right:20px;bottom:20px;background:white;z-index:9999;padding:20px;border:1px solid #ccc">
            <button id="upload-different">Upload a different file</button>
          </div>`
        );
      });
    </script>
  </body></html>'></iframe>
</body></html>
'''


async def _exercise_toggle_and_iframe(page, agent):
    await page.set_content(MAIN_TOGGLE_HTML)
    upload = await agent._click_cv_upload_option(page)
    assert upload is not None, "floating Upload a different file was not detected"
    assert await upload.is_visible()
    assert "Upload a different file" in (await upload.inner_text())
    await upload.click()

    await page.set_content(IFRAME_HTML)
    upload2 = await agent._click_cv_upload_option(page)
    assert upload2 is not None, "iframe CV toggle/upload popup was not detected"
    assert await upload2.is_visible()


async def _exercise_preopened(page, agent):
    await page.set_content(r'''<!doctype html><html><body>
      <div id="floating-upload" style="position:fixed;right:20px;bottom:20px;background:white;z-index:9999;padding:20px">
        <button id="upload-different">⇧ Upload a different file</button>
      </div>
      <button id="cv" aria-label="CV options">CV options</button>
    </body></html>''')
    upload = await agent._click_cv_upload_option(page)
    assert upload is not None, "already-open Upload a different file was not detected"
    assert await upload.is_visible()


def test_toggle_and_iframe():
    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
            try:
                page = await browser.new_page()
                agent = IndeedAgent()
                await _exercise_toggle_and_iframe(page, agent)
                await _exercise_preopened(page, agent)
            finally:
                await browser.close()
    asyncio.run(run())


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        try:
            agent = IndeedAgent()
            page = await browser.new_page()
            await test_toggle_and_iframe(page, agent)
            await test_preopened(page, agent)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
    print("PASS: CV options toggle popup, iframe popup, and pre-open state")
