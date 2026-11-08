"""Acceptance: recursive photo import, auto-sync, duplicate uploads, undo, and PDF reader."""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect
from fixtures import make_pdf

fixtures=Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory() as tmp:
    base=Path(tmp)
    library=base/'My Photos';(library/'Holiday').mkdir(parents=True)
    shutil.copyfile(fixtures/'IMG_001.jpg',library/'IMG_001.jpg')
    shutil.copyfile(fixtures/'IMG_002.jpg',library/'Holiday/IMG_002.jpg')
    shutil.copyfile(fixtures/'IMG_003.jpg',library/'Holiday/IMG_003.jpg')
    (library/'do-not-import.txt').write_text('Photos-only import must skip me.',encoding='utf-8')
    pdf=base/'Purchase and warranty.pdf';make_pdf(pdf)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    env={**os.environ,'PAPERTRAIL_DATA':str(base/'index'),'PAPERTRAIL_SYNC_SECONDS':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
    process=subprocess.Popen([os.environ.get('PAPERTRAIL_APP_PYTHON',sys.executable),'app.py','--port',str(port)],env=env)
    def api(path,body=None):
        req=urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','X-Papertrail-Token':token})
        with urllib.request.urlopen(req) as r:return json.load(r)
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(url,timeout=1) as r:token=re.search(r'name="papertrail-token" content="([^"]+)"',r.read().decode()).group(1)
                break
            except OSError:time.sleep(.1)
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1440,'height':1000})
            page.set_default_timeout(15000)
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(url)
            page.get_by_role('button',name='Import photo library',exact=True).click()
            expect(page.locator('#import-dialog')).to_be_visible()
            expect(page.locator('#import-scope')).to_have_value('photos')
            expect(page.locator('#watch-folder')).to_be_checked()
            page.locator('#folder').fill(str(base))
            page.get_by_role('button',name='Browse…',exact=True).click()
            page.locator('#browser-folders').get_by_role('button',name='My Photos',exact=False).click()
            expect(page.locator('#browser-path')).to_have_text(str(library))
            page.get_by_role('button',name='Use this folder',exact=True).click()
            expect(page.locator('#folder')).to_have_value(str(library))
            page.screenshot(path='../../outputs/papertrail-import-library.png',full_page=True)
            page.get_by_role('button',name='Import library',exact=True).click()
            expect(page.locator('.card')).to_have_count(3,timeout=120000)
            page.wait_for_function('() => [...document.querySelectorAll(".photo-cover img")].every(i=>i.naturalWidth>0)')
            assert (library/'IMG_001.jpg').exists()
            assert not list((base/'index/uploads').glob('*'))
            assert not api('/api/search?q=skip&mode=text')
            page.screenshot(path='../../outputs/papertrail-photo-library.png',full_page=True)
            # A newly saved photo appears without re-import or reload.
            shutil.copyfile(fixtures/'IMG_002.jpg',library/'Holiday/IMG_004.jpg')
            expect(page.locator('.card')).to_have_count(4,timeout=30000)
            page.get_by_role('button',name='Folders',exact=True).click()
            page.get_by_role('button',name='Pause sync',exact=True).click()
            expect(page.get_by_role('button',name='Resume sync',exact=True)).to_be_visible()
            shutil.copyfile(fixtures/'IMG_003.jpg',library/'IMG_005.jpg')
            time.sleep(2.5)
            assert api('/api/status')['count']==4
            page.get_by_role('button',name='Resume sync',exact=True).click()
            page.get_by_role('button',name='Close folders',exact=True).click()
            expect(page.locator('.card')).to_have_count(5,timeout=30000)
            # Source deletion disappears automatically; other files survive.
            (library/'IMG_005.jpg').unlink()
            expect(page.locator('.card')).to_have_count(4,timeout=20000)
            page.locator('#file-picker').set_input_files(str(pdf))
            expect(page.locator('.card')).to_have_count(5,timeout=30000)
            page.locator('#search-mode').select_option('text')
            page.locator('#query').fill('where is my warranty')
            expect(page.locator('.card')).to_have_count(1,timeout=30000)
            page.get_by_role('button',name='Read document').click()
            expect(page.locator('#preview-image')).to_be_visible()
            page.wait_for_function('() => document.querySelector("#preview-image").naturalWidth > 1000')
            page.locator('#matching-pages').get_by_role('button',name='2',exact=True).click()
            expect(page.locator('#page-counter')).to_have_text('Page 2 of 3')
            page.wait_for_function('() => document.querySelector("#preview-image").naturalWidth > 1000')
            page.screenshot(path='../../outputs/papertrail-pdf-reader.png',full_page=True)
            page.get_by_role('button',name='Extracted text',exact=True).click()
            expect(page.locator('#preview-body')).to_contain_text('Battery replacement')
            page.get_by_role('button',name='Next page',exact=True).click()
            expect(page.locator('#page-counter')).to_have_text('Page 3 of 3')
            page.get_by_role('button',name='Close preview',exact=True).click()
            page.locator('#file-picker').set_input_files(str(pdf))
            expect(page.locator('#toast-message')).to_contain_text('already in your library')
            assert api('/api/status')['count']==5
            page.get_by_role('button',name='Remove from library',exact=True).click()
            expect(page.locator('.card')).to_have_count(0)
            page.get_by_role('button',name='Undo',exact=True).click()
            expect(page.locator('.card')).to_have_count(1)
            page.get_by_role('button',name='Clear search',exact=True).click()
            expect(page.locator('.card')).to_have_count(5)
            page.set_viewport_size({'width':390,'height':844})
            page.get_by_role('button',name='Import photo library',exact=True).click()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('#import-dialog').evaluate('(el)=>el.scrollWidth <= el.clientWidth')
            page.screenshot(path='../../outputs/papertrail-import-mobile.png',full_page=True)
            page.get_by_role('button',name='Close import',exact=True).click()
            assert not errors, errors
            browser.close()
        print('PASS recursive photo import, originals unchanged, text files excluded, automatic add/delete, pause/resume, PDF grouping/rendering/navigation, prefix question search, duplicate upload, undo, mobile dialog',flush=True)
    finally:
        process.terminate();process.wait()
