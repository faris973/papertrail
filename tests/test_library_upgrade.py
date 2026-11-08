import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
import app
import previews
from fixtures import make_pdf

class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous = app.DATA
        app.DATA = self.root / 'index'
        self.folder = self.root / 'documents';self.folder.mkdir()
        app.CANCEL.clear();app.REMOVED.clear()
        app.STATE.update(running=False, done=0,total=0,errors=[],warnings=[])

    def tearDown(self):
        self.wait_for_job()
        app.DATA = self.previous
        self.temp.cleanup()

    def wait_for_job(self):
        deadline=time.time()+10
        while app.STATE['running'] and time.time()<deadline:time.sleep(.02)
        self.assertFalse(app.STATE['running'])

    def test_pdf_is_grouped_and_original_pages_render(self):
        path=self.folder/'receipt.pdf';make_pdf(path)
        app.index_folder(self.folder)
        self.assertEqual(len(app.search('',mode='text')),1)
        result=app.search('where is my warr',mode='text')[0]
        self.assertEqual(result['page_count'],3)
        self.assertEqual(sorted(result['matching_pages']),[2,3])
        self.assertIn('\x01',result['snippet'])
        first=previews.render(path,1,700);second=previews.render(path,2,700)
        self.assertNotEqual(first,second)
        self.assertEqual(Image.open(io.BytesIO(first)).width,700)
        with self.assertRaises(ValueError):previews.render(path,4,700)

    def test_photo_folder_includes_nested_heic_and_skips_documents(self):
        nested=self.folder/'holiday';nested.mkdir()
        Image.new('RGB',(100,80),'orange').save(nested/'IMG_1.heic',format='HEIF')
        Image.new('RGB',(100,80),'blue').save(self.folder/'IMG_2.PNG')
        (nested/'private.txt').write_text('not a photo',encoding='utf-8')
        with patch('vision.encode_image',return_value=np.ones(512,dtype=np.float32)),patch('app.ocr',return_value=''):
            app.index_folder(self.folder,'photos')
        self.assertEqual(len(app.search('')),2)
        self.assertEqual(app.STATE['errors'],[])
        self.assertTrue(previews.render(nested/'IMG_1.heic').startswith(b'\xff\xd8'))
        self.assertTrue((nested/'private.txt').exists())

    def test_sync_updates_files_and_respects_removal_and_undo(self):
        path=self.folder/'notes.txt';path.write_text('violet flower',encoding='utf-8')
        with app.closing(app.db()) as conn,conn:conn.execute('INSERT INTO sources(path,scope,enabled) VALUES(?,?,1)',(str(self.folder),'all'))
        app.sync_if_changed();self.wait_for_job()
        found=app.search('violet')[0]
        token=app.remove_file(found['id'])
        app.sync_if_changed();self.wait_for_job()
        self.assertEqual(app.search('violet'),[])
        app.restore_file(token)
        self.assertEqual(len(app.search('violet')),1)
        path.write_text('yellow sunflower',encoding='utf-8')
        app.sync_if_changed();self.wait_for_job()
        self.assertEqual(app.search('violet'),[])
        self.assertEqual(len(app.search('sunflower')),1)
        path.unlink()
        app.sync_if_changed();self.wait_for_job()
        self.assertEqual(app.search(''),[])

    def test_unavailable_folder_keeps_index(self):
        path=self.folder/'notes.txt';path.write_text('keep this searchable',encoding='utf-8')
        app.index_folder(self.folder)
        with app.closing(app.db()) as conn,conn:conn.execute('INSERT INTO sources(path,scope,enabled) VALUES(?,?,1)',(str(self.folder),'all'))
        hidden=self.root/'offline';self.folder.rename(hidden)
        app.sync_if_changed()
        self.assertEqual(len(app.search('searchable')),1)
        self.assertFalse(app.search('searchable')[0]['available'])
        self.assertIn('unavailable',app.source_list()[0]['error'].lower())

    def test_cancellation_keeps_completed_files(self):
        for n in range(3):(self.folder/f'{n}.txt').write_text(f'note number {n}',encoding='utf-8')
        original=app.index_file
        def stop_after_first(path):
            original(path);app.CANCEL.set()
        with patch('app.index_file',side_effect=stop_after_first):
            app.start_job(app.index_folder,self.folder);self.wait_for_job()
        self.assertEqual(len(app.search('')),1)
        app.start_job(app.index_folder,self.folder);self.wait_for_job()
        self.assertEqual(len(app.search('')),3)

if __name__=='__main__':unittest.main()
