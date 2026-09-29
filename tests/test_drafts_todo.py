import os
import pathlib
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from apply import drafts, workflow  # noqa: E402

REAL_DRAFT = """# Jane Doe — Senior Engineer
jane@example.com

## SUMMARY
Fifteen years building payment systems, lifting coverage 32% to 73%.

## EXPERIENCE
### Staff Engineer, Acme
- Cut checkout latency 40%.
"""


class StaleDraftsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name) / "applications"
        self.root.mkdir(parents=True)

    def _make_application(
        self,
        identifier: str,
        *,
        draft: str,
        feedback: str = "",
        workflow_state: str | None = "drafting",
        application_status: str | None = "draft",
        final_cv: str | None = None,
    ) -> pathlib.Path:
        application = self.root / identifier
        application.mkdir()
        state = f'\nworkflow_state: "{workflow_state}"' if workflow_state is not None else ""
        status = f'\nstatus: "{application_status}"' if application_status is not None else ""
        (application / "meta.yaml").write_text(
            f'company: "Test"{status}{state}\n', encoding="utf-8"
        )
        (application / workflow.DRAFT_NAME).write_text(draft, encoding="utf-8")
        (application / workflow.FEEDBACK_NAME).write_text(feedback, encoding="utf-8")
        if final_cv is not None:
            (application / "cv.md").write_text(final_cv, encoding="utf-8")
        return application

    def _ages(self, path: pathlib.Path, filename: str, *, older: bool) -> None:
        """Nudge one file's mtime so ordering is deterministic on fast disks."""
        target = path / filename
        skew = -10 if older else 10
        stamp = time.time() + skew
        os.utime(target, (stamp, stamp))

    def test_placeholder_draft_needs_first_draft(self):
        self._make_application("2026-07-20_Placeholder", draft=workflow.DRAFT_TEMPLATE)
        stale = drafts.stale_drafts(self.root)
        self.assertEqual([s.identifier for s in stale], ["2026-07-20_Placeholder"])
        self.assertEqual(stale[0].reason, "needs first draft")

    def test_feedback_newer_than_draft_is_stale(self):
        application = self._make_application(
            "2026-07-20_Feedback", draft=REAL_DRAFT, feedback="Tighten the summary."
        )
        self._ages(application, workflow.DRAFT_NAME, older=True)
        self._ages(application, workflow.FEEDBACK_NAME, older=False)
        stale = drafts.stale_drafts(self.root)
        self.assertEqual([s.identifier for s in stale], ["2026-07-20_Feedback"])
        self.assertEqual(stale[0].reason, "new feedback since last draft")

    def test_finalized_application_is_excluded(self):
        application = self._make_application(
            "2026-07-20_Finalized",
            draft=workflow.DRAFT_TEMPLATE,
            workflow_state="finalized",
        )
        # Even a placeholder draft is skipped once finalized.
        self.assertIsNone(drafts.draft_status(application))
        self.assertEqual(drafts.stale_drafts(self.root), [])

    def test_non_draft_application_statuses_are_excluded(self):
        for application_status in (
            "applied",
            "interview",
            "offer",
            "rejected",
            "withdrawn",
        ):
            with self.subTest(application_status=application_status):
                application = self._make_application(
                    f"2026-07-20-{application_status}",
                    draft=workflow.DRAFT_TEMPLATE,
                    application_status=application_status,
                )
                self.assertIsNone(drafts.draft_status(application))

        self.assertEqual(drafts.stale_drafts(self.root), [])

    def test_legacy_finished_cv_is_excluded(self):
        # Older applications completed before workflow_state existed: they have a
        # real cv.md and no cv-draft.md, and must never be re-drafted.
        application = self._make_application(
            "2026-07-06_Legacy",
            draft="",
            workflow_state=None,
            final_cv=REAL_DRAFT,
        )
        self.assertIsNone(drafts.draft_status(application))
        self.assertEqual(drafts.stale_drafts(self.root), [])

    def test_placeholder_final_cv_is_not_treated_as_finished(self):
        # A scaffold-placeholder cv.md must not count as a finished CV.
        self._make_application(
            "2026-07-10_PlaceholderCv",
            draft=workflow.DRAFT_TEMPLATE,
            workflow_state=None,
            final_cv=workflow.DRAFT_TEMPLATE,
        )
        stale = drafts.stale_drafts(self.root)
        self.assertEqual([s.identifier for s in stale], ["2026-07-10_PlaceholderCv"])

    def test_current_draft_without_newer_feedback_is_not_stale(self):
        application = self._make_application(
            "2026-07-20_Current", draft=REAL_DRAFT, feedback="Old notes."
        )
        self._ages(application, workflow.FEEDBACK_NAME, older=True)
        self._ages(application, workflow.DRAFT_NAME, older=False)
        self.assertIsNone(drafts.draft_status(application))
        self.assertEqual(drafts.stale_drafts(self.root), [])


if __name__ == "__main__":
    unittest.main()
