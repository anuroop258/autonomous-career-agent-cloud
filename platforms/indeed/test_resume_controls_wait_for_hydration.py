import asyncio
import importlib.util
import sys
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
INDEED_ROOT = ROOT / 'platforms' / 'indeed'
spec = importlib.util.spec_from_file_location('storage', INDEED_ROOT / 'storage.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
sys.modules['storage'] = mod
sys.path.insert(0, str(INDEED_ROOT))
from indeed_agent import IndeedAgent

HTML = '''<!doctype html><html><body>
<div id="mount"></div>
<script>
setTimeout(() => {
  document.getElementById('mount').innerHTML = `
    <section data-testid="resumeSection">
      <h2>Resume</h2>
      <button type="button" aria-label="Edit resume">Edit</button>
      <button id="cv" style="display:none" type="button">CV options</button>
      <div id="menu" style="display:none;position:fixed;z-index:99999"><button type="button">Upload a different file</button></div>
    </section>`;
  const edit=document.querySelector('[aria-label="Edit resume"]');
  const cv=document.querySelector('#cv');
  const menu=document.querySelector('#menu');
  edit.onclick=()=>cv.style.display='block';
  cv.onclick=()=>menu.style.display='block';
}, 1200);
</script></body></html>'''

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
        page = await browser.new_page()
        await page.set_content(HTML)
        agent = IndeedAgent()

        ok = await agent._click_exact_resume_edit(page)
        assert ok is True, 'late Edit resume control was not detected/clicked'
        assert await page.locator('#cv').is_visible()

        # Separate late-hydration state where CV options is rendered later and visible.
        CV_HTML = '''<!doctype html><html><body><div id=mount></div><script>setTimeout(()=>{document.getElementById('mount').innerHTML=`<section data-testid=resumeSection><h2>Resume</h2><button id=cv type=button>CV options</button><div id=menu style=display:none;position:fixed;z-index:99999><button type=button>Upload a different file</button></div></section>`;const cv=document.querySelector('#cv');const menu=document.querySelector('#menu');cv.onclick=()=>menu.style.display='block';},1200);</script></body></html>'''
        await page.set_content(CV_HTML)
        cv = await agent._click_cv_upload_option(page)
        assert cv is not None, 'late CV options control was not detected'
        assert await cv.is_visible()
        assert await page.get_by_text('Upload a different file', exact=True).is_visible()

        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
    print('PASS: late hydration Resume/Edit/CV controls')
