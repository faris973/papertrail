import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from urllib.parse import quote
from pathlib import Path
from http.server import ThreadingHTTPServer
import app
from fixtures import make_pdf

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.previous=app.DATA
        app.DATA=Path(self.tmp.name)
        app.STATE.update(running=False,done=0,total=0,errors=[],warnings=[])
        self.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.worker.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.worker.join()
        app.DATA=self.previous
        self.tmp.cleanup()

    def request(self,path,body=None,authorized=True):
        headers={'Content-Type':'application/json'}
        if authorized:headers['X-Papertrail-Token']=app.TOKEN
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            response=urllib.request.urlopen(req)
        except urllib.error.HTTPError as error:
            response=error
        with response:
            return response.status,json.load(response)

    def test_api_and_photos_require_session_token(self):
        for path in ['/api/search','/api/status','/api/image?id=1','/api/preview?id=1','/api/render?id=1','/api/sources','/api/browse']:
            self.assertEqual(self.request(path,authorized=False)[0],403)
        self.assertEqual(self.request('/api/remove',{'id':1},authorized=False)[0],403)

    def test_pdf_preview_reports_all_pages(self):
        pdf=app.DATA/'sample.pdf'
        make_pdf(pdf)
        app.index_file(pdf)
        file_id=app.search('warranty', 'text')[0]['id']
        status,preview=self.request(f'/api/preview?id={file_id}&page=2')
        self.assertEqual(status,200)
        self.assertEqual(preview['page_count'],3)
        self.assertEqual(preview['page'],2)
        self.assertIn('Battery replacement', preview['body'])

    def test_folder_browser_lists_directories_only(self):
        (app.DATA/'Holiday photos').mkdir()
        (app.DATA/'.private').mkdir()
        (app.DATA/'notes.txt').write_text('Do not return file contents', encoding='utf-8')
        status,listing=self.request('/api/browse?path='+quote(str(app.DATA)))
        self.assertEqual(status,200)
        self.assertEqual([item['name'] for item in listing['folders']],['Holiday photos'])
        self.assertEqual(listing['parent'],str(app.DATA.parent))
        self.assertEqual(self.request('/api/browse?path='+quote(str(app.DATA/'missing')))[0],400)

    def test_malformed_requests_return_json_errors(self):
        self.assertEqual(self.request('/api/preview?id=1&page=oops')[0],400)
        self.assertEqual(self.request('/api/import',[])[0],400)
        self.assertEqual(self.request('/api/import',{'path':None})[0],400)
        self.assertEqual(self.request('/api/upload',{'name':'x.exe','data':'AA=='})[0],400)
        self.assertEqual(self.request('/api/upload',{'name':'x.jpg','data':'not-base64!'})[0],400)
        self.assertEqual(self.request('/api/image?id=999')[0],404)

if __name__=='__main__':unittest.main()
