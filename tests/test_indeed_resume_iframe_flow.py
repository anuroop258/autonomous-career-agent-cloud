import asyncio
import importlib.util
import sys
import html
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
INDEED_ROOT = ROOT / 'platforms' / 'indeed'
_storage_spec = importlib.util.spec_from_file_location('storage', INDEED_ROOT / 'storage.py')
_storage_mod = importlib.util.module_from_spec(_storage_spec)
_storage_spec.loader.exec_module(_storage_mod)
sys.modules['storage'] = _storage_mod
sys.path.insert(0, str(INDEED_ROOT))
from indeed_agent import IndeedAgent

FRAME_HTML = '''<!doctype html><html><body>
<section id="resume"><h2>Resume</h2><button id="edit">Edit</button>
<button id="cv" style="display:none">CV options</button>
<div id="menu" style="display:none"><button id="upload">Upload a different file</button></div>
<input id="file" type="file" style="display:none">
<button id="continue">Continue</button></section>
<script>
const edit=document.getElementById('edit'); const cv=document.getElementById('cv'); const menu=document.getElementById('menu'); const upload=document.getElementById('upload'); const file=document.getElementById('file'); const cont=document.getElementById('continue');
edit.onclick=()=>cv.style.display='block';
cv.onclick=()=>menu.style.display='block';
upload.onclick=()=>file.click();
file.onchange=()=>document.body.dataset.uploaded=file.files[0].name;
cont.onclick=()=>document.body.innerText='Review your application';
</script></body></html>'''

HOST_HTML = '<!doctype html><html><body><iframe id="app" srcdoc="' + html.escape(FRAME_HTML, quote=True) + '"></iframe></body></html>'

async def main():
    pdf = ROOT / 'test_iframe_resume.pdf'
    pdf.write_bytes(b'%PDF-1.4 test')
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
            page = await browser.new_page()
            await page.set_content(HOST_HTML)
            await page.wait_for_timeout(300)
            assert len(page.frames) == 2
            agent = IndeedAgent()
            agent.current_resume_path = str(pdf)
            agent._indeed_resume_replaced = False
            ok = await agent._upload_tailored_resume_on_indeed_review(page)
            assert ok is True
            assert agent._indeed_resume_replaced is True
            frame = page.frames[1]
            uploaded = await frame.locator('body').get_attribute('data-uploaded')
            assert uploaded and uploaded.endswith('_tailored_resume.pdf'), uploaded
            assert 'Review your application' in await frame.locator('body').inner_text()
            await browser.close()
    finally:
        pdf.unlink(missing_ok=True)

if __name__ == '__main__':
    asyncio.run(main())
    print('PASS: Indeed resume iframe flow')
