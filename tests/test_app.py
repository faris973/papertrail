import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from pathlib import Path
import app

class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        app.DATA = self.root / 'index'
        self.docs = self.root / 'docs'
        self.docs.mkdir()
        app.STATE.update(running=False, done=0, total=0, errors=[], warnings=[])

    def tearDown(self):
        self.tmp.cleanup()

    def test_import_update_delete_and_literal_queries(self):
        file = self.docs / 'receipt.txt'
        file.write_text('Laptop warranty expires December 2027', encoding='utf-8')
        app.index_folder(self.docs)
        result = app.search('warranty')[0]
        self.assertIn('\x01warranty\x02', result['snippet'])
        app.index_folder(self.docs)
        self.assertEqual(len(app.search('warranty')), 1)
        file.write_text('Insurance renewal September', encoding='utf-8')
        app.index_folder(self.docs)
        self.assertEqual(app.search('warranty'), [])
        self.assertEqual(len(app.search('insurance')), 1)
        self.assertEqual(app.search('" OR *'), [])
        file.unlink()
        app.index_folder(self.docs)
        self.assertEqual(app.search('insurance'), [])

    def test_failure_does_not_stop_other_files(self):
        (self.docs / 'broken.pdf').write_bytes(b'not a pdf')
        (self.docs / 'good.md').write_text('Reservation confirmation', encoding='utf-8')
        app.index_folder(self.docs)
        self.assertEqual(len(app.search('reservation')), 1)
        self.assertEqual(len(app.STATE['errors']), 1)

    def test_image_ocr(self):
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new('RGB', (1100, 300), 'white')
        font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 42) if Path('C:/Windows/Fonts/arial.ttf').exists() else ImageFont.load_default(size=42)
        ImageDraw.Draw(image).text((25, 50), 'WARRANTY\nRECEIPT\n2027', font=font, fill='black')
        image.save(self.docs / 'scan.png')
        with patch('vision.encode_image', return_value=np.ones(512, dtype=np.float32)/np.sqrt(512)):
            app.index_folder(self.docs)
        self.assertEqual(app.STATE['errors'], [])
        self.assertEqual(len(app.search('warranty', mode='text')), 1)


    def test_text_free_photo_survives_model_failure_and_retries(self):
        from PIL import Image
        photo = self.docs / 'IMG_101.jpg'
        Image.new('RGB', (64, 64), 'orange').save(photo)
        with patch('vision.encode_image', side_effect=RuntimeError('Model unavailable')), patch('app.ocr', return_value=''):
            app.index_folder(self.docs)
        rows = app.search('')
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['is_image'])
        self.assertEqual(app.STATE['errors'], [])
        with app.closing(app.db()) as conn:
            self.assertIsNone(conn.execute('SELECT embedding FROM photos').fetchone()[0])
        vector = np.ones(512,dtype=np.float32)/np.sqrt(512)
        with patch('vision.encode_image', return_value=vector), patch('app.ocr', return_value=''):
            app.index_folder(self.docs)
        with patch('vision.encode_query', return_value=vector):
            self.assertEqual(app.search('orange', mode='visual')[0]['id'],rows[0]['id'])
        photo.unlink()
        app.index_folder(self.docs)
        with app.closing(app.db()) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM photos').fetchone()[0],0)

    def test_changed_photo_replaces_visual_fingerprint(self):
        from PIL import Image
        photo = self.docs / 'photo.png'
        first = np.zeros(512, dtype=np.float32);first[0]=1
        second = np.zeros(512, dtype=np.float32);second[1]=1
        Image.new('RGB',(32,32),'red').save(photo)
        with patch('vision.encode_image', return_value=first), patch('app.ocr', return_value=''):
            app.index_folder(self.docs)
        Image.new('RGB',(64,64),'blue').save(photo)
        with patch('vision.encode_image', return_value=second), patch('app.ocr', return_value=''):
            app.index_folder(self.docs)
        with patch('vision.encode_query', return_value=first):
            self.assertEqual(app.search('red',mode='visual'),[])
        with patch('vision.encode_query', return_value=second):
            self.assertEqual(len(app.search('blue',mode='visual')),1)

if __name__ == '__main__':
    unittest.main()
