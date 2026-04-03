import threading

import webview
from werkzeug.serving import make_server

from app import app

WINDOW_TITLE = "TriedingView"
HOST = "127.0.0.1"


class FlaskDesktopServer:
    def __init__(self, flask_app):
        self._server = make_server(HOST, 0, flask_app, threaded=True)
        self.port = self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}"

    def start(self):
        self._thread.start()

    def stop(self):
        self._server.shutdown()
        self._thread.join(timeout=5)


def main():
    server = FlaskDesktopServer(app)
    server.start()
    webview.create_window(WINDOW_TITLE, server.url, width=1600, height=1000)
    try:
        webview.start()
    finally:
        server.stop()


if __name__ == "__main__":
    main()
