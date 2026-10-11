import asyncio, html
from pathlib import Path
from playwright.async_api import async_playwright
import importlib.util, sys
ROOT=Path(__file__).resolve().parents[1]; INDEED=ROOT/'platforms'/'indeed'
spec=importlib.util.spec_from_file_location('storage', INDEED/'storage.py'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); sys.modules['storage']=mod
sys.path.insert(0,str(INDEED)); from indeed_agent import IndeedAgent

FRAME_EDIT='''<html><body><section><div>Resume</div><button aria-label="Edit resume"><span>Edit</span></button><button aria-label="CV options" style="display:none"><span>⚙</span><span>CV options</span></button><div role="menu" style="display:none"><div role="menuitem">Upload a different file</div></div><script>document.querySelector('[aria-label="Edit resume"]').onclick=()=>{document.querySelector('[aria-label="CV options"]').style.display='block'}; document.querySelector('[aria-label="CV options"]').onclick=()=>document.querySelector('[role=menu]').style.display='block';</script></section></body></html>'''
FRAME_PRE='''<html><body><section><div>Resume</div><button aria-label="CV options"><span>⚙</span><span>CV options</span></button><div role="menu" style="display:block"><div role="menuitem"><span>Upload a different file</span></div></div></section></body></html>'''

def host(frame): return '<html><body><iframe srcdoc="'+html.escape(frame,quote=True)+'"></iframe></body></html>'

async def main():
  async with async_playwright() as p:
    browser=await p.chromium.launch(headless=True, executable_path='/usr/bin/chromium')
    agent=IndeedAgent()
    page=await browser.new_page(); await page.set_content(host(FRAME_EDIT));
    assert await agent._click_exact_resume_edit(page) is True
    upload=await agent._click_cv_upload_option(page)
    assert upload is not None
    assert 'Upload a different file' in await upload.inner_text()
    await page.close()
    page2=await browser.new_page(); await page2.set_content(host(FRAME_PRE));
    upload2=await agent._click_cv_upload_option(page2)
    assert upload2 is not None
    assert 'Upload a different file' in await upload2.inner_text()
    await browser.close()

if __name__=='__main__': asyncio.run(main()); print('PASS: Indeed Edit + Upload control variants')
