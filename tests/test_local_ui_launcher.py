import http.server
import pathlib
import socket
import sys
import threading
import unittest

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from apply import local_ui  # noqa: E402
from tools import local_ui as launcher  # noqa: E402


class _Handler(http.server.BaseHTTPRequestHandler):
    """Answers every path with a body that is not the UI's health token."""

    body = b"AirTunes"

    def do_GET(self):  # noqa: N802 - http.server's required spelling
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class LauncherProbeTests(unittest.TestCase):
    def test_probe_reports_nothing_listening_on_a_free_port(self):
        self.assertIsNone(launcher.probe(f"http://127.0.0.1:{_free_port()}"))

    def test_probe_distinguishes_a_stranger_on_the_port_from_this_ui(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}"

        answer = launcher.probe(url)

        self.assertIsNotNone(answer)
        self.assertNotEqual(answer, local_ui.HEALTH_TOKEN)


if __name__ == "__main__":
    unittest.main()
