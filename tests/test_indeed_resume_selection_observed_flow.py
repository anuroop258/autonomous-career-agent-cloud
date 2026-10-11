
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
INDEED_ROOT = ROOT / "platforms" / "indeed"
sys.path.insert(0, str(INDEED_ROOT))

# When this test is launched from the project root, Python's empty-string
# path can otherwise resolve v28_current/storage.py before the Indeed-local
# storage.py. Load the platform-local module explicitly.
import importlib.util
_storage_spec = importlib.util.spec_from_file_location("storage", INDEED_ROOT / "storage.py")
_storage_mod = importlib.util.module_from_spec(_storage_spec)
_storage_spec.loader.exec_module(_storage_mod)
sys.modules["storage"] = _storage_mod

from indeed_agent import IndeedAgent


HTML = r"""
<!doctype html>
<html><body>
  <section id="resume">
    <h2>Resume</h2>
    <div id="cv-options">CV options</div>
    <div id="menu" style="display:none">
      <button id="upload-different" type="button">Upload a different file</button>
    </div>
    <input id="resume-file" type="file" style="display:none" />
    <button id="continue">Continue</button>
  </section>
  <script>
    document.getElementById("cv-options").onclick = () => {
      document.getElementById("menu").style.display = "block";
    };
    document.getElementById("upload-different").onclick = () => {
      document.getElementById("resume-file").click();
    };
    document.getElementById("resume-file").onchange = () => {
      document.body.dataset.uploaded =
        document.getElementById("resume-file").files[0].name;
    };
    document.getElementById("continue").onclick = () => {
      document.body.innerText = "Review your application Submit application";
    };
  </script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def log_message(self, *args):
        return


def run_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class ResumeSelectionPage:
    def __init__(self, page):
        self._page = page

    @property
    def url(self):
        return (
            "https://smartapply.indeed.com/beta/indeedapply/form/"
            "resume-selection-module/resume-selection"
        )

    def __getattr__(self, name):
        return getattr(self._page, name)


def main():
    async def run():
        server = run_server()
        pdf = ROOT / "test_resume_selection_observed.pdf"
        pdf.write_bytes(b"%PDF-1.4 test")
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    executable_path="/usr/bin/chromium",
                )
                page = await browser.new_page()
                await page.set_content(HTML)

                wrapped_page = ResumeSelectionPage(page)
                agent = IndeedAgent()
                agent.current_resume_path = str(pdf)
                agent._indeed_resume_replaced = False

                async def should_not_click_edit(_page):
                    raise AssertionError(
                        "Resume -> Edit must be skipped when already on "
                        "Indeed's resume-selection module"
                    )

                agent._click_exact_resume_edit = should_not_click_edit

                ok = await agent._upload_tailored_resume_on_indeed_review(wrapped_page)
                assert ok is True
                assert agent._indeed_resume_replaced is True
                uploaded = await page.locator("body").get_attribute("data-uploaded")
                assert uploaded and uploaded.endswith("_tailored_resume.pdf"), uploaded
                assert "Review your application" in await page.locator("body").inner_text()

                # The observed Indeed redirect/review URL is itself an application
                # state and must be routed through the resume replacement path.
                class FakePage:
                    url = (
                        "https://smartapply.indeed.com/beta/indeedapply/form/"
                        "resume-selection-module/resume-selection"
                    )

                assert await agent._is_indeed_review_state(FakePage(), "") is True

                # Verify the master-resume fallback when tailoring is unavailable.
                agent2 = IndeedAgent()
                agent2.current_resume_path = str(ROOT / "missing-tailored.pdf")
                agent2._indeed_resume_replaced = False

                async def master_resume():
                    return str(pdf)

                agent2._find_resume = master_resume
                await page.set_content(HTML)
                ok2 = await agent2._upload_tailored_resume_on_indeed_review(wrapped_page)
                assert ok2 is True
                assert agent2._indeed_resume_replaced is True
                uploaded2 = await page.locator("body").get_attribute("data-uploaded")
                assert uploaded2 and uploaded2.endswith("_tailored_resume.pdf"), uploaded2

                await browser.close()
        finally:
            server.shutdown()
            server.server_close()
            pdf.unlink(missing_ok=True)

    asyncio.run(run())


if __name__ == "__main__":
    main()
    print("PASS: observed Indeed resume-selection start state")
