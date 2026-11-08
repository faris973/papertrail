import threading
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer
from app import Handler, db, start_background_services, SHUTDOWN

if __name__ == '__main__':
    url = 'http://127.0.0.1:8765'
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            existing = b'papertrail-token' in response.read()
    except OSError:
        existing = False
    if existing:
        webbrowser.open(url)
    else:
        db().close()
        start_background_services()
        try:
            server = ThreadingHTTPServer(('127.0.0.1', 8765), Handler)
        except OSError:
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        url = f'http://127.0.0.1:{server.server_port}'
        print(f'Papertrail: {url}\nKeep this window open. Press Ctrl+C to stop.', flush=True)
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            SHUTDOWN.set()
            server.server_close()
