"""Run using Python with Playwright installed, from the repository root."""
import os, sys, tempfile, subprocess, time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
with tempfile.TemporaryDirectory() as tmp:
    env = {**os.environ, 'PAPERTRAIL_DATA': str(Path(tmp)/'index')}
    process = subprocess.Popen([os.environ.get('PAPERTRAIL_APP_PYTHON',sys.executable), 'app.py', '--port', '18766'], env=env)
    try:
        time.sleep(1)
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1440,'height':1050})
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:18766')
            page.get_by_text('A little order for your everyday.').wait_for()
            page.screenshot(path='../../outputs/papertrail-empty.png',full_page=True)
            page.locator('#file-picker').set_input_files({'name':'Laptop warranty.txt','mimeType':'text/plain','buffer':b'Laptop warranty expires December 2027. Coverage includes battery replacement.'})
            page.locator('.card').wait_for()
            page.get_by_role('button',name='PDFs',exact=True).click()
            page.get_by_text('Nothing here just yet.').wait_for()
            page.get_by_role('button',name='Text',exact=True).click()
            page.locator('.card').wait_for()
            page.get_by_role('button',name='List view',exact=True).click()
            expect(page.locator('#results')).to_have_class('list-mode')
            page.get_by_role('button',name='Grid view',exact=True).click()
            page.get_by_role('button',name='All files',exact=True).click()
            page.get_by_role('button',name='How Papertrail works').click()
            expect(page.locator('#help-dialog')).to_be_visible()
            page.get_by_role('button',name='Close help').click()
            page.keyboard.press('Control+k')
            expect(page.locator('#query')).to_be_focused()
            page.locator('#query').fill('warranty')
            page.locator('mark').first.wait_for()
            page.get_by_role('button',name='Read document').click()
            expect(page.locator("#preview-body")).to_contain_text("battery replacement")
            page.screenshot(path='../../outputs/papertrail-reader.png',full_page=True)
            page.get_by_role('button',name='Close preview').click()
            page.screenshot(path='../../outputs/papertrail-desktop.png',full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path='../../outputs/papertrail-mobile.png',full_page=True)
            page.get_by_role('button',name='Remove from library').click()
            page.get_by_text('Nothing here just yet.').wait_for()
            page.reload()
            page.get_by_text('A little order for your everyday.').wait_for()
            assert not errors,errors
            browser.close()
            print('PASS: upload, index, search, highlights, reader, removal, reload, mobile overflow, no JS errors')
    finally:
        process.terminate()
        process.wait()