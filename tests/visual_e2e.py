"""Real-model acceptance test. Pass a folder containing IMG_001/002/003.jpg (car/cat/mountain)."""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.sync_api import sync_playwright, expect

parser=argparse.ArgumentParser()
parser.add_argument('fixtures', type=Path)
args=parser.parse_args()
fixtures=args.fixtures.resolve()
with tempfile.TemporaryDirectory() as tmp:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    env={**os.environ,'PAPERTRAIL_DATA':tmp,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
    def start():
        process=subprocess.Popen([os.environ.get('PAPERTRAIL_APP_PYTHON',sys.executable),'app.py','--port',str(port)],env=env)
        for _ in range(100):
            try:
                with urllib.request.urlopen(url,timeout=1) as response:
                    token=re.search(r'name="papertrail-token" content="([^"]+)"',response.read().decode()).group(1)
                return process,token
            except OSError:time.sleep(.1)
        raise RuntimeError('Server failed to start')
    process,token=start()
    def api(path,data=None,auth=True):
        req=urllib.request.Request(url+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json',**({'X-Papertrail-Token':token} if auth else {})})
        with urllib.request.urlopen(req) as response:return json.load(response)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];remote=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda req:remote.append(req.url) if not req.url.startswith(url) and not req.url.startswith('blob:') else None)
            page.goto(url)
            page.locator('#file-picker').set_input_files([str(fixtures/f'IMG_00{i}.jpg') for i in [1,2,3]])
            expect(page.locator('.card')).to_have_count(3,timeout=120000)
            expect(page.locator('#upload')).to_be_enabled(timeout=10000)
            expect(page.locator('.photo-cover img').first).to_be_visible()
            page.wait_for_function('() => [...document.querySelectorAll(".photo-cover img")].every(i=>i.naturalWidth>0)')
            page.screenshot(path='../../outputs/papertrail-photos.png',full_page=True)
            assert api('/api/search?q=car&mode=text')==[], 'Car must not match filename or OCR'
            for query,expected in [('car','IMG_001.jpg'),('orange%20sports%20car','IMG_001.jpg'),('cat','IMG_002.jpg'),('mountain','IMG_003.jpg')]:
                results=api('/api/search?q='+query+'&mode=visual')
                assert results and results[0]['name']==expected,(query,results)
                print('PASS',query,expected,results[0]['similarity'],flush=True)
            page.locator('#query').fill('car')
            expect(page.locator('.card')).to_have_count(1,timeout=15000)
            expect(page.locator('.visual-match')).to_have_text('Visual match')
            page.wait_for_function('() => document.querySelector(".photo-cover img").naturalWidth>0')
            page.screenshot(path='../../outputs/papertrail-car-search.png',full_page=True)
            page.get_by_role('button',name='View photo').click()
            expect(page.locator('#preview-image')).to_be_visible()
            page.wait_for_function('() => document.querySelector("#preview-image").naturalWidth>0')
            page.get_by_role('button',name='Close preview').click()
            page.locator('#search-mode').select_option('text')
            expect(page.locator('.card')).to_have_count(0)
            page.locator('#search-mode').select_option('visual')
            expect(page.locator('.card')).to_have_count(1)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path='../../outputs/papertrail-car-mobile.png',full_page=True)
            assert not errors,errors
            assert not remote,remote
            browser.close()
        # Reopen the same database, with network model downloads explicitly disabled.
        process.terminate();process.wait()
        process,token=start()
        results=api('/api/search?q=car&mode=visual')
        assert results[0]['name']=='IMG_001.jpg'
        api('/api/remove',{'id':results[0]['id']})
        assert api('/api/search?q=car&mode=visual')==[]
        try:api('/api/search?q=car',auth=False)
        except urllib.error.HTTPError as e:assert e.code==403
        else:raise AssertionError('Unauthenticated access allowed')
        print('PASS browser upload, thumbnails, visual-only retrieval, photo reader, modes, mobile, persistence, offline reload, deletion, API auth; no browser network requests',flush=True)
    finally:
        process.terminate();process.wait()
