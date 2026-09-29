import json
import pathlib
import re
import sys
import tempfile
import unittest
import urllib.parse
from unittest import mock

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from apply import (  # noqa: E402
    applications,
    catalog,
    local_ui,
    workflow,
)

APPLICATION_ID = "2026-07-10_ParkitSwedenAb"


class LocalUiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.application = self.root / "applications" / APPLICATION_ID
        self.application.mkdir(parents=True)
        (self.root / "profile").mkdir()
        (self.root / "profile" / "master-profile.yaml").write_text(
            "name: Example\n", encoding="utf-8"
        )
        (self.application / "meta.yaml").write_text(
            "company: Parkit Sweden AB\n"
            "role: Fullstack Developer - Parkit\n"
            "status: draft\n"
            "fit_score: 4\n"
            "workflow_state: drafting\n"
            'url: "https://careers.parkit.example/jobs/fullstack"\n',
            encoding="utf-8",
        )
        (self.application / "job.md").write_text(
            "# Parkit Sweden AB — Fullstack Developer - Parkit\n\n"
            "Build React, Node.js, GraphQL, PostgreSQL, and AWS products.\n",
            encoding="utf-8",
        )
        for filename, content in {
            "cv-analysis.md": "# CV analysis\n\nReviewed evidence.\n",
            "cv-feedback.md": "# Next-draft feedback\n\nNo feedback yet.\n",
            "cv-draft.md": "# CV draft\n\nDraft content.\n",
            "cv-review.md": "# CV review\n\nNo check has run.\n",
        }.items():
            (self.application / filename).write_text(content, encoding="utf-8")
        (self.application / "cv-draft.pdf").write_bytes(b"draft-pdf")
        (self.application / "cv.pdf").write_bytes(b"final-pdf")
        self.app = local_ui.create_app(self.root)
        self.client = self.app.test_client()

    def test_list_and_open_application_displays_requested_artifacts(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Parkit Sweden AB", response.data)
        self.assertIn(APPLICATION_ID.encode(), response.data)

        response = self.client.get(f"/applications/{APPLICATION_ID}")

        self.assertEqual(response.status_code, 200)
        for filename in (
            "job.md",
            "meta.yaml",
            "cv-analysis.md",
            "cv-feedback.md",
            "cv-draft.md",
            "cv-review.md",
            "cv-draft.pdf",
            "cv.pdf",
        ):
            self.assertIn(filename.encode(), response.data)
        self.assertIn(b"Build React, Node.js, GraphQL", response.data)

    def test_applications_info_copy_is_loaded_from_the_screen_intent_file(self):
        intent_root = self.root / "docs" / "intent"
        intent_root.mkdir(parents=True)
        intent_path = intent_root / "applications.md"
        canonical = (
            pathlib.Path(local_ui.__file__).resolve().parents[2]
            / "docs"
            / "intent"
            / "applications.md"
        ).read_text(encoding="utf-8")
        intent_path.write_text(
            canonical.replace(
                "Shows every application workspace in one flat list.",
                "Shows the first authored list intent.",
            ).replace(
                "Applications is the campaign overview:",
                "The first authored screen narrative:",
            ),
            encoding="utf-8",
        )

        first = self.client.get("/")
        intent_path.write_text(
            intent_path.read_text(encoding="utf-8").replace("first authored", "revised authored"),
            encoding="utf-8",
        )
        second = self.client.get("/")

        self.assertEqual(first.status_code, 200)
        self.assertIn(b"Shows the first authored list intent.", first.data)
        self.assertIn(b"The first authored screen narrative:", first.data)
        self.assertEqual(second.status_code, 200)
        self.assertIn(b"Shows the revised authored list intent.", second.data)
        self.assertIn(b"The revised authored screen narrative:", second.data)
        self.assertNotIn(b"first authored", second.data)

    def test_info_popover_scroll_close_ignores_scrolling_inside_the_popover(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        body = response.data.decode("utf-8")
        self.assertRegex(
            body,
            r'addEventListener\("scroll",\s*function\s*\(event\)[\s\S]*?'
            r'closest\("\.info-popover"\)[\s\S]*?return;[\s\S]*?closeAll\(\);',
        )

    def test_applications_are_rendered_by_latest_activity_then_folder_name_descending(self):
        (self.application / "meta.yaml").write_text(
            "company: Older open application\n"
            "role: Engineer\n"
            "status: interview\n"
            "date_created: 2026-07-20\n",
            encoding="utf-8",
        )
        fixtures = {
            "2026-07-22_Alpha": (
                "Tied Alpha",
                "accepted",
                "date_created: 2026-07-22\n",
            ),
            "2026-07-22_Zulu": (
                "Tied Zulu",
                "withdrawn",
                "date_created: 2026-07-22\n",
            ),
            "2026-07-01_RecentlyRejected": (
                "Recently rejected",
                "rejected",
                "events:\n  - when: 2026-07-25T09:00:00Z\n    kind: note\n    text: Reply received\n",
            ),
        }
        for identifier, (company, status, activity) in fixtures.items():
            folder = self.root / "applications" / identifier
            folder.mkdir()
            (folder / "meta.yaml").write_text(
                f"company: {company}\nrole: Engineer\nstatus: {status}\n{activity}",
                encoding="utf-8",
            )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        rendered = response.data.decode("utf-8")
        expected_order = [
            "Recently rejected",
            "Tied Zulu",
            "Tied Alpha",
            "Older open application",
        ]
        self.assertEqual(
            sorted(expected_order, key=rendered.index),
            expected_order,
        )

    def test_health_endpoint_identifies_this_ui(self):
        response = self.client.get(local_ui.HEALTH_PATH)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.decode("utf-8"), local_ui.HEALTH_TOKEN)

    def test_application_page_shows_clickable_apply_link_from_meta_url(self):
        response = self.client.get(f"/applications/{APPLICATION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'href="https://careers.parkit.example/jobs/fullstack"', response.data)
        self.assertIn(b"Apply", response.data)

    def test_application_page_omits_apply_link_when_meta_has_no_url(self):
        (self.application / "meta.yaml").write_text(
            "company: No Url AB\nrole: Engineer\nstatus: draft\n", encoding="utf-8"
        )

        response = self.client.get(f"/applications/{APPLICATION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Apply \xe2\x86\x97", response.data)

    def test_legacy_notes_render_as_the_standing_summary_without_events(self):
        (self.application / "meta.yaml").write_text(
            "company: Legacy AB\n"
            "role: Engineer\n"
            "status: draft\n"
            "date_created: 2026-07-20\n"
            "notes: Strong legacy rationale.\n",
            encoding="utf-8",
        )

        response = self.client.get(f"/applications/{APPLICATION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Strong legacy rationale.", response.data)
        self.assertIn(b'data-timeline-key="moment-date_created"', response.data)
        self.assertNotIn(b'data-event-kind="note"', response.data)

    def test_application_timeline_orders_every_moment_and_event_newest_first(self):
        (self.application / "events").mkdir()
        (self.application / "events" / "reply.md").write_text(
            "Thanks for applying.\n", encoding="utf-8"
        )
        (self.application / "meta.yaml").write_text(
            "company: Parkit Sweden AB\n"
            "role: Fullstack Developer - Parkit\n"
            "status: interview\n"
            "fit_score: 4\n"
            "summary: Strong product and platform fit.\n"
            'url: "https://careers.parkit.example/jobs/fullstack"\n'
            "date_fetched: 2026-07-19\n"
            "date_created: 2026-07-20\n"
            "date_applied: 2026-07-21\n"
            "draft_started_at: 2026-07-22T08:00:00Z\n"
            "last_checked_at: 2026-07-23T08:00:00Z\n"
            "finalized_at: 2026-07-23T09:00:00Z\n"
            "events:\n"
            "  - when: 2026-07-24T08:00:00Z\n"
            "    kind: note\n"
            "    text: Hiring manager viewed the application.\n"
            "  - when: 2026-07-25T08:00:00Z\n"
            "    kind: email\n"
            "    direction: incoming\n"
            "    from: hiring@parkit.example\n"
            "    to: candidate@example.com\n"
            "    subject: Interview invitation\n"
            "    ref: events/reply.md\n"
            "  - when: 2026-07-26T08:00:00Z\n"
            "    kind: link\n"
            "    url: https://ats.example/candidate\n"
            "    label: Candidate portal\n"
            "  - when: 2026-07-27T08:00:00Z\n"
            "    kind: status_changed\n"
            "    from: applied\n"
            "    to: interview\n",
            encoding="utf-8",
        )

        response = self.client.get(f"/applications/{APPLICATION_ID}")

        self.assertEqual(response.status_code, 200)
        body = response.data.decode("utf-8")
        self.assertIn('class="page page-shell"', body)
        self.assertIn('class="two-pane"', body)
        self.assertIn("Strong product and platform fit.", body)
        self.assertIn("https://careers.parkit.example/jobs/fullstack", body)
        rendered_keys = re.findall(r'data-timeline-key="([^"]+)"', body)
        self.assertEqual(
            rendered_keys,
            [
                "event-3",
                "event-2",
                "event-1",
                "event-0",
                "moment-finalized_at",
                "moment-last_checked_at",
                "moment-draft_started_at",
                "moment-date_applied",
                "moment-date_created",
                "moment-date_fetched",
                "moment-workspace",
            ],
        )
        self.assertRegex(
            body,
            r'<a(?=[^>]*data-timeline-key="event-3")(?=[^>]*aria-current="true")[^>]*>',
        )
        for label in (
            "Status changed",
            "Candidate portal",
            "Interview invitation",
            "Hiring manager viewed",
            "Application finalized",
            "Draft checked",
            "Draft started",
            "Application submitted",
            "Application created",
            "Posting fetched",
            "Application workspace",
        ):
            self.assertIn(label, body)

    def test_application_info_popovers_cover_its_required_contexts(self):
        (self.application / "meta.yaml").write_text(
            "company: Parkit Sweden AB\n"
            "role: Fullstack Developer - Parkit\n"
            "status: draft\n"
            "date_created: 2026-07-20\n"
            "events:\n"
            "  - when: 2026-07-24T08:00:00Z\n"
            "    kind: note\n"
            "    text: Hiring manager viewed the application.\n",
            encoding="utf-8",
        )

        response = self.client.get(f"/applications/{APPLICATION_ID}")

        self.assertEqual(response.status_code, 200)
        for control_id in (
            "application-screen-info",
            "application-job-card-info",
            "application-status-info",
            "application-events-info",
            "application-selected-event-info",
        ):
            self.assertIn(f'id="{control_id}"'.encode(), response.data)
        self.assertNotIn(b'class="event-info"', response.data)

    def test_unknown_legacy_event_uses_the_generic_selected_event_info(self):
        (self.application / "meta.yaml").write_text(
            "company: Parkit Sweden AB\n"
            "role: Fullstack Developer - Parkit\n"
            "status: draft\n"
            "events:\n"
            "  - when: 2026-07-24T08:00:00Z\n"
            "    kind: calendar\n",
            encoding="utf-8",
        )

        response = self.client.get(f"/applications/{APPLICATION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Shows a stored application event.", response.data)
        self.assertIn(b'id="application-selected-event-info"', response.data)

    def test_workspace_rail_exposes_artifacts_when_only_creation_moments_exist(self):
        (self.application / "meta.yaml").write_text(
            "company: Legacy Interview AB\n"
            "role: Engineer\n"
            "status: interview\n"
            "date_created: 2026-06-22\n"
            "date_applied: 2026-06-22\n"
            "notes: Reached interview before the draft workflow.\n",
            encoding="utf-8",
        )

        default = self.client.get(f"/applications/{APPLICATION_ID}")
        workspace = self.client.get(f"/applications/{APPLICATION_ID}?event=moment-workspace")

        self.assertEqual(default.status_code, 200)
        self.assertIn(b'data-timeline-key="moment-workspace"', default.data)
        self.assertNotIn(b"Save cv-analysis.md", default.data)
        self.assertEqual(workspace.status_code, 200)
        self.assertRegex(
            workspace.data.decode("utf-8"),
            r'<a(?=[^>]*data-timeline-key="moment-workspace")(?=[^>]*aria-current="true")[^>]*>',
        )
        self.assertIn(b"Save cv-analysis.md", workspace.data)
        self.assertIn(b"Save cv-feedback.md", workspace.data)
        self.assertIn(b"Run check", workspace.data)

    def test_selecting_an_event_changes_only_the_detail_pane(self):
        (self.application / "events").mkdir()
        (self.application / "events" / "reply.md").write_text(
            "Please choose an interview time.\n", encoding="utf-8"
        )
        (self.application / "meta.yaml").write_text(
            "company: Parkit Sweden AB\n"
            "role: Fullstack Developer - Parkit\n"
            "status: draft\n"
            "date_created: 2026-07-20\n"
            "events:\n"
            "  - when: 2026-07-24T08:00:00Z\n"
            "    kind: note\n"
            "    text: First observation.\n"
            "  - when: 2026-07-25T08:00:00Z\n"
            "    kind: email\n"
            "    direction: incoming\n"
            "    from: hiring@parkit.example\n"
            "    to: candidate@example.com\n"
            "    subject: Interview invitation\n"
            "    ref: events/reply.md\n",
            encoding="utf-8",
        )
        default = self.client.get(f"/applications/{APPLICATION_ID}")

        selected = self.client.get(f"/applications/{APPLICATION_ID}?event=event-0")

        self.assertEqual(selected.status_code, 200)
        default_body = default.data.decode("utf-8")
        selected_body = selected.data.decode("utf-8")
        self.assertEqual(
            re.findall(r'data-timeline-key="([^"]+)"', default_body),
            re.findall(r'data-timeline-key="([^"]+)"', selected_body),
        )
        self.assertRegex(
            selected_body,
            r'<a(?=[^>]*data-timeline-key="event-0")(?=[^>]*aria-current="true")[^>]*>',
        )
        self.assertIn("First observation.", selected_body)
        self.assertNotIn("Please choose an interview time.", selected_body)

    def test_status_dropdown_writes_head_date_and_event_through_core_in_one_post(self):
        self.app.config["STATUS_NOW"] = "2026-07-26T10:15:00Z"
        before = {
            path.relative_to(self.application): path.read_bytes()
            for path in self.application.rglob("*")
            if path.is_file()
        }

        response = self.client.post(
            f"/applications/{APPLICATION_ID}/status",
            data={"status": "applied"},
        )

        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        self.assertIn("event=event-0", location)
        self.assertIn("#event-event-0", location)
        stored = applications.read_meta(str(self.application / "meta.yaml"))
        self.assertEqual(stored["status"], "applied")
        self.assertEqual(str(stored["date_applied"]), "2026-07-26")
        self.assertEqual(
            stored["events"],
            [
                {
                    "when": "2026-07-26T10:15:00Z",
                    "kind": "status_changed",
                    "from": "draft",
                    "to": "applied",
                }
            ],
        )
        after = {
            path.relative_to(self.application): path.read_bytes()
            for path in self.application.rglob("*")
            if path.is_file()
        }
        self.assertEqual(set(after), set(before))
        self.assertEqual(
            [path for path in after if after[path] != before[path]],
            [pathlib.Path("meta.yaml")],
        )

        rendered = self.client.get(response.headers["Location"])
        self.assertRegex(
            rendered.data.decode("utf-8"),
            r'<option\s+value="applied"\s+selected',
        )
        for status in applications.APPLICATION_STATUSES:
            self.assertIn(f'value="{status}"'.encode(), rendered.data)
        self.assertIn(b'data-natural="true"', rendered.data)

    def test_draft_history_lives_inside_the_selected_draft_event_info(self):
        version = self.application / "drafts" / "001"
        version.mkdir(parents=True)
        (version / "cv-draft.md").write_text("# Archived draft\n", encoding="utf-8")
        (version / "cv-draft.pdf").write_bytes(b"archived-pdf")
        (self.application / "meta.yaml").write_text(
            "company: Parkit Sweden AB\n"
            "role: Fullstack Developer - Parkit\n"
            "status: draft\n"
            "draft_iteration: 2\n"
            "draft_started_at: 2026-07-22T08:00:00Z\n"
            "last_checked_at: 2026-07-23T08:00:00Z\n",
            encoding="utf-8",
        )

        default = self.client.get(f"/applications/{APPLICATION_ID}")
        draft = self.client.get(f"/applications/{APPLICATION_ID}?event=moment-draft_started_at")

        self.assertNotIn(b"cv-draft.md \xc2\xb7 v2", default.data)
        self.assertIn(b'aria-label="selected event Info"', draft.data)
        self.assertIn(b"cv-draft.md \xc2\xb7 v2", draft.data)
        self.assertIn(b"001", draft.data)
        self.assertNotIn(b'<section class="panel version-panel">', draft.data)

    def test_application_page_explains_flow_and_flags_analysis_claims_missing_from_draft(self):
        (self.application / "cv-analysis.md").write_text(
            "# CV analysis\n\nMy React Native experience is closer to 7 years.\n",
            encoding="utf-8",
        )
        with (self.application / "meta.yaml").open("a", encoding="utf-8") as meta:
            meta.write("draft_started_at: 2026-07-22T08:00:00Z\n")

        response = self.client.get(f"/applications/{APPLICATION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Planning and evidence notes", response.data)
        self.assertIn(b"Human instructions for the next draft", response.data)
        self.assertIn(b"Generated candidate CV", response.data)
        self.assertIn(b"cv-draft.md \xc2\xb7 v1", response.data)
        self.assertIn(b"Reads the saved cv-draft.md, job.md, and profile context", response.data)
        self.assertIn(b"Analysis claim not found in draft", response.data)
        self.assertIn(b"7 years", response.data)
        self.assertIn(b"cv-draft.md does not include it", response.data)

    def test_application_page_flags_final_snapshot_when_draft_has_diverged(self):
        (self.application / "cv.md").write_text("# Older approved CV\n", encoding="utf-8")
        with (self.application / "meta.yaml").open("a", encoding="utf-8") as meta:
            meta.write("draft_started_at: 2026-07-22T08:00:00Z\n")

        response = self.client.get(f"/applications/{APPLICATION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Final snapshot is stale", response.data)
        self.assertIn(b"cv.md differs from cv-draft.md", response.data)

    def test_application_page_lists_archived_draft_versions(self):
        version = self.application / "drafts" / "001"
        version.mkdir(parents=True)
        (version / "cv-draft.md").write_text("# Archived draft\n", encoding="utf-8")
        (version / "cv-draft.pdf").write_bytes(b"archived-pdf")
        with (self.application / "meta.yaml").open("a", encoding="utf-8") as meta:
            meta.write("draft_started_at: 2026-07-22T08:00:00Z\n")

        response = self.client.get(f"/applications/{APPLICATION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"001", response.data)
        self.assertIn(b"draft present, PDF present", response.data)

    def test_reopening_application_displays_the_last_persisted_gate_report(self):
        (self.application / "cv-review.md").write_text(
            "# CV review\n\n"
            "Overall gate result: **FAIL**\n\n"
            "## Gates\n\n"
            "- **FAIL — ATS lint:** WEAK: coverage 40%, 2 quantified hits, 300 words\n"
            "  - Action: raise truthful keyword coverage\n",
            encoding="utf-8",
        )
        with (self.application / "meta.yaml").open("a", encoding="utf-8") as meta:
            meta.write("last_checked_at: 2026-07-23T08:00:00Z\n")

        response = self.client.get(f"/applications/{APPLICATION_ID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Latest gates", response.data)
        self.assertIn(b"ATS lint", response.data)
        self.assertIn(b"coverage 40%", response.data)
        self.assertIn(b"raise truthful keyword coverage", response.data)

    def test_pdf_route_serves_existing_pdf_inline(self):
        for filename, expected in (("cv-draft.pdf", b"draft-pdf"), ("cv.pdf", b"final-pdf")):
            with self.subTest(filename=filename):
                response = self.client.get(f"/applications/{APPLICATION_ID}/files/{filename}")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, expected)
                self.assertTrue(response.content_type.startswith("application/pdf"))
                response.close()

    def test_analysis_and_feedback_are_editable_but_generated_draft_is_read_only(self):
        response = self.client.post(
            f"/applications/{APPLICATION_ID}/artifacts/cv-analysis.md",
            data={
                "content": "# Updated analysis\n",
                "selected_event": "moment-workspace",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertRegex(
            response.data.decode("utf-8"),
            r'<a(?=[^>]*data-timeline-key="moment-workspace")(?=[^>]*aria-current="true")[^>]*>',
        )
        self.assertEqual(
            (self.application / "cv-analysis.md").read_text(encoding="utf-8"),
            "# Updated analysis\n",
        )

        response = self.client.post(
            f"/applications/{APPLICATION_ID}/artifacts/cv-feedback.md",
            data={
                "content": "# Next draft\n\nUse the seven-year claim.\n",
                "selected_event": "moment-workspace",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertRegex(
            response.data.decode("utf-8"),
            r'<a(?=[^>]*data-timeline-key="moment-workspace")(?=[^>]*aria-current="true")[^>]*>',
        )
        self.assertEqual(
            (self.application / "cv-feedback.md").read_text(encoding="utf-8"),
            "# Next draft\n\nUse the seven-year claim.\n",
        )

        response = self.client.post(
            f"/applications/{APPLICATION_ID}/artifacts/cv-draft.md",
            data={
                "content": "# Do not change\n",
                "selected_event": "moment-workspace",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"only cv-analysis.md and cv-feedback.md", response.data)
        self.assertEqual(
            (self.application / "cv-draft.md").read_text(encoding="utf-8"),
            "# CV draft\n\nDraft content.\n",
        )

    def test_artifact_check_and_approve_keep_the_selected_timeline_row(self):
        (self.application / "meta.yaml").write_text(
            "company: Parkit Sweden AB\n"
            "role: Fullstack Developer - Parkit\n"
            "status: draft\n"
            "draft_started_at: 2026-07-22T08:00:00Z\n"
            "last_checked_at: 2026-07-23T08:00:00Z\n",
            encoding="utf-8",
        )
        selected = "moment-draft_started_at"
        expected = workflow.CheckResult(
            workflow.WorkflowPaths.for_application(self.application),
            (workflow.Gate("example gate", True, "ok"),),
        )

        saved = self.client.post(
            f"/applications/{APPLICATION_ID}/artifacts/cv-analysis.md",
            data={"content": "# Kept selection\n", "selected_event": selected},
        )
        with mock.patch.object(local_ui.workflow, "check", return_value=expected):
            checked = self.client.post(
                f"/applications/{APPLICATION_ID}/check",
                data={"selected_event": selected},
            )
        with mock.patch.object(local_ui.workflow, "finalize", return_value=expected):
            approved = self.client.post(
                f"/applications/{APPLICATION_ID}/approve",
                data={"confirm": "approve", "selected_event": selected},
            )

        for response in (saved, checked, approved):
            self.assertEqual(response.status_code, 200)
            self.assertRegex(
                response.data.decode("utf-8"),
                rf'<a(?=[^>]*data-timeline-key="{selected}")(?=[^>]*aria-current="true")[^>]*>',
            )
        for response in (checked, approved):
            self.assertIn(b"Latest gates", response.data)
            self.assertIn(b"example gate", response.data)
            self.assertIn(b"PASS", response.data)

    def test_check_delegates_to_workflow_and_displays_returned_gates(self):
        expected = workflow.CheckResult(
            workflow.WorkflowPaths.for_application(self.application),
            (workflow.Gate("example gate", False, "needs attention", ("fix it",)),),
        )
        with mock.patch.object(local_ui.workflow, "check", return_value=expected) as check:
            response = self.client.post(f"/applications/{APPLICATION_ID}/check")

        self.assertEqual(response.status_code, 200)
        check.assert_called_once()
        self.assertIn(b"example gate", response.data)
        self.assertIn(b"FAIL", response.data)
        self.assertIn(b"needs attention", response.data)

    def test_approval_requires_confirmation_and_calls_finalize_explicitly(self):
        expected = workflow.CheckResult(
            workflow.WorkflowPaths.for_application(self.application),
            (workflow.Gate("all gates", True, "passed"),),
        )
        with mock.patch.object(local_ui.workflow, "finalize", return_value=expected) as finalize:
            response = self.client.post(f"/applications/{APPLICATION_ID}/approve")

            self.assertEqual(response.status_code, 400)
            finalize.assert_not_called()

            response = self.client.post(
                f"/applications/{APPLICATION_ID}/approve",
                data={"confirm": "approve"},
            )

        self.assertEqual(response.status_code, 200)
        finalize.assert_called_once_with(
            self.application.resolve(),
            profile_path=None,
            approve=True,
        )
        self.assertIn(b"Approval completed", response.data)

    def test_failed_approval_displays_the_gates_that_refused_promotion(self):
        (self.application / "meta.yaml").write_text(
            "company: Parkit Sweden AB\n"
            "role: Fullstack Developer - Parkit\n"
            "status: draft\n"
            "draft_started_at: 2026-07-22T08:00:00Z\n",
            encoding="utf-8",
        )
        expected = workflow.CheckResult(
            workflow.WorkflowPaths.for_application(self.application),
            (workflow.Gate("ATS lint", False, "coverage is too low", ("add evidence",)),),
        )
        with (
            mock.patch.object(
                local_ui.workflow,
                "finalize",
                side_effect=workflow.WorkflowError("refusing to finalize: gates failed"),
            ) as finalize,
            mock.patch.object(local_ui.workflow, "check", return_value=expected) as check,
        ):
            response = self.client.post(
                f"/applications/{APPLICATION_ID}/approve",
                data={"confirm": "approve", "selected_event": "moment-draft_started_at"},
            )

        self.assertEqual(response.status_code, 409)
        finalize.assert_called_once()
        check.assert_called_once()
        body = response.data.decode("utf-8")
        self.assertRegex(
            body,
            r'<a(?=[^>]*data-timeline-key="moment-draft_started_at")(?=[^>]*aria-current="true")[^>]*>',
        )
        self.assertIn("Latest gates", body)
        self.assertIn("ATS lint", body)
        self.assertIn("coverage is too low", body)


WATERMARK = "2026-07-16T16:14:00+00:00"
NOW = "2026-07-16T16:14:00+00:00"


def _catalog_record(**overrides):
    job_id = overrides.get("job_id", "jobtech:jobsearch.api.jobtechdev.se:31183366")
    # Unique apply URL per job so seed fixtures stay singletons under clustering.
    default_apply = f"https://careers.example.test/{job_id.split(':')[-1]}"
    record = {
        "schema_version": catalog.SCHEMA_VERSION,
        "job_id": job_id,
        "company": "Catalsy AB",
        "title": "Senior Full Stack Developer",
        "location": "Remote, SE",
        "url": default_apply,
        "apply_url": default_apply,
        "listing_url": "",
        "description": (
            "Catalsy is a risk nervous system. AI-native for real — Claude Code is "
            "part of the daily workflow. Stack: TypeScript · Node · Postgres · AWS. "
            "Remote-first, real equity. " + ("More detail. " * 40)
        ),
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
        "retrieved_at": WATERMARK,
        "first_seen": WATERMARK,
        "last_seen": WATERMARK,
        "score": 4,
        "angle": "ai_native",
        "fit_score": 5,
        "fit_breakdown": {"angle": 3, "seniority": 1, "rn": 1},
        "attrs": {
            "employment": "permanent",
            "arrangement": "remote",
            "office_days": None,
            "region": "sweden",
            "pay": {"raw": "", "period": None},
        },
        "hits": ["ai-native", "llm", "typescript"],
        "triage": "open",
        "skip_reason": "",
        "application": "",
        "cluster_id": "",
    }
    record.update(overrides)
    if "url" not in overrides and "apply_url" not in overrides:
        record["url"] = default_apply
        record["apply_url"] = default_apply
    return record


class JobsUiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        (self.root / "applications").mkdir()
        (self.root / "profile").mkdir()
        (self.root / "profile" / "master-profile.yaml").write_text(
            "name: Example\n", encoding="utf-8"
        )
        catalog.write_watermark(str(self.root), WATERMARK)
        self.records = {
            "new": _catalog_record(),
            "closing": _catalog_record(
                job_id="jobtech:jobsearch.api.jobtechdev.se:31205917",
                company="Sinch Sweden AB",
                title="Senior Full-Stack Developer",
                first_seen="2026-07-09T10:00:00+00:00",
                last_seen=WATERMARK,
                deadline="2026-07-24",
                posted="2026-06-23",
                angle="full_stack_lead",
                fit_score=4,
                fit_breakdown={"angle": 2, "seniority": 1, "rn": 0},
                hits=["full-stack", "architect"],
            ),
            "open": _catalog_record(
                job_id="jobtech:jobsearch.api.jobtechdev.se:31198877",
                company="Anyfin",
                title="Senior React Native Engineer",
                first_seen="2026-07-09T10:00:00+00:00",
                last_seen=WATERMARK,
                posted="2026-06-18",
                angle="mobile_product",
                fit_score=4,
                hits=["react native", "mobile"],
            ),
            "interested": _catalog_record(
                job_id="jobtech:jobsearch.api.jobtechdev.se:31150022",
                company="Kry / Livi",
                title="Staff Frontend Engineer",
                first_seen="2026-07-02T10:00:00+00:00",
                last_seen=WATERMARK,
                triage="interested",
                angle="full_stack_lead",
                fit_score=5,
            ),
            "skipped": _catalog_record(
                job_id="jobtech:jobsearch.api.jobtechdev.se:31090011",
                company="Some Agency AB",
                title="WordPress Developer",
                first_seen="2026-07-02T10:00:00+00:00",
                last_seen=WATERMARK,
                triage="skipped",
                skip_reason="Wrong stack — PHP/WordPress agency work",
                fit_score=1,
                angle="full_stack_lead",
                hits=["php"],
            ),
            "stale": _catalog_record(
                job_id="jobtech:jobsearch.api.jobtechdev.se:30000001",
                company="Stale Corp",
                title="Ancient Role",
                first_seen="2026-05-01T10:00:00+00:00",
                last_seen="2026-05-01T10:00:00+00:00",
                fit_score=3,
            ),
        }
        for record in self.records.values():
            catalog.put_record(str(self.root), record)
        self.app = local_ui.create_app(self.root)
        self.app.config["CATALOG_NOW"] = NOW
        self.client = self.app.test_client()

    def test_jobs_route_renders_one_rich_flat_feed_with_default_buckets(self):
        response = self.client.get("/jobs")

        self.assertEqual(response.status_code, 200)
        body = response.data
        self.assertNotIn(b'class="rail-group"', body)
        self.assertIn(b"Sinch Sweden AB", body)
        self.assertIn(b"Catalsy AB", body)
        self.assertIn(b"Anyfin", body)
        self.assertIn(b"Kry / Livi", body)
        self.assertNotIn(b"Some Agency AB", body)
        self.assertNotIn(b"Stale Corp", body)
        self.assertNotIn(b"Ancient Role", body)
        for value in (
            b"Senior Full Stack Developer",
            b"Remote, SE",
            b"ai_native",
            b"Catalsy is a risk nervous system",
            b"ai-native",
            b"typescript",
            b"new",
            b"closes in 8d",
        ):
            self.assertIn(value, body)
        self.assertIn(b'name="angle"', body)
        self.assertIn(b'name="min_fit"', body)
        self.assertIn(b'name="triage"', body)
        self.assertIn(b'name="sort"', body)

    def test_jobs_info_popovers_sit_by_screen_filters_feed_and_detail(self):
        response = self.client.get("/jobs")

        self.assertEqual(response.status_code, 200)
        for control_id in (
            "jobs-screen-info",
            "jobs-filters-info",
            "jobs-feed-info",
            "jobs-detail-info",
        ):
            self.assertIn(f'id="{control_id}"'.encode(), response.data)

    def test_jobs_filters_and_sort_are_repeated_query_parameters(self):
        response = self.client.get(
            "/jobs?angle=full_stack_lead&angle=mobile_product&min_fit=4"
            "&triage=closing&triage=interested&sort=deadline"
        )

        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertIn("Sinch Sweden AB", body)
        self.assertIn("Kry / Livi", body)
        self.assertNotIn("Catalsy AB", body)
        self.assertNotIn("Anyfin", body)
        self.assertNotIn("Some Agency AB", body)
        self.assertLess(body.index("Sinch Sweden AB"), body.index("Kry / Livi"))
        self.assertRegex(body, r'value="full_stack_lead"\s+checked')
        self.assertRegex(body, r'value="mobile_product"\s+checked')
        self.assertRegex(body, r'value="4"\s+selected')
        self.assertRegex(body, r'value="closing"\s+checked')
        self.assertRegex(body, r'value="interested"\s+checked')
        self.assertRegex(body, r'value="deadline"\s+selected')
        self.assertRegex(
            body,
            r'href="/jobs/[^\"]+\?angle=full_stack_lead&amp;angle=mobile_product'
            r"&amp;min_fit=4&amp;triage=closing&amp;triage=interested&amp;sort=deadline#job-",
        )

    def test_jobs_can_show_skipped_and_sort_newest_via_query_parameters(self):
        response = self.client.get("/jobs?triage=skipped&min_fit=0&sort=newest")

        self.assertEqual(response.status_code, 200)
        body = response.data
        self.assertIn(b"Some Agency AB", body)
        self.assertNotIn(b"Catalsy AB", body)
        self.assertNotIn(b"Sinch Sweden AB", body)
        self.assertRegex(body.decode(), r'value="skipped"\s+checked')
        self.assertRegex(body.decode(), r'value="newest"\s+selected')

    def test_jobs_fit_and_newest_sorts_change_the_flat_feed_order(self):
        fit_body = self.client.get("/jobs?sort=fit").data.decode()
        newest_body = self.client.get("/jobs?sort=newest").data.decode()

        self.assertLess(fit_body.index("Catalsy AB"), fit_body.index("Anyfin"))
        self.assertLess(fit_body.index("Catalsy AB"), fit_body.index("Kry / Livi"))
        self.assertLess(newest_body.index("Catalsy AB"), newest_body.index("Kry / Livi"))

    def test_jobs_detail_shows_fit_attrs_dates_cues_and_description(self):
        job_id = self.records["new"]["job_id"]
        response = self.client.get(f"/jobs/{job_id}")

        self.assertEqual(response.status_code, 200)
        body = response.data
        self.assertIn(b"ai_native", body)
        self.assertIn(b">5<", body)
        self.assertIn(b"angle:3", body)
        self.assertIn(b"seniority:1", body)
        self.assertIn(b"rn:1", body)
        self.assertIn(b"emp:permanent", body)
        self.assertIn(b"work:remote", body)
        self.assertIn(b"2026-06-16", body)
        self.assertIn(WATERMARK[:10].encode(), body)
        self.assertIn(b"ai-native", body)
        self.assertIn(b"typescript", body)
        self.assertIn(b"Catalsy is a risk nervous system", body)
        self.assertIn(b"See more", body)

    def test_interested_job_detail_still_offers_skip(self):
        job_id = self.records["interested"]["job_id"]

        response = self.client.get(f"/jobs/{job_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(f'action="/jobs/{job_id}/skip?'.encode(), response.data)
        self.assertIn(b">Skip</button>", response.data)

    def test_interested_scaffolds_application_sets_applied_and_redirects(self):
        job_id = self.records["new"]["job_id"]
        response = self.client.post(f"/jobs/{job_id}/interested", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        self.assertTrue(location.startswith("/applications/"))
        identifier = location.rsplit("/", 1)[-1]
        application = self.root / "applications" / identifier
        self.assertTrue((application / "job.md").is_file())
        self.assertTrue((application / "meta.yaml").is_file())
        meta = (application / "meta.yaml").read_text(encoding="utf-8")
        self.assertIn('angle: "ai_native"', meta)
        self.assertIn("fit_score: 5", meta)
        self.assertIn("discovery_score: 4", meta)
        self.assertIn("job_id: " + json.dumps(job_id), meta)
        record = catalog.load_record(str(self.root), job_id)
        self.assertEqual(record["triage"], "applied")
        self.assertEqual(record["application"], identifier)
        follow = self.client.get(location)
        self.assertEqual(follow.status_code, 200)
        self.assertIn(b"Catalsy AB", follow.data)

    def test_skip_requires_reason_and_persists_so_job_leaves_new(self):
        job_id = self.records["new"]["job_id"]
        missing = self.client.post(f"/jobs/{job_id}/skip", data={"reason": ""})
        self.assertEqual(missing.status_code, 400)
        self.assertIn(b"Skip requires a reason", missing.data)
        record = catalog.load_record(str(self.root), job_id)
        self.assertEqual(record["triage"], "open")

        response = self.client.post(
            f"/jobs/{job_id}/skip",
            data={"reason": "Comp too low for the scope"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        record = catalog.load_record(str(self.root), job_id)
        self.assertEqual(record["triage"], "skipped")
        self.assertEqual(record["skip_reason"], "Comp too low for the scope")
        self.assertIn(b"skipped", response.data)
        self.assertIn(b"Comp too low for the scope", response.data)
        listing = response.data.decode()
        self.assertIn("Catalsy AB", listing)
        self.assertRegex(
            listing,
            r'data-triage="skipped"[\s\S]*?Catalsy AB',
        )

    def test_cluster_mates_show_as_one_row_with_manual_paste_description(self):
        apply_url = "https://careers.cluster.example/jobs/backend"
        winner = _catalog_record(
            job_id="jobtech:jobsearch.api.jobtechdev.se:88008800",
            company="Cluster Winner AB",
            title="Senior Backend Engineer",
            apply_url=apply_url,
            url=apply_url,
            description="Winner body " + ("detail " * 40),
            description_source="search",
            fit_score=3,
        )
        mate = _catalog_record(
            job_id="remotive:remotive.com:88008801",
            company="Cluster Mate",
            title="Backend Engineer",
            apply_url=apply_url,
            url="https://remotive.com/remote-jobs/software-development/backend-88008801",
            description="Short mate",
            description_source="search",
            fit_score=5,
            angle="backend_principal",
        )
        paste = _catalog_record(
            job_id="ingest:clusterpaste001",
            company="Cluster Paste Co",
            title="Backend Engineer",
            apply_url="",
            url=apply_url,
            source_url=apply_url,
            source="ingest",
            description="Curated paste description for the cluster detail pane.",
            description_source="manual-paste",
            fit_score=2,
        )
        for record in (winner, mate, paste):
            catalog.put_record(str(self.root), record)

        listing = self.client.get("/jobs")
        self.assertEqual(listing.status_code, 200)
        body = listing.data.decode()
        self.assertIn("Cluster Winner AB", body)
        self.assertNotIn("Cluster Mate", body)
        self.assertNotIn("Cluster Paste Co", body)
        # Ranking chrome uses cluster_fit_score (max); winner keeps its own fit/angle.
        self.assertRegex(body, r"Cluster Winner AB[\s\S]*?\b5\b")
        self.assertIn("ai_native", body)

        detail = self.client.get(f"/jobs/{mate['job_id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Curated paste description for the cluster detail pane.", detail.data)
        self.assertIn(b"Cluster Winner AB", detail.data)
        # Detail shows the winner's own fit, not the cluster max.
        self.assertIn(b">3<", detail.data)
        winner = catalog.load_record(str(self.root), winner["job_id"])
        self.assertEqual(winner["description_source"], "search")
        self.assertNotEqual(winner["description"], paste["description"])

    def test_opening_job_acknowledges_and_clears_new_badge(self):
        job_id = self.records["new"]["job_id"]
        first = self.client.get(f"/jobs/{job_id}")
        self.assertEqual(first.status_code, 200)
        self.assertNotIn(b'class="badge-new"', first.data)
        record = catalog.load_record(str(self.root), job_id)
        self.assertEqual(record["acknowledged_at"], NOW)
        listing = self.client.get("/jobs").data.decode()
        self.assertNotRegex(listing, r"badge-new[^>]*>[\s\S]*?Catalsy AB")
        self.assertRegex(listing, r'data-triage="open"[\s\S]*?Catalsy AB')

    def test_second_same_day_role_at_company_gets_distinct_application_folder(self):
        first_id = self.records["new"]["job_id"]
        second = _catalog_record(
            job_id="jobtech:jobsearch.api.jobtechdev.se:39990001",
            company="Catalsy AB",
            title="Staff Platform Engineer",
            description="Different role body for platform work. " + ("x " * 40),
            angle="backend_principal",
            fit_score=4,
        )
        catalog.put_record(str(self.root), second)

        first_resp = self.client.post(f"/jobs/{first_id}/interested", follow_redirects=False)
        second_resp = self.client.post(
            f"/jobs/{second['job_id']}/interested", follow_redirects=False
        )
        self.assertEqual(first_resp.status_code, 302)
        self.assertEqual(second_resp.status_code, 302)
        first_folder = first_resp.headers["Location"].rsplit("/", 1)[-1]
        second_folder = second_resp.headers["Location"].rsplit("/", 1)[-1]
        self.assertNotEqual(first_folder, second_folder)
        first_meta = (self.root / "applications" / first_folder / "meta.yaml").read_text(
            encoding="utf-8"
        )
        second_meta = (self.root / "applications" / second_folder / "meta.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn(json.dumps(first_id), first_meta)
        self.assertIn(json.dumps(second["job_id"]), second_meta)
        self.assertIn("Senior Full Stack Developer", first_meta)
        self.assertIn("Staff Platform Engineer", second_meta)
        first_source = json.loads(
            (self.root / "applications" / first_folder / "source.json").read_text(encoding="utf-8")
        )
        second_source = json.loads(
            (self.root / "applications" / second_folder / "source.json").read_text(encoding="utf-8")
        )
        self.assertEqual(first_source["job_id"], first_id)
        self.assertEqual(second_source["job_id"], second["job_id"])
        self.assertNotEqual(first_source["description"], second_source["description"])

    def test_rail_rows_link_to_their_own_fragment_anchor(self):
        body = self.client.get("/jobs").data.decode()
        anchor = local_ui.anchor_id("job", self.records["new"]["job_id"])

        self.assertIn(f'id="{anchor}"', body)
        self.assertIn(f'#{anchor}"', body)

    def test_skip_pins_the_row_without_unhiding_the_skipped_bucket(self):
        job_id = self.records["new"]["job_id"]

        response = self.client.post(
            f"/jobs/{job_id}/skip?angle=ai_native&min_fit=4&triage=open&triage=closing&sort=newest",
            data={"reason": "Comp too low for the scope"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        self.assertIn("angle=ai_native", location)
        self.assertIn("min_fit=4", location)
        self.assertIn("triage=open", location)
        self.assertIn("triage=closing", location)
        self.assertNotIn("triage=skipped", location)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
        self.assertEqual(query["pin"], [job_id])
        self.assertIn("sort=newest", location)
        self.assertTrue(
            location.endswith("#" + local_ui.anchor_id("job", job_id)),
            location,
        )
        followed = self.client.get(location)
        self.assertEqual(followed.status_code, 200)
        body = followed.data.decode()
        self.assertIn(f'id="{local_ui.anchor_id("job", job_id)}"', body)
        # Only the pinned row is unhidden; other skipped jobs stay out of the feed.
        self.assertIn("Catalsy AB", body)
        self.assertNotIn("Some Agency AB", body)
        self.assertNotRegex(body, r'value="skipped"\s+checked')

    def test_landing_page_still_hides_skipped_jobs_after_a_skip(self):
        job_id = self.records["new"]["job_id"]
        self.client.post(
            f"/jobs/{job_id}/skip",
            data={"reason": "Comp too low for the scope"},
            follow_redirects=True,
        )

        body = self.client.get("/jobs").data.decode()

        self.assertNotIn("Catalsy AB", body)
        self.assertNotIn("Some Agency AB", body)

    def test_submitting_zero_triage_boxes_empties_the_feed(self):
        response = self.client.get("/jobs?triage_submitted=1&min_fit=0&sort=fit")

        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertIn("No jobs match these filters", body)
        self.assertNotIn("Catalsy AB", body)
        self.assertNotIn("Sinch Sweden AB", body)
        self.assertNotRegex(body, r'value="open"\s+checked')
        self.assertNotRegex(body, r'value="interested"\s+checked')
        self.assertIn('name="triage_submitted"', body)

    def test_cards_badge_only_new_and_updated_freshness(self):
        body = self.client.get("/jobs").data.decode()

        self.assertIn("badge-new", body)
        self.assertNotIn("badge-freshness", body)
        self.assertNotIn(">unchanged<", body)

    def test_triaged_cards_carry_a_chip_so_a_pinned_skip_is_not_read_as_open(self):
        job_id = self.records["new"]["job_id"]
        location = self.client.post(
            f"/jobs/{job_id}/skip",
            data={"reason": "Comp too low for the scope"},
        ).headers["Location"]

        body = self.client.get(location).data.decode()

        self.assertRegex(body, r'data-triage="skipped"[\s\S]*?badge-triage-skipped')
        self.assertRegex(body, r'data-triage="interested"[\s\S]*?badge-triage-interested')
        # Only the pinned skip and the interested row are marked; open rows stay bare.
        self.assertEqual(body.count("badge-triage-"), 2)

    def test_all_stale_catalog_asks_for_a_fetch_instead_of_wider_filters(self):
        self.app.config["CATALOG_NOW"] = "2026-12-01T09:00:00+00:00"

        response = self.client.get("/jobs")

        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertIn("Every catalog job has gone stale", body)
        self.assertIn("Fetch jobs", body)
        self.assertIn('action="/jobs/enqueue?', body)
        self.assertNotIn("Try widening the feed", body)
        self.assertNotIn("No catalog jobs yet", body)


class TwoPaneShellTests(unittest.TestCase):
    """The shared 70vw two-pane shell both interactive screens are built on."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        (self.root / "applications").mkdir()
        self.app = local_ui.create_app(self.root)
        self.client = self.app.test_client()
        self.templates = pathlib.Path(local_ui.__file__).resolve().parents[2] / "templates"

    def test_anchor_id_makes_a_fragment_safe_id_from_any_job_id(self):
        self.assertEqual(
            local_ui.anchor_id("job", "jobtech:jobsearch.api.jobtechdev.se:39947983"),
            "job-jobtech-jobsearch-api-jobtechdev-se-39947983",
        )
        self.assertEqual(
            local_ui.anchor_id("event", "2026-07-22T09:00:00+00:00"),
            "event-2026-07-22T09-00-00-00-00",
        )
        self.assertEqual(local_ui.anchor_id("job", "///"), "job")

    def test_shell_renders_standalone_with_both_panes(self):
        response = self.client.get("/shell")

        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertIn('class="page page-shell"', body)
        self.assertIn('class="two-pane"', body)
        self.assertIn("card pane pane-rail", body)
        self.assertIn("card pane pane-detail", body)
        self.assertIn("Rail column", body)
        self.assertIn("Detail column", body)

    def test_shell_renders_an_empty_shell_with_no_screen_content(self):
        with self.app.test_request_context("/shell"):
            body = local_ui.render_template("two_pane.html")

        self.assertIn('class="two-pane"', body)
        self.assertIn("Nothing to list yet.", body)
        self.assertIn("Select an item on the left to read it here.", body)

    def test_shell_rail_rows_keep_their_place_via_fragment_anchors(self):
        body = self.client.get("/shell").data.decode()

        self.assertIn('id="demo-rail"', body)
        self.assertIn('href="/shell?item=rail#demo-rail"', body)
        selected = self.client.get("/shell?item=place-keeping").data.decode()
        self.assertIn('id="demo-place-keeping" class="rail-item sel"', selected)

    def test_jobs_screen_adopts_the_shell_instead_of_its_own_layout(self):
        jobs_template = (self.templates / "local_ui" / "jobs.html").read_text(encoding="utf-8")

        self.assertIn('{% extends "two_pane.html" %}', jobs_template)
        # The layout lives only in the shell; screens must not re-declare it.
        self.assertNotIn('class="two-pane"', jobs_template)
        self.assertNotIn("pane-rail", jobs_template)
        self.assertNotIn("pane-detail", jobs_template)

    def test_shell_serves_no_htmx_and_no_client_side_framework(self):
        for path in ("/", "/jobs", "/shell"):
            with self.subTest(path=path):
                rendered = self.client.get(path).data.decode().lower()

                self.assertNotIn("hx-get", rendered)
                self.assertNotIn("hx-post", rendered)
                self.assertNotIn("hx-swap", rendered)
                self.assertNotRegex(rendered, r"""['"][^'"]*htmx[^'"]*\.js['"]""")
                self.assertNotIn("<script src=", rendered)

    def test_jobs_empty_catalog_state_is_actionable_and_does_not_crash(self):
        response = self.client.get("/jobs")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No catalog jobs yet", response.data)
        self.assertIn(b"Fetch jobs", response.data)
        self.assertIn(b'action="/jobs/enqueue?', response.data)
        self.assertIn(b'name="type" value="fetch-jobs"', response.data)


class CommandQueueEnqueueTests(unittest.TestCase):
    """UI enqueue writes exactly one queued request file and nothing else."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name).resolve()
        self.application = self.root / "applications" / APPLICATION_ID
        self.application.mkdir(parents=True)
        (self.application / "meta.yaml").write_text(
            "company: Parkit Sweden AB\n"
            "role: Fullstack Developer - Parkit\n"
            "status: applied\n"
            "fit_score: 4\n"
            "date_applied: 2026-07-20\n"
            "events:\n"
            "  - when: 2026-07-20T09:00:00Z\n"
            "    kind: status_changed\n"
            "    from: draft\n"
            "    to: applied\n",
            encoding="utf-8",
        )
        (self.application / "job.md").write_text("# Job\n", encoding="utf-8")
        for filename in (
            "cv-analysis.md",
            "cv-feedback.md",
            "cv-draft.md",
            "cv-review.md",
        ):
            (self.application / filename).write_text(f"# {filename}\n", encoding="utf-8")
        self.app = local_ui.create_app(self.root)
        self.client = self.app.test_client()

    def _repo_files(self) -> dict[pathlib.Path, bytes]:
        return {
            path.relative_to(self.root): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def test_application_enqueue_drops_exactly_the_queue_file_and_writes_nothing_else(self):
        before = self._repo_files()
        meta_before = (self.application / "meta.yaml").read_text(encoding="utf-8")

        response = self.client.post(
            f"/applications/{APPLICATION_ID}/enqueue",
            data={"type": "capture-email", "selected_event": "event-0"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/applications/{APPLICATION_ID}", response.headers["Location"])

        after = self._repo_files()
        created = sorted(set(after) - set(before))
        self.assertEqual(len(created), 1, created)
        self.assertEqual(created[0].parts[0], "queue")
        self.assertRegex(created[0].name, r"^[\dT]+Z-capture-email-[0-9a-f]+\.yaml$")
        self.assertEqual(
            [path for path in after if path in before and after[path] != before[path]],
            [],
        )
        self.assertEqual(
            (self.application / "meta.yaml").read_text(encoding="utf-8"),
            meta_before,
        )
        stored = yaml.safe_load(after[created[0]])
        self.assertEqual(stored["type"], "capture-email")
        self.assertEqual(stored["target"], f"app: {APPLICATION_ID}")
        self.assertEqual(stored["state"], "queued")
        self.assertNotIn("args", stored)

    def test_jobs_enqueue_drops_exactly_the_queue_file_with_none_target(self):
        before = self._repo_files()

        response = self.client.post(
            "/jobs/enqueue",
            data={"type": "fetch-jobs"},
        )

        self.assertEqual(response.status_code, 302)
        location = urllib.parse.urlparse(response.headers["Location"]).path
        self.assertEqual(location, "/jobs")

        after = self._repo_files()
        created = sorted(set(after) - set(before))
        self.assertEqual(len(created), 1, created)
        self.assertEqual(created[0].parts[0], "queue")
        self.assertRegex(created[0].name, r"^[\dT]+Z-fetch-jobs-[0-9a-f]+\.yaml$")
        self.assertEqual(
            [path for path in after if path in before and after[path] != before[path]],
            [],
        )
        stored = yaml.safe_load(after[created[0]])
        self.assertEqual(
            stored,
            {"type": "fetch-jobs", "target": None, "state": "queued"},
        )

    def test_jobs_enqueue_redirect_preserves_active_filters(self):
        response = self.client.post(
            "/jobs/enqueue?angle=platform&angle=backend&min_fit=3&triage=closing&sort=deadline",
            data={"type": "fetch-jobs"},
        )

        self.assertEqual(response.status_code, 302)
        location = urllib.parse.urlparse(response.headers["Location"])
        self.assertEqual(location.path, "/jobs")
        query = urllib.parse.parse_qs(location.query)
        self.assertEqual(query["angle"], ["platform", "backend"])
        self.assertEqual(query["min_fit"], ["3"])
        self.assertEqual(query["triage"], ["closing"])
        self.assertEqual(query["sort"], ["deadline"])


if __name__ == "__main__":
    unittest.main()
