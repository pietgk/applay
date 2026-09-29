"""Unit tests for the command-queue enqueue seam (ADR-0008)."""

from __future__ import annotations

import datetime
import pathlib
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from apply import queue  # noqa: E402


class QueueEnqueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name).resolve()

    def test_enqueue_writes_queued_request_with_app_target(self):
        path = queue.enqueue(
            self.root,
            "refresh-draft",
            target=queue.app_target("2026-07-10_ParkitSwedenAb"),
            when=datetime.datetime(2026, 7, 27, 10, 0, 0, tzinfo=datetime.UTC),
        )

        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, queue.queue_dir(self.root))
        self.assertEqual(
            yaml.safe_load(path.read_text(encoding="utf-8")),
            {
                "type": "refresh-draft",
                "target": "app: 2026-07-10_ParkitSwedenAb",
                "state": "queued",
            },
        )

    def test_enqueue_rejects_unknown_type_and_writes_nothing(self):
        with self.assertRaises(queue.QueueError):
            queue.enqueue(self.root, "not-a-command")
        self.assertFalse((self.root / "queue").exists())

    def test_enqueue_includes_optional_args_only_when_provided(self):
        path = queue.enqueue(
            self.root,
            "re-check",
            target="app: demo",
            args={"focus": "claims"},
            when=datetime.datetime(2026, 7, 27, 11, 0, 0, tzinfo=datetime.UTC),
        )

        stored = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(stored["args"], {"focus": "claims"})
        self.assertEqual(stored["state"], "queued")

    def test_enqueue_rejects_application_command_without_app_target(self):
        with self.assertRaisesRegex(queue.QueueError, "requires an application target"):
            queue.enqueue(self.root, "capture-email", target=None)
        self.assertFalse((self.root / "queue").exists())

    def test_enqueue_rejects_jobs_command_with_any_target(self):
        with self.assertRaisesRegex(queue.QueueError, "does not accept a target"):
            queue.enqueue(self.root, "fetch-jobs", target=queue.app_target("demo"))
        self.assertFalse((self.root / "queue").exists())


if __name__ == "__main__":
    unittest.main()
