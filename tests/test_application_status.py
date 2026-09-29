import contextlib
import datetime
import io
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from apply import application_status  # noqa: E402
from tools import mark_applied  # noqa: E402


class MarkAppliedTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.application = pathlib.Path(self.temporary.name) / "2026-07-20_Example"
        self.application.mkdir()

    def _write_meta(self, text: str) -> pathlib.Path:
        path = self.application / "meta.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_marks_draft_applied_and_preserves_comments_and_other_fields(self):
        metadata = self._write_meta(
            'company: "Example AB"\n'
            "status: draft        # draft | applied | interview | offer | accepted | rejected | withdrawn\n"
            'date_applied: ""\n'
            'notes: "Keep this"\n'
        )

        recorded_at = datetime.datetime(2026, 7, 21, 22, 30, tzinfo=datetime.UTC)
        with mock.patch.object(
            application_status.applications,
            "_event_moment_and_date",
            return_value=(recorded_at, datetime.date(2026, 7, 21)),
        ):
            result = application_status.mark_applied(
                self.application, today=datetime.date(2026, 7, 20)
            )

        self.assertTrue(result.changed)
        self.assertEqual(result.date_applied, "2026-07-20")
        stored = yaml.safe_load(metadata.read_text(encoding="utf-8"))
        self.assertEqual(stored["status"], "applied")
        self.assertEqual(stored["date_applied"], "2026-07-20")
        self.assertEqual(stored["notes"], "Keep this")
        [event] = stored["events"]
        self.assertEqual(event["kind"], "status_changed")
        self.assertEqual(event["from"], "draft")
        self.assertEqual(event["to"], "applied")
        self.assertEqual(event["when"], "2026-07-21T22:30:00Z")

    def test_already_applied_is_idempotent_and_preserves_original_date(self):
        metadata = self._write_meta(
            'company: "Example AB"\nstatus: applied\ndate_applied: "2026-07-19"\n'
        )
        before = metadata.read_text(encoding="utf-8")

        result = application_status.mark_applied(self.application, today=datetime.date(2026, 7, 20))

        self.assertFalse(result.changed)
        self.assertEqual(result.date_applied, "2026-07-19")
        self.assertEqual(metadata.read_text(encoding="utf-8"), before)

    def test_applied_without_date_fills_the_date_without_inventing_a_transition(self):
        self._write_meta('status: applied\ndate_applied: ""\n')

        result = application_status.mark_applied(self.application, "2026-07-18")

        self.assertTrue(result.changed)
        stored = yaml.safe_load((self.application / "meta.yaml").read_text(encoding="utf-8"))
        self.assertEqual(stored["date_applied"], "2026-07-18")
        self.assertNotIn("events", stored)

    def test_explicit_date_cannot_rewrite_an_existing_application_date(self):
        self._write_meta('status: applied\ndate_applied: "2026-07-19"\n')

        with self.assertRaisesRegex(
            application_status.ApplicationStatusError, "refusing to replace"
        ):
            application_status.mark_applied(self.application, "2026-07-20")

    def test_concurrent_confirmations_report_one_authoritative_change(self):
        metadata = self._write_meta('status: draft\ndate_applied: ""\n')
        results, errors = self._concurrent_confirmations(["2026-07-20", "2026-07-20"])

        self.assertEqual(sorted(result.changed for result in results), [False, True])
        self.assertEqual({result.date_applied for result in results}, {"2026-07-20"})
        self.assertEqual(errors, [])
        stored = yaml.safe_load(metadata.read_text(encoding="utf-8"))
        self.assertEqual(stored["date_applied"], "2026-07-20")
        self.assertEqual(len(stored["events"]), 1)

    def test_concurrent_conflicting_dates_preserve_the_winner(self):
        metadata = self._write_meta('status: draft\ndate_applied: ""\n')
        results, errors = self._concurrent_confirmations(["2026-07-20", "2026-07-21"])

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].changed)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], application_status.ApplicationStatusError)
        self.assertIn("refusing to replace", str(errors[0]))
        stored = yaml.safe_load(metadata.read_text(encoding="utf-8"))
        self.assertEqual(stored["date_applied"], results[0].date_applied)
        self.assertEqual(len(stored["events"]), 1)

    def test_later_status_cannot_regress_to_applied(self):
        self._write_meta('status: interview\ndate_applied: "2026-07-19"\n')

        with self.assertRaisesRegex(application_status.ApplicationStatusError, "interview"):
            application_status.mark_applied(self.application)

    def test_invalid_date_is_rejected_without_writing(self):
        metadata = self._write_meta('status: draft\ndate_applied: ""\n')
        before = metadata.read_text(encoding="utf-8")

        with self.assertRaisesRegex(application_status.ApplicationStatusError, "YYYY-MM-DD"):
            application_status.mark_applied(self.application, "20 July 2026")

        self.assertEqual(metadata.read_text(encoding="utf-8"), before)

    def test_missing_metadata_is_rejected(self):
        with self.assertRaisesRegex(application_status.ApplicationStatusError, "missing"):
            application_status.mark_applied(self.application)

    def test_cli_reports_the_transition(self):
        self._write_meta('status: draft\ndate_applied: ""\n')
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            code = mark_applied.main([str(self.application), "--date", "2026-07-20"])

        self.assertEqual(code, 0)
        self.assertIn(": marked applied on 2026-07-20", output.getvalue())

    def _concurrent_confirmations(
        self, applied_dates: list[str]
    ) -> tuple[list[application_status.AppliedUpdate], list[BaseException]]:
        metadata_path = self.application / "meta.yaml"
        results: list[application_status.AppliedUpdate] = []
        errors: list[BaseException] = []
        result_lock = threading.Lock()
        started = [threading.Event() for _ in applied_dates]
        completed = [threading.Event() for _ in applied_dates]

        def confirm(index: int, applied_on: str) -> None:
            started[index].set()
            try:
                result = application_status.mark_applied(self.application, applied_on)
                with result_lock:
                    results.append(result)
            except BaseException as error:
                with result_lock:
                    errors.append(error)
            finally:
                completed[index].set()

        with application_status.applications._meta_write_transaction(str(metadata_path)):
            threads = [
                threading.Thread(target=confirm, args=(index, applied_on))
                for index, applied_on in enumerate(applied_dates)
            ]
            for thread in threads:
                thread.start()
            self.assertTrue(all(event.wait(1) for event in started))
            self.assertTrue(all(not event.wait(0.05) for event in completed))

        for thread in threads:
            thread.join(1)
            self.assertFalse(thread.is_alive())
        return results, errors


if __name__ == "__main__":
    unittest.main()
