#!/usr/bin/env python3
"""Run the private, localhost-only CV application UI.

Idempotent: if this UI is already serving the port, report it and exit 0 instead
of failing with "address already in use". This lets a skill (or a human) call
``mise run ui`` unconditionally at the start of a session without spawning a
duplicate server.

A port that answers is not proof that *this* UI answers -- macOS AirPlay
Receiver squats on 5000, for instance -- so the probe asks for the UI's health
endpoint and refuses to report success for a stranger on the port.
"""

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from apply.local_ui import HEALTH_PATH, HEALTH_TOKEN, create_app  # noqa: E402

HOST = "127.0.0.1"


def probe(url: str, timeout: float = 0.5) -> str | None:
    """Return the health response body from ``url``, or None when nothing answers.

    Any body other than ``HEALTH_TOKEN`` means something else owns the port.
    """

    try:
        with urllib.request.urlopen(f"{url}{HEALTH_PATH}", timeout=timeout) as response:
            return response.read(len(HEALTH_TOKEN) + 1).decode("utf-8", "replace").strip()
    except (urllib.error.HTTPError, ValueError):
        return ""
    except (urllib.error.URLError, OSError):
        return None


if __name__ == "__main__":
    port = int(os.environ.get("APPLY_UI_PORT", "5052"))
    url = f"http://{HOST}:{port}"
    answer = probe(url)
    if answer == HEALTH_TOKEN:
        print(f"UI already running at {url}/jobs")
        raise SystemExit(0)
    if answer is not None:
        print(
            f"port {port} is taken by another server, not this UI.\n"
            f"Set APPLY_UI_PORT to a free port, or free {port} "
            "(on macOS, System Settings > General > AirDrop & Handoff > AirPlay Receiver).",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"starting UI at {url}/jobs (Ctrl+C to stop)")
    create_app(ROOT).run(host=HOST, port=port, debug=False)
