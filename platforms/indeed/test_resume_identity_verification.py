import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from platforms.indeed.indeed_agent import IndeedAgent


REVIEW_HTML = '''<!doctype html><html><body>
<section data-testid="resumeSection">
  <h2>Resume</h2>
  <div data-testid="resumeSection-actions">
    <a data-testid="fileDownload" download="{filename}" href="#">Download</a>
    <span data-testid="fileMetadata"><span data-testid="fileName">{filename}</span></span>
  </div>
</section>
</body></html>'''


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
        try:
            page = await browser.new_page()
            agent = IndeedAgent()

            target = 'Anuroop_Kudire_abc123_tailored_resume.pdf'
            stale = 'Anuroop_Kudire_old999_tailored_resume.pdf'

            await page.set_content(REVIEW_HTML.format(filename=target))
            assert await agent._visible_resume_filename(page) == target
            assert await agent._wait_for_exact_resume_filename(page, target, timeout_ms=250) == target
            assert await agent._wait_for_exact_resume_filename(page, stale, timeout_ms=250) is None

            await page.set_content(REVIEW_HTML.format(filename=stale))
            assert await agent._visible_resume_filename(page) == stale
            assert await agent._wait_for_exact_resume_filename(page, target, timeout_ms=250) is None
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
    print('PASS: exact native resume identity verification')
