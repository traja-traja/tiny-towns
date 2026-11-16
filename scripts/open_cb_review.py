"""Open the completed local CB map and report; no downloads or rebuilding."""
from functools import partial
from http.client import HTTPConnection
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import threading
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    '/cities/ceske-budejovice/experiments/report.html',
    '/.work/.preview/ceske-budejovice/site/index.html',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check both pages without opening a browser')
    args = parser.parse_args()
    for page in PAGES:
        if not (ROOT / page.lstrip('/')).is_file():
            raise SystemExit('Missing completed output: ' + page)
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    # A free port avoids interrupting an already running Velesin preview.
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        # Verify the actual files through the same server before showing URLs.
        for page in PAGES:
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=10)
            try:
                connection.request('GET', page)
                response = connection.getresponse()
                assert response.status == 200, (page, response.status)
                assert 'text/html' in response.getheader('Content-Type', '')
                assert len(response.read()) > 1000, page
            finally:
                connection.close()
            print(base + page, flush=True)
        if args.check:
            print('Both local pages passed the HTTP check.', flush=True)
            return
        for page in PAGES:
            webbrowser.open_new_tab(base + page)
        print('Keep this window open while using the map. Press Ctrl+C to stop.', flush=True)
        try:
            worker.join()
        except KeyboardInterrupt:
            pass
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


if __name__ == '__main__':
    main()
