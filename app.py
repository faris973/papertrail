"""Papertrail: local document search. Run python app.py."""
from contextlib import closing
import io
import base64
import logging
import mimetypes
import hashlib
import time
import subprocess
import sys
import previews
import argparse
import json
import os
import re
import secrets
import sqlite3
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).parent
DATA = Path(os.environ.get('PAPERTRAIL_DATA', str(BASE / '.papertrail')))
TOKEN = secrets.token_urlsafe(32)
STATE = {'running': False, 'done': 0, 'total': 0, 'errors': [], 'warnings': [], 'stage': ''}
LOCK = threading.RLock()
CANCEL = threading.Event()
SHUTDOWN = threading.Event()
REVISION = 0
REMOVED = {}
WATCHER = None
EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.txt', '.md'}
OCR = None
IMAGES = {'.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif', '.avif', '.tif', '.tiff', '.bmp'}
EXTENSIONS |= IMAGES
from pillow_heif import register_heif_opener
register_heif_opener()
import vision

def db():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA / 'index.sqlite', timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, path TEXT UNIQUE, stamp TEXT)')
    conn.execute('CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(file_id UNINDEXED, page UNINDEXED, name, body, tokenize="unicode61")')
    conn.execute('CREATE TABLE IF NOT EXISTS photos(file_id INTEGER PRIMARY KEY, embedding BLOB, model TEXT, thumbnail BLOB NOT NULL, error TEXT)')
    columns = {row[1] for row in conn.execute('PRAGMA table_info(files)')}
    if 'content_hash' not in columns:
        conn.execute('ALTER TABLE files ADD COLUMN content_hash TEXT')
    if 'error' not in columns:
        conn.execute('ALTER TABLE files ADD COLUMN error TEXT')
    conn.execute('CREATE INDEX IF NOT EXISTS files_hash ON files(content_hash)')
    conn.execute('CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, path TEXT UNIQUE, scope TEXT NOT NULL DEFAULT "all", enabled INTEGER NOT NULL DEFAULT 1, last_scan REAL, error TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS ignored_paths(path TEXT PRIMARY KEY)')
    conn.execute('CREATE TABLE IF NOT EXISTS failed_files(path TEXT PRIMARY KEY,stamp TEXT,error TEXT)')
    conn.commit()
    return conn

def ocr(image):
    global OCR
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    if OCR is None:
        OCR = RapidOCR()
    result, _ = OCR(np.array(image.convert('RGB')))
    return '\n'.join(item[1] for item in (result or []))

def extract(path):
    if path.suffix.lower() in {'.txt', '.md'}:
        yield 1, path.read_text(encoding='utf-8', errors='replace')
    elif path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        for number, page in enumerate(reader.pages):
            text = page.extract_text() or ''
            if len(text.strip()) < 30:
                text = ocr(previews.pdf_page(path, number + 1))
            yield number + 1, text
    else:
        from PIL import Image, ImageOps
        with Image.open(path) as image:
            yield 1, ocr(ImageOps.exif_transpose(image))

def photo_data(path):
    from PIL import Image, ImageOps
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        image.thumbnail((2400, 2400))
        STATE['stage'] = 'Understanding ' + path.name
        error = None
        vector = None
        try:
            vector = vision.encode_image(image).astype('float32').tobytes()
        except Exception as exc:
            error = str(exc)
        try:
            body = ocr(image)
        except Exception as exc:
            body = ''
            STATE['warnings'].append({'file': path.name, 'error': 'Text extraction unavailable: ' + str(exc)})
        image.thumbnail((720, 720))
        output = io.BytesIO()
        image.save(output, format='JPEG', quality=86)
        return body, vector, output.getvalue(), error


def index_file(path):
    path = Path(path).resolve()
    stat = path.stat()
    stamp = f'{stat.st_mtime_ns}:{stat.st_size}'
    is_image = path.suffix.lower() in IMAGES
    with closing(db()) as conn:
        if conn.execute('SELECT 1 FROM ignored_paths WHERE path=?', (str(path),)).fetchone():
            return
        old = conn.execute('SELECT * FROM files WHERE path=?', (str(path),)).fetchone()
        photo = conn.execute('SELECT embedding,model FROM photos WHERE file_id=?', (old['id'],)).fetchone() if old else None
        if old and old['stamp'] == stamp and (not is_image or (photo and photo['embedding'] and photo['model'] == vision.MODEL_KEY)):
            return
    STATE['stage'] = 'Reading ' + path.name
    if is_image:
        body, vector, thumbnail, error = photo_data(path)
        pages = [(1, body)]  # Text-free photos are valid documents.
    else:
        pages = list(extract(path))
        if not any(text.strip() for _, text in pages):
            raise ValueError('No readable text found')
    checksum = file_hash(path)
    current = path.stat()
    if f'{current.st_mtime_ns}:{current.st_size}' != stamp:
        raise ValueError('File changed while reading it. It will be retried on the next sync.')
    with closing(db()) as conn, conn:
        conn.execute('INSERT INTO files(path,stamp) VALUES(?,?) ON CONFLICT(path) DO UPDATE SET stamp=excluded.stamp', (str(path), stamp))
        file_id = conn.execute('SELECT id FROM files WHERE path=?', (str(path),)).fetchone()[0]
        conn.execute('UPDATE files SET content_hash=?,error=NULL WHERE id=?', (checksum,file_id))
        conn.execute('DELETE FROM failed_files WHERE path=?', (str(path),))
        conn.execute('DELETE FROM pages WHERE file_id=?', (file_id,))
        conn.executemany('INSERT INTO pages(file_id,page,name,body) VALUES(?,?,?,?)', ((file_id, n, path.name, text) for n, text in pages))
        if is_image:
            conn.execute('INSERT OR REPLACE INTO photos VALUES(?,?,?,?,?)', (file_id, vector, vision.MODEL_KEY, thumbnail, error))
            if error:
                STATE['warnings'].append({'file': path.name, 'error': 'Photo saved, but visual search is pending. ' + error})
    changed()


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def changed():
    global REVISION
    with LOCK:
        REVISION += 1


def index_paths(paths):
    STATE['total'] = len(paths)
    for path in paths:
        if CANCEL.is_set():
            break
        try:
            index_file(path)
        except Exception as error:
            STATE['errors'].append({'file': path.name, 'error': str(error)})
            with closing(db()) as conn, conn:
                conn.execute('UPDATE files SET error=? WHERE path=?', (str(error), str(path)))
                if path.is_file():
                    stat = path.stat()
                    conn.execute('INSERT OR REPLACE INTO failed_files VALUES(?,?,?)', (str(path), f'{stat.st_mtime_ns}:{stat.st_size}', str(error)))
        finally:
            STATE['done'] += 1


def walk_files(folder, scope='all'):
    if not folder.is_dir():
        raise ValueError('Folder is unavailable. Reconnect the drive or choose another folder.')
    allowed = IMAGES if scope == 'photos' else EXTENSIONS
    excluded = {'.git', '.venv', '.models', '.papertrail', '__pycache__', 'node_modules'}
    with closing(db()) as conn:
        ignored = {r[0] for r in conn.execute('SELECT path FROM ignored_paths')}
    found = []
    def denied(error):
        STATE.setdefault('warnings', []).append({'file': str(error.filename), 'error': 'Folder could not be read.'})
    for directory, dirs, names in os.walk(folder, followlinks=False, onerror=denied):
        if CANCEL.is_set():
            break
        dirs[:] = [d for d in dirs if d not in excluded and not (Path(directory) / d).is_symlink()]
        for name in names:
            path = Path(directory) / name
            if path.suffix.lower() not in allowed or path.is_symlink():
                continue
            resolved = path.resolve()
            if str(resolved) in ignored:
                continue
            if DATA.resolve() in resolved.parents and (DATA / 'uploads').resolve() not in folder.parents:
                continue
            found.append(resolved)
    return sorted(found)


def index_folder(folder, scope='all'):
    STATE.setdefault('warnings', [])
    try:
        files = walk_files(folder, scope)
        # An unavailable root must never be interpreted as every file being deleted.
        if not folder.is_dir():
            raise ValueError('Folder became unavailable. Existing search entries were kept.')
        with closing(db()) as conn, conn:
            removed = 0
            for row in conn.execute('SELECT id,path FROM files').fetchall():
                original = Path(row['path'])
                eligible = scope != 'photos' or original.suffix.lower() in IMAGES
                if eligible and original.is_relative_to(folder) and not original.exists():
                    for table in ['pages', 'photos']:
                        conn.execute(f'DELETE FROM {table} WHERE file_id=?', (row['id'],))
                    conn.execute('DELETE FROM files WHERE id=?', (row['id'],))
                    removed += 1
            for failed in conn.execute('SELECT path FROM failed_files').fetchall():
                if Path(failed['path']).is_relative_to(folder) and not Path(failed['path']).exists():
                    conn.execute('DELETE FROM failed_files WHERE path=?', (failed['path'],))
            if removed:
                changed()
        index_paths(files)
        with closing(db()) as conn, conn:
            error = f"{len(STATE['errors'])} file(s) need attention" if STATE['errors'] else None
            conn.execute('UPDATE sources SET last_scan=?,error=? WHERE path=?', (time.time(), error, str(folder)))
    except Exception as error:
        STATE['errors'].append({'file': str(folder), 'error': str(error)})
        with closing(db()) as conn, conn:
            conn.execute('UPDATE sources SET last_scan=?,error=? WHERE path=?', (time.time(), str(error), str(folder)))


def search(query, mode='all'):
    import numpy as np
    words = query_words(query)
    with closing(db()) as conn:
        if not words:
            rows = [dict(r) for r in conn.execute('SELECT files.id,files.path,files.stamp AS version,files.error,pages.page,pages.name,substr(pages.body,1,260) AS snippet FROM pages JOIN files ON files.id=pages.file_id ORDER BY files.id DESC')]
        elif mode != 'visual':
            match = ' AND '.join('"' + word + '"*' for word in words)
            rows = [dict(r) for r in conn.execute("SELECT files.id,files.path,files.stamp AS version,files.error,pages.page,pages.name,snippet(pages,3,char(1),char(2),' … ',42) AS snippet FROM pages JOIN files ON files.id=pages.file_id WHERE pages MATCH ? ORDER BY bm25(pages,0,0,3,1)", (match,))]
        else:
            rows = []
        photo_ids = {r[0] for r in conn.execute('SELECT file_id FROM photos')}
        for row in rows:
            row['is_image'] = row['id'] in photo_ids
            row['match_type'] = 'text' if words else 'library'
        if words and mode != 'text':
            photos = conn.execute('SELECT photos.file_id,photos.embedding,files.path,files.stamp AS version,pages.name,pages.body FROM photos JOIN files ON files.id=photos.file_id JOIN pages ON pages.file_id=files.id WHERE photos.embedding IS NOT NULL AND photos.model=?', (vision.MODEL_KEY,)).fetchall()
            if photos:
                try:
                    query_vector = vision.encode_query(query[:1000])
                except RuntimeError:
                    if rows:
                        return group_results(rows, conn)
                    raise
                vectors = np.stack([np.frombuffer(p['embedding'], dtype=np.float32) for p in photos])
                scores = vectors @ query_vector
                existing = {row['id']: row for row in rows}
                for idx in np.argsort(-scores):
                    score = float(scores[idx])
                    # Similarity is not a probability. Suppress weak guesses.
                    if score < 0.22:
                        continue
                    photo = photos[int(idx)]
                    if photo['file_id'] in existing:
                        existing[photo['file_id']]['match_type'] = 'text + visual'
                        existing[photo['file_id']]['similarity'] = round(score, 4)
                    else:
                        rows.append({'id': photo['file_id'], 'path': photo['path'], 'version': photo['version'], 'page': 1, 'name': photo['name'], 'snippet': photo['body'][:260], 'is_image': True, 'match_type': 'visual', 'similarity': round(score, 4)})
        return group_results(rows, conn)


def query_words(query):
    words = re.findall(r'\w+', query, re.UNICODE)[:20]
    filler = {'where', 'is', 'are', 'my', 'the', 'a', 'an', 'find', 'show', 'me', 'please', 'for', 'of'}
    meaningful = [word for word in words if word.lower() not in filler]
    return meaningful or words


def group_results(rows, conn):
    counts = dict(conn.execute('SELECT file_id,count(*) FROM pages GROUP BY file_id'))
    grouped = {}
    for row in rows:
        file_id = row['id']
        if file_id in grouped:
            grouped[file_id]['matching_pages'].append(row['page'])
            continue
        row['matching_pages'] = [row['page']]
        row['page_count'] = counts.get(file_id, 1)
        row['kind'] = 'image' if row.get('is_image') else 'pdf' if Path(row['path']).suffix.lower() == '.pdf' else 'text'
        row['available'] = Path(row['path']).is_file()
        row['modified_ns'] = int(row['version'].split(':')[0])
        grouped[file_id] = row
    return list(grouped.values())


def run_job(target, args):
    try:
        target(*args)
    except Exception as error:
        STATE['errors'].append({'file': '', 'error': str(error)})
    finally:
        STATE.update(running=False, stage='', cancelled=CANCEL.is_set())
        CANCEL.clear()


def start_job(target, *args):
    with LOCK:
        if STATE['running']:
            return False
        CANCEL.clear()
        STATE['source_path'] = str(args[0]) if target == index_folder and args else None
        STATE.update(running=True, done=0, total=0, errors=[], warnings=[], stage='Starting import...', cancelled=False)
        threading.Thread(target=run_job, args=(target, args), daemon=True).start()
        return True


def source_list():
    with closing(db()) as conn:
        rows = [dict(row) for row in conn.execute('SELECT * FROM sources ORDER BY id')]
        paths = [Path(row[0]) for row in conn.execute('SELECT path FROM files')]
    for row in rows:
        root = Path(row['path'])
        row['name'] = root.name or str(root)
        row['available'] = root.is_dir()
        row['count'] = sum(p.is_relative_to(root) and (row['scope'] != 'photos' or p.suffix.lower() in IMAGES) for p in paths)
    return rows


def sync_if_changed():
    if STATE['running']:
        return
    for source in source_list():
        if not source['enabled']:
            continue
        root = Path(source['path'])
        if not root.is_dir():
            with closing(db()) as conn, conn:
                conn.execute('UPDATE sources SET error=? WHERE id=?', ('Folder unavailable; existing index kept.', source['id']))
            continue
        try:
            paths = walk_files(root, source['scope'])
            with closing(db()) as conn:
                known = {row['path']: row['stamp'] for row in conn.execute('SELECT path,stamp FROM files') if Path(row['path']).is_relative_to(root) and (source['scope'] != 'photos' or Path(row['path']).suffix.lower() in IMAGES)}
                known.update({row['path']: row['stamp'] for row in conn.execute('SELECT path,stamp FROM failed_files') if Path(row['path']).is_relative_to(root) and (source['scope'] != 'photos' or Path(row['path']).suffix.lower() in IMAGES)})
            current = {str(path): f'{path.stat().st_mtime_ns}:{path.stat().st_size}' for path in paths}
            if current != known:
                start_job(index_folder, root, source['scope'])
                return
            with closing(db()) as conn, conn:
                conn.execute('UPDATE sources SET last_scan=?,error=NULL WHERE id=?', (time.time(), source['id']))
        except OSError:
            continue  # Files can disappear between enumeration and stat; retry next scan.


def start_background_services():
    global WATCHER
    if WATCHER and WATCHER.is_alive():
        return
    SHUTDOWN.clear()
    def watch():
        interval = max(1, float(os.environ.get('PAPERTRAIL_SYNC_SECONDS', '15')))
        while not SHUTDOWN.wait(interval):
            try:
                sync_if_changed()
            except Exception:
                logging.exception('Folder sync failed')
    WATCHER = threading.Thread(target=watch, daemon=True)
    WATCHER.start()


def remove_file(file_id):
    with LOCK:
        if STATE['running']:
            raise RuntimeError('Wait for the import to finish before removing files')
        with closing(db()) as conn, conn:
            file = conn.execute('SELECT * FROM files WHERE id=?', (file_id,)).fetchone()
            if not file:
                raise ValueError('Document not found')
            pages = [dict(r) for r in conn.execute('SELECT * FROM pages WHERE file_id=?', (file_id,))]
            photo = conn.execute('SELECT * FROM photos WHERE file_id=?', (file_id,)).fetchone()
            token = secrets.token_urlsafe(24)
            for key in list(REMOVED):
                if REMOVED[key]['expires'] < time.time():
                    REMOVED.pop(key)
            if len(REMOVED) >= 10:
                REMOVED.pop(next(iter(REMOVED)))
            REMOVED[token] = {'file': dict(file), 'pages': pages, 'photo': dict(photo) if photo else None, 'expires': time.time() + 120}
            conn.execute('INSERT OR IGNORE INTO ignored_paths VALUES(?)', (file['path'],))
            conn.execute('DELETE FROM failed_files WHERE path=?', (file['path'],))
            for table in ['pages', 'photos']:
                conn.execute(f'DELETE FROM {table} WHERE file_id=?', (file_id,))
            conn.execute('DELETE FROM files WHERE id=?', (file_id,))
        changed()
        return token


def restore_file(token):
    with LOCK:
        saved = REMOVED.get(token)
        if not saved or saved['expires'] < time.time():
            REMOVED.pop(token, None)
            raise ValueError('Undo expired. Import the original file again to add it back.')
        file = saved['file']
        with closing(db()) as conn, conn:
            conn.execute('DELETE FROM ignored_paths WHERE path=?', (file['path'],))
            conn.execute('INSERT OR IGNORE INTO files(path,stamp,content_hash,error) VALUES(?,?,?,?)', (file['path'],file['stamp'],file['content_hash'],file['error']))
            new_id = conn.execute('SELECT id FROM files WHERE path=?', (file['path'],)).fetchone()[0]
            conn.execute('DELETE FROM pages WHERE file_id=?', (new_id,))
            conn.executemany('INSERT INTO pages VALUES(?,?,?,?)', [(new_id,p['page'],p['name'],p['body']) for p in saved['pages']])
            if saved['photo']:
                photo = saved['photo']
                conn.execute('INSERT OR REPLACE INTO photos VALUES(?,?,?,?,?)', (new_id,photo['embedding'],photo['model'],photo['thumbnail'],photo['error']))
        REMOVED.pop(token)
        changed()
        return new_id


def pictures_folder():
    if sys.platform == 'win32':
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x27, None, 0, buffer) == 0:
            return buffer.value
    return str(Path.home() / 'Pictures')


def browse_folders(path=''):
    folder = Path(path).expanduser().resolve() if path else Path.home()
    if not folder.is_dir():
        raise ValueError('Folder is unavailable. Connect the drive or choose another location.')
    directories = []
    with os.scandir(folder) as entries:
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False) and not entry.name.startswith('.'):
                    directories.append({'name': entry.name, 'path': str(Path(entry.path).resolve())})
            except OSError:
                continue
    locations = [{'name': 'Home', 'path': str(Path.home())}, {'name': 'Pictures', 'path': pictures_folder()}]
    if sys.platform == 'win32':
        import ctypes
        drives = ctypes.windll.kernel32.GetLogicalDrives()
        locations.extend({'name': chr(65+i) + ':', 'path': chr(65+i) + ':\\'} for i in range(26) if drives & (1 << i))
    else:
        locations.append({'name': 'Computer', 'path': '/'})
    return {'path': str(folder), 'parent': str(folder.parent), 'folders': sorted(directories, key=lambda item: item['name'].casefold()), 'locations': locations}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data, status=200, kind='application/json'):
        body = json.dumps(data).encode() if kind == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' blob:; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        return self.headers.get('X-Papertrail-Token') == TOKEN

    def do_GET(self):
        host = self.headers.get('Host', '').split(':')[0]
        if host not in {'127.0.0.1', 'localhost'}:
            return self.send({'error': 'Invalid host'}, 403)
        url = urlparse(self.path)
        if url.path == '/':
            return self.send((BASE / 'static/index.html').read_bytes().replace(b'__TOKEN__', TOKEN.encode()), kind='text/html; charset=utf-8')
        if url.path in {'/app.js', '/style.css'}:
            return self.send((BASE / 'static' / url.path[1:]).read_bytes(), kind='text/javascript' if url.path.endswith('.js') else 'text/css')
        if not self.authorized():
            return self.send({'error': 'Unauthorized'}, 403)
        if url.path == '/api/browse':
            try:
                return self.send(browse_folders(parse_qs(url.query).get('path', [''])[0]))
            except (OSError, ValueError) as error:
                return self.send({'error': str(error)}, 400)
        if url.path == '/api/sources':
            return self.send({'sources': source_list(), 'pictures': pictures_folder()})
        if url.path == '/api/render':
            params = parse_qs(url.query)
            try:
                page = int(params.get('page', ['1'])[0])
                width = int(params.get('width', ['1500'])[0])
                with closing(db()) as conn:
                    row = conn.execute('SELECT path FROM files WHERE id=?', (params.get('id',[''])[0],)).fetchone()
                if not row or Path(row['path']).suffix.lower() not in IMAGES | {'.pdf'}:
                    return self.send({'error': 'Preview not found'}, 404)
                return self.send(previews.render(row['path'], page, width), kind='image/jpeg')
            except (OSError, ValueError, RuntimeError) as error:
                return self.send({'error': 'Cannot preview this original: ' + str(error)}, 400)
        if url.path == '/api/image':
            params = parse_qs(url.query)
            with closing(db()) as conn:
                row = conn.execute('SELECT thumbnail FROM photos WHERE file_id=?', (params.get('id', [''])[0],)).fetchone()
            if not row:
                return self.send({'error': 'Image not found'}, 404)
            return self.send(row['thumbnail'], kind='image/jpeg')
        if url.path == '/api/preview':
            params = parse_qs(url.query)
            try:
                page = int(params.get('page',['1'])[0])
            except ValueError:
                return self.send({'error': 'Invalid page number'}, 400)
            with closing(db()) as conn:
                row = conn.execute('SELECT files.path,pages.body,pages.page FROM files JOIN pages ON files.id=pages.file_id WHERE files.id=? AND pages.page=?', (params.get('id',[''])[0], page)).fetchone()
            if not row:
                return self.send({'error': 'Document not found'}, 404)
            result = dict(row)
            result['is_image'] = Path(row['path']).suffix.lower() in IMAGES
            result['kind'] = 'image' if result['is_image'] else 'pdf' if Path(row['path']).suffix.lower() == '.pdf' else 'text'
            result['available'] = Path(row['path']).is_file()
            with closing(db()) as conn:
                result['page_count'] = conn.execute('SELECT count(*) FROM pages JOIN files ON files.id=pages.file_id WHERE files.id=?', (params.get('id',[''])[0],)).fetchone()[0]
            return self.send(result)
        if url.path == '/api/search':
            params = parse_qs(url.query)
            try:
                return self.send(search(params.get('q', [''])[0], params.get('mode', ['all'])[0]))
            except RuntimeError as error:
                return self.send({'error': str(error)}, 503)
        if url.path == '/api/status':
            with LOCK:
                for key in list(REMOVED):
                    if REMOVED[key]['expires'] < time.time():
                        REMOVED.pop(key)
            with closing(db()) as conn:
                count = conn.execute('SELECT count(*) FROM files').fetchone()[0]
                photo_rows = [r for r in conn.execute('SELECT files.path,photos.embedding,photos.model FROM files LEFT JOIN photos ON files.id=photos.file_id') if Path(r['path']).suffix.lower() in IMAGES]
                photo_count = len(photo_rows)
                pending = sum(r['embedding'] is None or r['model'] != vision.MODEL_KEY for r in photo_rows)
            return self.send({**STATE, 'count': count, 'photo_count': photo_count, 'pending_photos': pending, 'vision': vision.STATUS, 'revision': REVISION})
        return self.send({'error': 'Not found'}, 404)

    def do_POST(self):
        if not self.authorized() or self.headers.get('Host','').split(':')[0] not in {'127.0.0.1','localhost'}:
            return self.send({'error': 'Unauthorized'}, 403)
        try:
            size = int(self.headers.get('Content-Length', 0))
            if size <= 0 or size > 40 * 1024 * 1024:
                return self.send({'error': 'Request too large'}, 413)
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                return self.send({'error': 'Expected a JSON object'}, 400)
            if self.path == '/api/reindex-photos':
                with closing(db()) as conn:
                    paths = [Path(r[0]) for r in conn.execute('SELECT path FROM files') if Path(r[0]).suffix.lower() in IMAGES]
                if not start_job(index_paths, paths):
                    return self.send({'error': 'An import is already running'}, 409)
                return self.send({'ok': True})
            if self.path == '/api/cancel':
                CANCEL.set()
                if STATE.get('source_path'):
                    with closing(db()) as conn, conn:
                        conn.execute('UPDATE sources SET enabled=0 WHERE path=?', (STATE['source_path'],))
                return self.send({'ok': True})
            if self.path == '/api/upload':
                name = Path(payload['name']).name
                if not name or name in {'.', '..'} or ':' in name:
                    return self.send({'error': 'Invalid filename'}, 400)
                if Path(name).suffix.lower() not in EXTENSIONS:
                    return self.send({'error': 'Unsupported file type'}, 400)
                data = base64.b64decode(payload['data'], validate=True)
                checksum = hashlib.sha256(data).hexdigest()
                with LOCK:
                    if STATE['running']:
                        return self.send({'error': 'An import is running. Please wait or stop it first.'}, 409)
                    with closing(db()) as conn:
                        duplicate = conn.execute('SELECT id FROM files WHERE content_hash=?', (checksum,)).fetchone()
                    if duplicate:
                        return self.send({'ok': True, 'duplicate': True, 'id': duplicate['id']})
                    inbox = DATA / 'uploads' / secrets.token_hex(8)
                    inbox.mkdir(parents=True, exist_ok=True)
                    (inbox / name).write_bytes(data)
                    start_job(index_folder, inbox.resolve())
                return self.send({'ok': True})
            if self.path == '/api/remove':
                return self.send({'ok': True, 'undo_token': remove_file(payload['id'])})
            if self.path == '/api/restore':
                return self.send({'ok': True, 'id': restore_file(payload['undo_token'])})
            if self.path == '/api/import':
                if not isinstance(payload.get('path'), str) or not payload['path'].strip():
                    return self.send({'error': 'Choose a folder or enter its full path.'}, 400)
                folder = Path(payload['path']).expanduser().resolve()
                scope = payload.get('scope', 'all')
                if scope not in {'all', 'photos'}:
                    return self.send({'error': 'Unknown import type'}, 400)
                if not folder.is_dir():
                    return self.send({'error': 'Folder not found'}, 400)
                with LOCK:
                    if STATE['running']:
                        return self.send({'error': 'An import is already running'}, 409)
                    with closing(db()) as conn, conn:
                        conn.execute('INSERT INTO sources(path,scope,enabled) VALUES(?,?,?) ON CONFLICT(path) DO UPDATE SET scope=excluded.scope,enabled=excluded.enabled', (str(folder),scope,int(bool(payload.get('watch', False)))))
                    start_job(index_folder, folder, scope)
                return self.send({'ok': True})
            if self.path in {'/api/source/sync', '/api/source/toggle', '/api/source/disconnect'}:
                with LOCK:
                    if STATE['running']:
                        return self.send({'error': 'Wait for the current import to finish.'}, 409)
                    with closing(db()) as conn, conn:
                        source = conn.execute('SELECT * FROM sources WHERE id=?', (payload['id'],)).fetchone()
                        if not source:
                            return self.send({'error': 'Folder not found'}, 404)
                        if self.path.endswith('/disconnect'):
                            conn.execute('DELETE FROM sources WHERE id=?', (source['id'],))
                        elif self.path.endswith('/toggle'):
                            conn.execute('UPDATE sources SET enabled=? WHERE id=?', (int(bool(payload['enabled'])),source['id']))
                        else:
                            start_job(index_folder, Path(source['path']), source['scope'])
                return self.send({'ok': True})
            if self.path == '/api/open':
                with closing(db()) as conn:
                    row = conn.execute('SELECT path FROM files WHERE id=?', (payload['id'],)).fetchone()
                if not row or not Path(row['path']).is_file():
                    return self.send({'error': 'Original file is unavailable'}, 404)
                if sys.platform == 'win32':
                    os.startfile(row['path'])
                else:
                    subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', row['path']])
                return self.send({'ok': True})
            return self.send({'error': 'Not found'}, 404)
        except RuntimeError as error:
            return self.send({'error': str(error)}, 409)
        except (ValueError, KeyError, OSError, TypeError, subprocess.TimeoutExpired) as error:
            return self.send({'error': str(error)}, 400)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    db().close()
    start_background_services()
    print(f'Papertrail is ready at http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
