"""Core tests for the application event model over a temporary ``meta.yaml``."""

import datetime
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from apply import applications as application_core  # noqa: E402
from apply import catalog  # noqa: E402

REPOSITORY = pathlib.Path(__file__).parent.parent

# A meta.yaml in the shape the scaffold writes: flat fields, inline comments,
# and a folded block scalar. Nothing here may change when an event is appended.
FLAT_META = (
    'company: "Example AB"\n'
    'role: "Senior Backend Engineer"\n'
    'angle: "backend_principal"\n'
    "fit_score: 4         # 0-5, see profile/positioning.md job-fit quick test\n"
    "status: applied      # draft | applied | interview | offer | accepted | rejected | withdrawn\n"
    'date_created: "2026-06-15"\n'
    'date_applied: "2026-06-22"\n'
    "summary: >-\n"
    "  Scheduling domain — strong ops wedge.\n"
    "  Worth a tailored draft.\n"
    'draft_started_at: "2026-07-10T12:25:36Z"\n'
)


class ApplicationEventTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.application = pathlib.Path(temporary.name) / "2026-06-15_Example"
        self.application.mkdir()
        self.meta_path = self.application / "meta.yaml"

    def _write_meta(self, text: str = FLAT_META) -> pathlib.Path:
        self.meta_path.write_text(text, encoding="utf-8")
        return self.meta_path

    def _meta(self) -> dict:
        return application_core.read_meta(str(self.meta_path))

    def _append(self, kind: str, fields: dict, **keywords):
        return application_core.append_event(str(self.meta_path), kind, fields, **keywords)

    # --- the list-aware writer ------------------------------------------

    def test_appending_an_event_leaves_every_flat_field_untouched(self):
        self._write_meta()

        self._append("note", {"text": "Recruiter call booked."}, when="2026-07-22T09:00:00Z")

        text = self.meta_path.read_text(encoding="utf-8")
        self.assertTrue(
            text.startswith(FLAT_META),
            f"flat fields were rewritten:\n{text}",
        )
        self.assertEqual(
            self._meta()["events"],
            [{"when": "2026-07-22T09:00:00Z", "kind": "note", "text": "Recruiter call booked."}],
        )

    def test_events_append_in_order_and_reuse_the_existing_block(self):
        self._write_meta()

        self._append("note", {"text": "First"}, when="2026-07-20T09:00:00Z")
        application_core.set_status(str(self.meta_path), "interview", when="2026-07-21T09:00:00Z")
        self._append("link", {"url": "https://jobs.example/dash", "label": "Candidate dashboard"})

        stored = self._meta()["events"]
        self.assertEqual([event["kind"] for event in stored], ["note", "status_changed", "link"])
        self.assertEqual(self.meta_path.read_text(encoding="utf-8").count("\nevents:\n"), 1)

    def test_the_flat_writer_still_works_after_events_exist(self):
        self._write_meta()
        self._append("note", {"text": "First"}, when="2026-07-20T09:00:00Z")

        application_core.update_meta(
            str(self.meta_path),
            {"last_checked_at": "2026-07-23T08:00:00Z"},
            force=True,
        )
        self._append("note", {"text": "Second"}, when="2026-07-24T09:00:00Z")

        meta = self._meta()
        self.assertEqual(meta["status"], "applied")
        self.assertEqual(meta["last_checked_at"], "2026-07-23T08:00:00Z")
        self.assertEqual([event["text"] for event in meta["events"]], ["First", "Second"])

    def test_email_body_becomes_a_sibling_events_file_referenced_by_ref(self):
        self._write_meta()
        body = "Hi Piet,\n\nWe are moving forward with another candidate.\n"

        event = self._append(
            "email",
            {
                "direction": "incoming",
                "from": "recruiter@example.com",
                "to": "piet.groot.kormelink@gmail.com",
                "subject": "Your application",
            },
            when="2026-07-22T10:45:00Z",
            body=body,
        )

        self.assertEqual(event["ref"], "events/20260722T104500Z-email.md")
        payload = self.application / event["ref"]
        self.assertEqual(payload.read_text(encoding="utf-8"), body)
        # meta.yaml stays skimmable: the body lives only in the sibling file.
        self.assertNotIn("moving forward", self.meta_path.read_text(encoding="utf-8"))

    def test_payload_names_never_collide_within_one_second(self):
        self._write_meta()
        fields = {
            "direction": "outgoing",
            "from": "piet.groot.kormelink@gmail.com",
            "to": "recruiter@example.com",
            "subject": "Follow-up",
        }

        first = self._append("email", dict(fields), when="2026-07-22T10:45:00Z", body="One")
        second = self._append("email", dict(fields), when="2026-07-22T10:45:00Z", body="Two")

        self.assertNotEqual(first["ref"], second["ref"])
        self.assertEqual((self.application / second["ref"]).read_text(encoding="utf-8"), "Two\n")

    def test_a_multi_line_note_round_trips_and_leaves_no_trailing_whitespace(self):
        self._write_meta()
        text = "Screening call:\n\n- asked about the regulated-product work\n- take-home due Monday"

        self._append("note", {"text": text}, when="2026-07-22T09:00:00Z")
        self._append("note", {"text": "After"}, when="2026-07-23T09:00:00Z")

        stored = self.meta_path.read_text(encoding="utf-8")
        self.assertEqual([event["text"] for event in self._meta()["events"]], [text, "After"])
        self.assertEqual([line for line in stored.splitlines() if line != line.rstrip()], [])

    def test_a_link_may_carry_a_saved_page_payload(self):
        self._write_meta()

        event = self._append(
            "link",
            {"url": "https://jobs.example/dash", "label": "Candidate dashboard"},
            when="2026-07-22T11:00:00Z",
            body="<html>saved</html>",
            body_suffix=".html",
        )

        self.assertEqual(event["ref"], "events/20260722T110000Z-link.html")
        self.assertTrue((self.application / event["ref"]).exists())

    def test_msg_id_is_kept_for_capture_dedup_and_empty_optionals_are_dropped(self):
        self._write_meta()

        event = self._append(
            "email",
            {
                "direction": "incoming",
                "from": "recruiter@example.com",
                "to": "piet.groot.kormelink@gmail.com",
                "subject": "Your application",
                "msg_id": "gmail:18f0",
            },
            body="body",
        )
        second = self._append(
            "email",
            {
                "direction": "incoming",
                "from": "recruiter@example.com",
                "to": "piet.groot.kormelink@gmail.com",
                "subject": "Your application",
                "msg_id": "",
            },
            body="body",
        )

        self.assertEqual(event["msg_id"], "gmail:18f0")
        self.assertNotIn("msg_id", second)

    # --- the closed enum ------------------------------------------------

    def test_the_kind_enum_is_closed(self):
        self._write_meta()
        before = self.meta_path.read_text(encoding="utf-8")

        with self.assertRaisesRegex(application_core.MetaEventError, "unknown event kind"):
            self._append("interview", {"text": "invented"})

        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), before)

    def test_each_kind_requires_its_documented_fields(self):
        self._write_meta()
        cases = [
            ("status_changed", {"to": "interview"}, "'from'"),
            ("email", {"direction": "incoming", "subject": "Hi"}, "'from'"),
            ("link", {"url": "https://jobs.example"}, "'label'"),
            ("note", {}, "'text'"),
        ]

        for kind, fields, expected in cases:
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(application_core.MetaEventError, expected):
                    self._append(kind, fields)

    def test_unexpected_fields_and_directions_are_rejected(self):
        self._write_meta()

        with self.assertRaisesRegex(application_core.MetaEventError, "unexpected field"):
            self._append("note", {"text": "Hi", "subject": "nope"})
        with self.assertRaisesRegex(application_core.MetaEventError, "direction must be"):
            self._append(
                "email",
                {
                    "direction": "sideways",
                    "from": "a@example.com",
                    "to": "b@example.com",
                    "subject": "Hi",
                },
                body="body",
            )

    def test_only_email_and_link_carry_a_payload_body(self):
        self._write_meta()

        with self.assertRaisesRegex(application_core.MetaEventError, "carry no payload body"):
            self._append("note", {"text": "Hi"}, body="a body")

    def test_a_rejected_event_writes_no_payload_file(self):
        self._write_meta()

        with self.assertRaises(application_core.MetaEventError):
            self._append("email", {"direction": "incoming", "subject": "Hi"}, body="body")

        self.assertFalse((self.application / "events").exists())

    def test_a_failed_meta_write_leaves_no_orphan_payload(self):
        self._write_meta()

        with mock.patch.object(
            application_core, "_atomic_write", side_effect=OSError("simulated meta write failure")
        ):
            with self.assertRaises(OSError):
                self._append(
                    "email",
                    {
                        "direction": "incoming",
                        "from": "recruiter@example.com",
                        "to": "piet.groot.kormelink@gmail.com",
                        "subject": "Your application",
                    },
                    when="2026-07-22T10:45:00Z",
                    body="body",
                )

        self.assertFalse((self.application / "events").exists())
        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), FLAT_META)

    def test_a_failed_payload_write_leaves_no_orphan_events(self):
        self._write_meta()
        real_open = open

        def open_side_effect(path, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            if "events" in str(path) and "w" in mode:
                raise OSError("simulated payload write failure")
            return real_open(path, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=open_side_effect):
            with self.assertRaises(OSError):
                self._append(
                    "email",
                    {
                        "direction": "incoming",
                        "from": "recruiter@example.com",
                        "to": "piet.groot.kormelink@gmail.com",
                        "subject": "Your application",
                    },
                    when="2026-07-22T10:45:00Z",
                    body="body",
                )

        self.assertFalse((self.application / "events").exists())
        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), FLAT_META)

    def test_unparseable_metadata_is_refused_rather_than_overwritten(self):
        broken = self._write_meta("company: [unclosed\n")

        with self.assertRaisesRegex(application_core.MetaEventError, "could not parse"):
            self._append("note", {"text": "Hi"})

        self.assertEqual(broken.read_text(encoding="utf-8"), "company: [unclosed\n")

    def test_a_populated_inline_events_list_is_refused_rather_than_rewritten(self):
        original = 'company: "Example AB"\nevents: [{when: "2026-07-22T09:00:00Z", kind: note}]\n'
        self._write_meta(original)

        with self.assertRaisesRegex(application_core.MetaEventError, "inline events list"):
            self._append("note", {"text": "Hi"})

        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_a_missing_meta_is_never_fabricated(self):
        with self.assertRaisesRegex(application_core.MetaEventError, "missing"):
            self._append("note", {"text": "Hi"})

        self.assertFalse(self.meta_path.exists())

    def test_an_invalid_timestamp_is_refused(self):
        self._write_meta()

        with self.assertRaisesRegex(application_core.MetaEventError, "invalid event timestamp"):
            self._append("note", {"text": "Hi"}, when="22 July 2026")

    def test_event_inputs_reject_naive_instants_and_basic_dates(self):
        self._write_meta()
        original = self.meta_path.read_text(encoding="utf-8")
        cases = (
            ("2026-07-24T09:00:00", "timezone-aware"),
            ("20260724", "YYYY-MM-DD"),
        )

        for when, message in cases:
            with self.subTest(when=when):
                with self.assertRaisesRegex(application_core.MetaEventError, message):
                    self._append("note", {"text": "Hi"}, when=when)
                self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_a_day_only_timestamp_is_stored_as_a_full_utc_instant(self):
        self._write_meta()

        event = self._append("note", {"text": "Hi"}, when="2026-07-22")

        self.assertRegex(event["when"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(self._meta()["events"][-1]["when"], event["when"])

    def test_a_day_only_append_synthesizes_its_clock_inside_the_transaction(self):
        self._write_meta()
        clock_called = threading.Event()
        started = threading.Event()
        completed = threading.Event()
        errors: list[BaseException] = []
        moment = datetime.datetime(2026, 7, 22, 9, tzinfo=datetime.UTC)

        def controlled_clock(when, **_keywords):
            clock_called.set()
            return moment, moment.date()

        def append_note() -> None:
            started.set()
            try:
                self._append("note", {"text": "Hi"}, when="2026-07-22")
            except BaseException as error:
                errors.append(error)
            finally:
                completed.set()

        with mock.patch.object(
            application_core, "_event_moment_and_date", side_effect=controlled_clock
        ):
            with application_core._meta_write_transaction(str(self.meta_path)):
                thread = threading.Thread(target=append_note)
                thread.start()
                self.assertTrue(started.wait(1))
                clock_was_early = clock_called.wait(0.05)
            thread.join(1)

        self.assertFalse(thread.is_alive())
        self.assertFalse(clock_was_early)
        self.assertTrue(completed.is_set())
        self.assertEqual(errors, [])
        self.assertEqual(self._meta()["events"][0]["when"], "2026-07-22T09:00:00Z")

    def test_an_unsupported_posix_timezone_is_rejected(self):
        self._write_meta()
        original = self.meta_path.read_text(encoding="utf-8")

        with mock.patch.dict(
            "os.environ",
            {"TZ": "CET-1CEST,M3.5.0,M10.5.0/3"},
        ):
            with self.assertRaisesRegex(application_core.MetaEventError, "unsupported TZ"):
                self._append("note", {"text": "Hi"}, when="2026-01-22")

        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_date_only_events_require_timezone_rules_but_implicit_instants_do_not(self):
        self._write_meta()
        original = self.meta_path.read_text(encoding="utf-8")
        real_open = open

        def open_without_localtime(path, *args, **kwargs):
            if str(path) == "/etc/localtime":
                raise FileNotFoundError(path)
            return real_open(path, *args, **kwargs)

        with (
            mock.patch.dict("os.environ", {"TZ": ""}),
            mock.patch("builtins.open", side_effect=open_without_localtime),
        ):
            with self.assertRaisesRegex(application_core.MetaEventError, "rule-bearing"):
                self._append("note", {"text": "Dated"}, when="2026-01-22")

            self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)
            self._append("note", {"text": "Current"})

        self.assertEqual(self._meta()["events"][0]["text"], "Current")

    def test_a_local_day_uses_one_aware_instant_near_midnight(self):
        local_timezone = ZoneInfo("Europe/Stockholm")
        local_now = datetime.datetime(
            2026,
            7,
            23,
            0,
            30,
            tzinfo=local_timezone,
        )

        moment, calendar_date = application_core._event_moment_and_date(
            "2026-07-23", now=local_now, local_timezone=local_timezone
        )

        self.assertEqual(moment, datetime.datetime(2026, 7, 22, 22, 30, tzinfo=datetime.UTC))
        self.assertEqual(calendar_date, datetime.date(2026, 7, 23))
        self.assertLessEqual(moment, local_now.astimezone(datetime.UTC))

    def test_a_local_day_uses_the_target_dates_timezone_offset(self):
        summer_now = datetime.datetime(
            2026,
            7,
            23,
            12,
            30,
            tzinfo=datetime.timezone(datetime.timedelta(hours=2)),
        )

        with mock.patch.dict("os.environ", {"TZ": "Europe/Stockholm"}):
            moment, calendar_date = application_core._event_moment_and_date(
                "2026-01-23",
                now=summer_now,
            )

        self.assertEqual(moment, datetime.datetime(2026, 1, 23, 11, 30, tzinfo=datetime.UTC))
        self.assertEqual(calendar_date, datetime.date(2026, 1, 23))

    # --- derived last_activity_at ---------------------------------------

    def test_last_activity_at_is_the_newest_flat_field_or_event(self):
        self._write_meta()
        meta = self._meta()

        self.assertEqual(
            application_core.last_activity_at(meta),
            datetime.datetime(2026, 7, 10, 12, 25, 36, tzinfo=datetime.UTC),
        )

        self._append("note", {"text": "Recruiter call"}, when="2026-07-22T09:00:00Z")

        self.assertEqual(
            application_core.last_activity_at(self._meta()),
            datetime.datetime(2026, 7, 22, 9, 0, 0, tzinfo=datetime.UTC),
        )

    def test_last_activity_at_reads_days_offsets_and_unquoted_yaml_dates(self):
        self._write_meta(
            "date_created: 2026-06-15\n"
            'date_applied: "2026-06-22"\n'
            'date_fetched: "2026-06-14T08:36:15.654312+00:00"\n'
            'last_checked_at: "2026-06-23T06:00:00+02:00"\n'
        )

        self.assertEqual(
            application_core.last_activity_at(self._meta()),
            datetime.datetime(2026, 6, 23, 4, 0, 0, tzinfo=datetime.UTC),
        )

    def test_last_activity_at_ignores_unusable_values_and_may_be_unknown(self):
        self._write_meta('company: "Example AB"\ndate_created: ""\ndate_applied: "soon"\n')

        self.assertIsNone(application_core.last_activity_at(self._meta()))

    def test_last_activity_at_is_never_stored(self):
        self._write_meta()

        self._append("note", {"text": "Recruiter call"})

        self.assertNotIn("last_activity_at", self.meta_path.read_text(encoding="utf-8"))
        self.assertNotIn("last_activity_at", self._meta())

    def test_applications_sort_by_activity_then_folder_name(self):
        newest_event = {"date_created": "2026-06-01", "events": [{"when": "2026-07-24T09:00:00Z"}]}
        applications = [
            ("2026-06-15_Alpha", {"date_created": "2026-06-15"}),
            ("2026-07-01_Bravo", newest_event),
            ("2026-06-15_Zulu", {"date_created": "2026-06-15"}),
            ("2026-05-01_Undated", {}),
        ]

        ordered = sorted(
            applications,
            key=lambda entry: application_core.activity_sort_key(entry[0], entry[1]),
            reverse=True,
        )

        self.assertEqual(
            [identifier for identifier, _ in ordered],
            ["2026-07-01_Bravo", "2026-06-15_Zulu", "2026-06-15_Alpha", "2026-05-01_Undated"],
        )

    # --- back-compat ----------------------------------------------------

    def test_a_flat_only_meta_parses_and_sorts_without_an_events_list(self):
        self._write_meta()
        meta = self._meta()

        self.assertNotIn("events", meta)
        self.assertEqual(application_core.events(meta), [])
        self.assertEqual(
            application_core.activity_sort_key("2026-06-15_Example", meta),
            (
                datetime.datetime(2026, 7, 10, 12, 25, 36, tzinfo=datetime.UTC),
                "2026-06-15_Example",
            ),
        )

    def test_a_meta_still_carrying_notes_reads_as_the_standing_summary(self):
        self._write_meta('company: "Example AB"\nnotes: "Scheduling domain — strong wedge."\n')

        self.assertEqual(
            application_core.summary(self._meta()), "Scheduling domain — strong wedge."
        )

    def test_summary_wins_over_a_leftover_notes_field(self):
        self._write_meta('summary: "The standing rationale."\nnotes: "The old rationale."\n')

        self.assertEqual(application_core.summary(self._meta()), "The standing rationale.")

    def test_the_scaffold_writes_summary_rather_than_notes(self):
        application_core.create_application(
            str(self.application), "Example AB", "Senior Backend Engineer", "2026-06-15"
        )

        meta = self._meta()
        self.assertIn("summary", meta)
        self.assertNotIn("notes", meta)

    def test_events_reading_tolerates_pre_event_and_malformed_lists(self):
        self.assertEqual(application_core.events({}), [])
        self.assertEqual(application_core.events({"events": None}), [])
        self.assertEqual(application_core.events({"events": "not a list"}), [])
        self.assertEqual(
            application_core.events({"events": ["stray", {"when": "2026-07-22T09:00:00Z"}]}),
            [{"when": "2026-07-22T09:00:00Z"}],
        )
        self.assertEqual(
            application_core.indexed_events(
                {"events": ["stray", {"when": "2026-07-22T09:00:00Z"}]}
            ),
            [(1, {"when": "2026-07-22T09:00:00Z"})],
        )

    def test_events_are_returned_oldest_first_whatever_the_file_order(self):
        self._write_meta()
        self._append("note", {"text": "Later"}, when="2026-07-24T09:00:00Z")
        self._append("note", {"text": "Earlier"}, when="2026-07-20T09:00:00Z")

        self.assertEqual(
            [event["text"] for event in application_core.events(self._meta())],
            ["Earlier", "Later"],
        )
        self.assertEqual(
            [index for index, _ in application_core.indexed_events(self._meta())],
            [1, 0],
        )

    def test_appending_to_an_empty_inline_events_list(self):
        self._write_meta('company: "Example AB"\nevents: []\n')

        self._append("note", {"text": "First"}, when="2026-07-22T09:00:00Z")

        self.assertEqual([event["text"] for event in self._meta()["events"]], ["First"])

    def test_tracked_applications_still_parse_and_sort(self):
        """The real corpus in this repository predates the event model."""
        folders = sorted((REPOSITORY / "applications").glob("*/meta.yaml"))
        if not folders:
            self.skipTest("no tracked applications in this checkout")

        for path in folders:
            with self.subTest(application=path.parent.name):
                meta = application_core.read_meta(str(path))
                self.assertTrue(meta, f"{path} did not parse")
                self.assertIsInstance(application_core.events(meta), list)
                self.assertIsNotNone(
                    application_core.last_activity_at(meta),
                    f"{path} has no usable dated field",
                )
                application_core.activity_sort_key(path.parent.name, meta)


class ApplicationStatusWriteThroughTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.meta_path = pathlib.Path(temporary.name) / "meta.yaml"

    def test_setting_status_writes_the_head_and_matching_event_together(self):
        self.meta_path.write_text(
            'company: "Example AB"\n'
            "status: applied      # lifecycle head\n"
            'date_applied: "2026-06-22"\n'
            'summary: "Keep this"\n',
            encoding="utf-8",
        )

        event = application_core.set_status(
            str(self.meta_path), "interview", when="2026-07-22T09:00:00Z"
        )

        meta = application_core.read_meta(str(self.meta_path))
        self.assertEqual(meta["status"], "interview")
        self.assertEqual(
            meta["events"],
            [
                {
                    "when": "2026-07-22T09:00:00Z",
                    "kind": "status_changed",
                    "from": "applied",
                    "to": "interview",
                }
            ],
        )
        self.assertEqual(event, meta["events"][0])
        text = self.meta_path.read_text(encoding="utf-8")
        self.assertIn('status: "interview" # lifecycle head\n', text)
        self.assertIn('summary: "Keep this"\n', text)

    def test_first_entry_into_applied_fills_only_its_flat_date_cache(self):
        self.meta_path.write_text('status: rejected\ndate_applied: ""\n', encoding="utf-8")

        application_core.set_status(
            str(self.meta_path),
            "applied",
            when="2026-07-23T19:15:00Z",
            human_confirmed=False,
        )

        meta = application_core.read_meta(str(self.meta_path))
        self.assertEqual(meta["date_applied"], "2026-07-23")
        self.assertNotIn("date_interview", meta)
        self.assertNotIn("date_offer", meta)

    def test_first_applied_transition_with_prior_history_writes_its_source_day(self):
        self.meta_path.write_text(
            'status: rejected\ndate_applied: ""\n'
            "events:\n"
            "  - when: 2026-07-20T09:00:00Z\n"
            "    kind: status_changed\n"
            "    from: draft\n"
            "    to: rejected\n",
            encoding="utf-8",
        )

        event = application_core.set_status(
            str(self.meta_path),
            "applied",
            when="2026-07-23T00:30:00+02:00",
        )

        assert event is not None
        meta = application_core.read_meta(str(self.meta_path))
        self.assertEqual(event["when"], "2026-07-22T22:30:00Z")
        self.assertEqual(meta["date_applied"], "2026-07-23")
        self.assertEqual(meta["status"], "applied")

    def test_reentering_applied_keeps_the_first_submission_date(self):
        self.meta_path.write_text(
            'status: rejected\ndate_applied: "2026-06-22"\n', encoding="utf-8"
        )

        application_core.set_status(
            str(self.meta_path),
            "applied",
            when="2026-07-23T19:15:00Z",
            human_confirmed=False,
        )

        meta = application_core.read_meta(str(self.meta_path))
        self.assertEqual(meta["date_applied"], "2026-06-22")
        self.assertEqual(meta["status"], "applied")
        self.assertEqual(
            meta["events"],
            [
                {
                    "when": "2026-07-23T19:15:00Z",
                    "kind": "status_changed",
                    "from": "rejected",
                    "to": "applied",
                }
            ],
        )

    def test_reentering_applied_with_empty_date_cache_leaves_it_untouched(self):
        self.meta_path.write_text(
            'status: rejected\ndate_applied: ""\n'
            "events:\n"
            "  - when: 2026-07-20T09:00:00Z\n"
            "    kind: status_changed\n"
            "    from: draft\n"
            "    to: applied\n"
            "  - when: 2026-07-21T09:00:00Z\n"
            "    kind: status_changed\n"
            "    from: applied\n"
            "    to: rejected\n",
            encoding="utf-8",
        )

        event = application_core.set_status(
            str(self.meta_path),
            "applied",
            when="2026-07-23T19:15:00Z",
            applied_on="2026-07-23",
        )

        assert event is not None
        meta = application_core.read_meta(str(self.meta_path))
        self.assertEqual(meta["status"], "applied")
        self.assertEqual(meta["date_applied"], "")
        self.assertEqual(event["from"], "rejected")
        self.assertEqual(event["to"], "applied")
        self.assertEqual(event["when"], "2026-07-23T19:15:00Z")
        self.assertEqual(meta["events"][-1], event)
        self.assertEqual(len(meta["events"]), 3)

    def test_repicking_the_current_status_records_nothing(self):
        original = 'status: applied\ndate_applied: "2026-06-22"\n'
        self.meta_path.write_text(original, encoding="utf-8")

        event = application_core.set_status(
            str(self.meta_path), "applied", when="2026-07-23T19:15:00Z"
        )

        self.assertIsNone(event)
        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_a_stale_status_timestamp_is_rejected_without_writing(self):
        self.meta_path.write_text('status: draft\ndate_applied: ""\n', encoding="utf-8")
        application_core.set_status(
            str(self.meta_path),
            "applied",
            when="2026-07-24T09:00:00Z",
            human_confirmed=True,
        )
        before = self.meta_path.read_text(encoding="utf-8")

        with self.assertRaisesRegex(application_core.MetaEventError, "precedes latest"):
            application_core.set_status(
                str(self.meta_path),
                "interview",
                when="2026-07-23T09:00:00Z",
            )

        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), before)

    def test_an_equal_status_timestamp_and_newer_note_do_not_block_a_transition(self):
        self.meta_path.write_text('status: draft\ndate_applied: ""\n', encoding="utf-8")
        application_core.set_status(
            str(self.meta_path),
            "applied",
            when="2026-07-24T09:00:00Z",
            human_confirmed=True,
        )
        application_core.append_event(
            str(self.meta_path),
            "note",
            {"text": "Later note"},
            when="2026-07-26T09:00:00Z",
        )

        application_core.set_status(
            str(self.meta_path),
            "interview",
            when="2026-07-24T09:00:00Z",
        )

        meta = application_core.read_meta(str(self.meta_path))
        self.assertEqual(meta["status"], "interview")
        status_events = [
            event for event in application_core.events(meta) if event["kind"] == "status_changed"
        ]
        self.assertEqual(status_events[-1]["to"], "interview")

    def test_repicking_the_current_status_ignores_a_stale_timestamp(self):
        original = (
            'status: applied\ndate_applied: "2026-07-24"\n'
            "events:\n"
            "  - when: 2026-07-24T09:00:00Z\n"
            "    kind: status_changed\n"
            "    from: draft\n"
            "    to: applied\n"
        )
        self.meta_path.write_text(original, encoding="utf-8")

        event = application_core.set_status(
            str(self.meta_path),
            "applied",
            when="2026-07-23T09:00:00Z",
        )

        self.assertIsNone(event)
        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_an_applied_head_missing_its_date_cache_gets_it_filled(self):
        self.meta_path.write_text('status: applied\ndate_applied: ""\n', encoding="utf-8")

        event = application_core.set_status(
            str(self.meta_path), "applied", when="2026-07-23T19:15:00Z"
        )

        self.assertIsNone(event)
        meta = application_core.read_meta(str(self.meta_path))
        self.assertEqual(meta["date_applied"], "2026-07-23")
        self.assertNotIn("events", meta)

    def test_an_event_backed_applied_head_refuses_an_unprovable_date_repair(self):
        original = (
            'status: applied\ndate_applied: ""\n'
            "events:\n"
            "  - when: 2026-07-22T22:30:00Z\n"
            "    kind: status_changed\n"
            "    from: draft\n"
            "    to: applied\n"
        )
        self.meta_path.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(
            application_core.MetaEventError,
            "first submission calendar day was not recorded",
        ):
            application_core.set_status(str(self.meta_path), "applied")

        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_matching_utc_date_does_not_authorize_event_backed_repair(self):
        original = (
            'status: applied\ndate_applied: ""\n'
            "events:\n"
            "  - when: 2026-07-24T09:00:00Z\n"
            "    kind: status_changed\n"
            "    from: draft\n"
            "    to: applied\n"
        )
        self.meta_path.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(application_core.MetaEventError, "cannot repair"):
            application_core.confirm_applied(str(self.meta_path), "2026-07-24")

        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_conflicting_event_backed_date_repair_is_rejected_without_writing(self):
        original = (
            'status: applied\ndate_applied: ""\n'
            "events:\n"
            "  - when: 2026-07-24T09:00:00Z\n"
            "    kind: status_changed\n"
            "    from: draft\n"
            "    to: applied\n"
        )
        conflicting_repairs = (
            lambda: application_core.set_status(
                str(self.meta_path),
                "applied",
                when="2026-07-23T09:00:00Z",
            ),
            lambda: application_core.set_status(
                str(self.meta_path),
                "applied",
                applied_on="2026-07-23",
            ),
            lambda: application_core.confirm_applied(
                str(self.meta_path),
                "2026-07-23",
            ),
        )

        for repair in conflicting_repairs:
            with self.subTest(repair=repair):
                self.meta_path.write_text(original, encoding="utf-8")
                with self.assertRaisesRegex(application_core.MetaEventError, "cannot repair"):
                    repair()
                self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_event_backed_date_repair_requires_an_applied_transition(self):
        original = (
            'status: applied\ndate_applied: ""\n'
            "events:\n"
            "  - when: 2026-07-24T09:00:00Z\n"
            "    kind: status_changed\n"
            "    from: draft\n"
            "    to: withdrawn\n"
        )
        self.meta_path.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(
            application_core.MetaEventError, "no transition entering applied"
        ):
            application_core.set_status(str(self.meta_path), "applied")

        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_malformed_status_history_is_reported_before_chronology_checks(self):
        malformed_events = (
            ("  - when: never\n    kind: status_changed\n    from: applied\n    to: interview\n"),
            (
                "  - when: 2026-07-24T09:00:00Z\n"
                "    kind: status_changed\n"
                "    from: screening\n"
                "    to: interview\n"
            ),
            (
                "  - when: 2026-07-24T09:00:00Z\n"
                "    kind: status_changed\n"
                "    from: applied\n"
                "    to: screening\n"
            ),
            (
                "  - when: 2026-07-24T09:00:00Z\n"
                "    kind: status_changed\n"
                "    from: applied\n"
                "    to: applied\n"
            ),
            (
                "  - when: 2026-07-24T09:00:00\n"
                "    kind: status_changed\n"
                "    from: applied\n"
                "    to: interview\n"
            ),
            (
                "  - when: 20260724\n"
                "    kind: status_changed\n"
                "    from: applied\n"
                "    to: interview\n"
            ),
            (
                "  - when: 2026-07-24T09:00:00Z\n"
                "    kind: status_changed\n"
                "    from: applied\n"
                "    to: interview\n"
                "    7: unexpected\n"
                "    extra: unexpected\n"
            ),
        )

        for malformed_event in malformed_events:
            with self.subTest(event=malformed_event):
                original = (
                    f'status: applied\ndate_applied: "2026-07-23"\nevents:\n{malformed_event}'
                )
                self.meta_path.write_text(original, encoding="utf-8")

                with self.assertRaisesRegex(
                    application_core.MetaEventError,
                    "malformed status history event 0",
                ):
                    application_core.set_status(
                        str(self.meta_path),
                        "interview",
                        when="2026-07-25T09:00:00Z",
                    )

                self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_a_date_only_when_keeps_the_application_day_and_writes_an_instant(self):
        self.meta_path.write_text('status: draft\ndate_applied: ""\n', encoding="utf-8")

        event = application_core.set_status(
            str(self.meta_path), "applied", when="2026-07-23", human_confirmed=True
        )

        assert event is not None
        self.assertRegex(event["when"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(
            application_core.read_meta(str(self.meta_path))["date_applied"], "2026-07-23"
        )

    def test_any_non_gated_pick_is_permitted_and_audited(self):
        self.meta_path.write_text("status: rejected\n", encoding="utf-8")

        application_core.set_status(str(self.meta_path), "interview", when="2026-07-23T19:15:00Z")

        meta = application_core.read_meta(str(self.meta_path))
        self.assertEqual(meta["status"], "interview")
        self.assertEqual(meta["events"][-1]["from"], "rejected")
        self.assertEqual(meta["events"][-1]["to"], "interview")

    def test_failed_atomic_replacement_leaves_head_and_history_unchanged(self):
        original = 'status: applied\ndate_applied: "2026-06-22"\n'
        self.meta_path.write_text(original, encoding="utf-8")

        with mock.patch.object(
            application_core, "_atomic_write", side_effect=OSError("simulated failure")
        ):
            with self.assertRaises(OSError):
                application_core.set_status(
                    str(self.meta_path), "offer", when="2026-07-23T19:15:00Z"
                )

        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_draft_to_applied_requires_explicit_human_confirmation(self):
        original = 'status: draft\ndate_applied: ""\n'
        self.meta_path.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(application_core.MetaEventError, "human confirmation"):
            application_core.set_status(str(self.meta_path), "applied", when="2026-07-23T19:15:00Z")

        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_status_enum_and_advisory_graph_are_the_documented_closed_set(self):
        self.assertEqual(
            application_core.APPLICATION_STATUSES,
            ("draft", "applied", "interview", "offer", "accepted", "rejected", "withdrawn"),
        )
        self.assertEqual(
            {
                status: application_core.advisory_next_statuses(status)
                for status in application_core.APPLICATION_STATUSES
            },
            {
                "draft": ("applied", "withdrawn"),
                "applied": ("interview", "rejected", "withdrawn"),
                "interview": ("offer", "rejected", "withdrawn"),
                "offer": ("accepted", "rejected", "withdrawn"),
                "accepted": (),
                "rejected": (),
                "withdrawn": (),
            },
        )

    def test_status_changed_events_reject_values_outside_the_closed_enum(self):
        self.meta_path.write_text("status: draft\n", encoding="utf-8")

        with self.assertRaisesRegex(application_core.MetaEventError, "unknown application status"):
            application_core.append_event(
                str(self.meta_path),
                "status_changed",
                {"from": "draft", "to": "screening"},
                when="2026-07-23T19:15:00Z",
            )

    def test_status_changed_events_require_distinct_endpoints(self):
        original = "status: applied\n"
        self.meta_path.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(application_core.MetaEventError, "endpoints must differ"):
            application_core.append_event(
                str(self.meta_path),
                "status_changed",
                {"from": "applied", "to": "applied"},
                when="2026-07-23T19:15:00Z",
            )

        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_status_changed_cannot_bypass_the_atomic_write_through_api(self):
        original = "status: applied\n"
        self.meta_path.write_text(original, encoding="utf-8")

        with self.assertRaisesRegex(application_core.MetaEventError, "set_status"):
            application_core.append_event(
                str(self.meta_path),
                "status_changed",
                {"from": "applied", "to": "interview"},
                when="2026-07-23T19:15:00Z",
            )

        self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_flat_writer_cannot_bypass_the_owned_status_caches(self):
        original = 'status: draft\ndate_applied: ""\n'
        self.meta_path.write_text(original, encoding="utf-8")

        for values in ({"status": "applied"}, {"date_applied": "2026-07-23"}):
            with self.subTest(values=values):
                with self.assertRaisesRegex(application_core.MetaEventError, "set_status"):
                    application_core.update_meta(str(self.meta_path), values, force=True)
                self.assertEqual(self.meta_path.read_text(encoding="utf-8"), original)

    def test_every_meta_writer_uses_the_shared_transaction_boundary(self):
        writers = {
            "flat": lambda: application_core.update_meta(
                str(self.meta_path), {"last_checked_at": "2026-07-24T09:00:00Z"}, force=True
            ),
            "event": lambda: application_core.append_event(
                str(self.meta_path),
                "note",
                {"text": "Concurrent note"},
                when="2026-07-24T09:00:00Z",
            ),
            "status": lambda: application_core.set_status(
                str(self.meta_path), "offer", when="2026-07-24T09:00:00Z"
            ),
        }

        for name, writer in writers.items():
            with self.subTest(writer=name):
                self.meta_path.write_text(
                    'status: interview\ndate_applied: "2026-06-22"\n', encoding="utf-8"
                )
                started = threading.Event()
                completed = threading.Event()
                errors: list[BaseException] = []

                def run_writer(
                    started=started,
                    writer=writer,
                    errors=errors,
                    completed=completed,
                ):
                    started.set()
                    try:
                        writer()
                    except BaseException as error:
                        errors.append(error)
                    finally:
                        completed.set()

                with application_core._meta_write_transaction(str(self.meta_path)):
                    thread = threading.Thread(target=run_writer)
                    thread.start()
                    self.assertTrue(started.wait(1))
                    self.assertFalse(completed.wait(0.05))

                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])

    def test_synthesized_status_times_follow_locked_commit_order(self):
        for when in (None, "2026-07-24"):
            with self.subTest(when=when):
                self._assert_synthesized_status_time_follows_locked_commit_order(when)

    def _assert_synthesized_status_time_follows_locked_commit_order(self, when: str | None) -> None:
        self.meta_path.write_text('status: draft\ndate_applied: ""\n', encoding="utf-8")
        first_clock_entered = threading.Event()
        second_clock_entered = threading.Event()
        release_first_clock = threading.Event()
        call_lock = threading.Lock()
        call_count = 0
        clock_inputs: list[str | None] = []
        errors: list[BaseException] = []

        def controlled_clock(supplied_when, **_keywords):
            nonlocal call_count
            with call_lock:
                call_index = call_count
                call_count += 1
                clock_inputs.append(supplied_when)
            if call_index == 0:
                first_clock_entered.set()
                if not release_first_clock.wait(1):
                    raise TimeoutError("first generated clock remained blocked")
            else:
                second_clock_entered.set()
            moment = datetime.datetime(2026, 7, 24, 9 + call_index, tzinfo=datetime.UTC)
            return moment, moment.date()

        def change_status(status: str, completed: threading.Event) -> None:
            try:
                application_core.set_status(str(self.meta_path), status, when=when)
            except BaseException as error:
                errors.append(error)
            finally:
                completed.set()

        first_completed = threading.Event()
        second_completed = threading.Event()
        with mock.patch.object(
            application_core, "_event_moment_and_date", side_effect=controlled_clock
        ):
            first = threading.Thread(target=change_status, args=("interview", first_completed))
            first.start()
            self.assertTrue(first_clock_entered.wait(1))

            second = threading.Thread(target=change_status, args=("offer", second_completed))
            second.start()
            second_clock_was_early = second_clock_entered.wait(0.05)
            if second_clock_was_early:
                self.assertTrue(second_completed.wait(1))
            release_first_clock.set()

            first.join(1)
            second.join(1)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertFalse(second_clock_was_early)
        self.assertEqual(errors, [])
        self.assertEqual(clock_inputs, [when, when])
        meta = application_core.read_meta(str(self.meta_path))
        self.assertEqual(meta["status"], "offer")
        self.assertEqual(application_core.events(meta)[-1]["to"], meta["status"])


class EventTimestampTests(unittest.TestCase):
    def test_new_events_are_stamped_in_whole_second_utc(self):
        moment = datetime.datetime(
            2026, 7, 22, 12, 45, 30, 123456, tzinfo=datetime.timezone(datetime.timedelta(hours=2))
        )

        self.assertEqual(application_core.event_timestamp(moment), "2026-07-22T10:45:30Z")

    def test_a_generated_stamp_round_trips_through_yaml(self):
        stamp = application_core.event_timestamp()
        stored = yaml.safe_load(f"when: {yaml.safe_dump(stamp).strip()}\n")

        self.assertEqual(
            application_core.parse_timestamp(stored["when"]).isoformat(),
            application_core.parse_timestamp(stamp).isoformat(),
        )


class GenesisNoteScaffoldTests(unittest.TestCase):
    """Scaffold-from-catalog writes one genesis note so the Application stands alone."""

    JOB_ID = "jobtech:jobsearch.api.jobtechdev.se:31183366"
    FIRST_SEEN = "2026-07-02T10:00:00+00:00"
    INTERESTED_DAY = "2026-07-10"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        (self.root / "applications").mkdir()
        catalog.put_record(
            str(self.root),
            {
                "schema_version": catalog.SCHEMA_VERSION,
                "job_id": self.JOB_ID,
                "company": "Catalsy AB",
                "title": "Senior Full Stack Developer",
                "location": "Remote, SE",
                "url": "https://careers.example.test/31183366",
                "apply_url": "https://careers.example.test/31183366",
                "listing_url": "",
                "description": "AI-native TypeScript role.",
                "posted": "2026-06-16",
                "deadline": "",
                "source": "jobtech",
                "source_id": "31183366",
                "source_ref": "jobsearch.api.jobtechdev.se",
                "source_queries": ["typescript developer"],
                "description_source": "jobtech-detail",
                "detail_url": "https://jobtech.example/31183366",
                "hn_thread_id": "",
                "source_url": "",
                "raw_paste": "",
                "ingested_at": "",
                "parsed_by": "",
                "parse_confirmed": False,
                "retrieved_at": self.FIRST_SEEN,
                "first_seen": self.FIRST_SEEN,
                "last_seen": self.FIRST_SEEN,
                "score": 4,
                "angle": "ai_native",
                "fit_score": 5,
                "fit_breakdown": {"angle": 3, "seniority": 1, "rn": 1},
                "attrs": {},
                "hits": ["ai-native", "typescript"],
                "triage": "open",
                "skip_reason": "",
                "application": "",
                "acknowledged_at": "",
                "cluster_id": "",
            },
        )

    def test_scaffold_from_catalog_writes_exactly_one_genesis_note(self):
        identifier = application_core.scaffold_from_catalog(
            str(self.root), self.JOB_ID, date=self.INTERESTED_DAY
        )

        meta_path = self.root / "applications" / identifier / "meta.yaml"
        meta = application_core.read_meta(str(meta_path))
        stored = application_core.events(meta)

        self.assertEqual(len(stored), 1)
        event = stored[0]
        self.assertEqual(event["kind"], "note")
        self.assertEqual(event["when"], "2026-07-02T10:00:00Z")
        text = event["text"]
        self.assertIn("Discovered in catalog", text)
        self.assertIn("first seen 2026-07-02", text)
        self.assertIn(f"interested {self.INTERESTED_DAY}", text)
        self.assertIn("fit 5", text)
        self.assertIn("ai_native angle", text)
        # No new event kind; note is the only entry and still a plain note.
        self.assertEqual(application_core.EVENT_KINDS, ("status_changed", "email", "link", "note"))
        self.assertNotIn("genesis", application_core.EVENT_KINDS)

    def test_re_scaffold_does_not_duplicate_the_genesis_note(self):
        application_core.scaffold_from_catalog(
            str(self.root), self.JOB_ID, date=self.INTERESTED_DAY
        )
        application_core.scaffold_from_catalog(
            str(self.root), self.JOB_ID, date=self.INTERESTED_DAY
        )

        apps = list((self.root / "applications").iterdir())
        self.assertEqual(len(apps), 1)
        stored = application_core.events(application_core.read_meta(str(apps[0] / "meta.yaml")))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["kind"], "note")

    def test_an_unwritable_genesis_note_still_leaves_the_job_triaged(self):
        identifier = application_core.application_identifier(
            self.INTERESTED_DAY,
            "Catalsy AB",
            "Senior Full Stack Developer",
            self.JOB_ID,
            str(self.root / "applications"),
        )
        folder = self.root / "applications" / identifier
        folder.mkdir()
        (folder / "meta.yaml").write_text(
            f'company: "Catalsy AB"\njob_id: "{self.JOB_ID}"\nevents: ["not an event"]\n',
            encoding="utf-8",
        )

        with self.assertRaises(application_core.MetaEventError) as caught:
            application_core.scaffold_from_catalog(
                str(self.root), self.JOB_ID, date=self.INTERESTED_DAY
            )

        message = str(caught.exception)
        self.assertIn(identifier, message)
        self.assertIn("inline events list", message)
        record = catalog.load_record(str(self.root), self.JOB_ID)
        self.assertEqual(record["triage"], "applied")
        self.assertEqual(record["application"], identifier)

    def test_genesis_note_text_carries_catalog_provenance(self):
        text = application_core.genesis_note_text(
            {
                "first_seen": self.FIRST_SEEN,
                "fit_score": 5,
                "angle": "ai_native",
            },
            self.INTERESTED_DAY,
        )

        self.assertEqual(
            text,
            "Discovered in catalog · first seen 2026-07-02 · interested 2026-07-10"
            " · fit 5, ai_native angle",
        )


if __name__ == "__main__":
    unittest.main()
