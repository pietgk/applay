import contextlib
import datetime
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from apply import applications as application_core  # noqa: E402
from apply import ats as ats_core  # noqa: E402
from apply import catalog as catalog_core  # noqa: E402
from apply import fetch as fetch_core  # noqa: E402
from apply import ingest as ingest_core  # noqa: E402
from apply import jobs as jobs_core  # noqa: E402
from apply import rendering as rendering_core  # noqa: E402
from apply import workflow as workflow_core  # noqa: E402
from tools import ats_lint, cv_workflow, jobs_fetch, new_application, render_cv

ROOT = pathlib.Path(__file__).parent
FIXTURES = ROOT / "fixtures"


class JobImportTests(unittest.TestCase):
    def test_package_scaffold_keeps_legacy_role_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            application_core.create_application(directory, "Example Mobility", "", "2026-07-10")

            job_text = (pathlib.Path(directory) / "job.md").read_text(encoding="utf-8")
            self.assertIn("# Example Mobility — role", job_text)

    def test_report_selection_and_import_preserve_provenance(self):
        jobs = new_application.load_report(str(FIXTURES / "import-report.jsonl"))
        job = new_application.select_report_job(jobs, match="Example Mobility")

        self.assertEqual(job["job_id"], "jobtech:jobsearch.api.jobtechdev.se:999001")
        imported = new_application.imported_job_markdown(
            job["company"], job["title"], "reports/jobs-2026-07-10.jsonl", job
        )
        self.assertIn("<!-- job-id: jobtech:jobsearch.api.jobtechdev.se:999001 -->", imported)
        self.assertIn("Permanent role in Stockholm.", imported)

        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            (folder / "job.md").write_text(
                f"# {job['company']} — {job['title']}\n\n{new_application.JOB_PLACEHOLDER}\n",
                encoding="utf-8",
            )
            (folder / "meta.yaml").write_text(
                "company: Example Mobility\nrole: Senior Backend Engineer\nstatus: draft\n",
                encoding="utf-8",
            )
            new_application.scaffold_from_report(
                str(folder), job["company"], job["title"], "report.jsonl", job
            )

            source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
            metadata = (folder / "meta.yaml").read_text(encoding="utf-8")
            self.assertEqual(source["job_id"], job["job_id"])
            self.assertIn('source: "jobtech"', metadata)
            self.assertIn('job_id: "jobtech:jobsearch.api.jobtechdev.se:999001"', metadata)
            self.assertIn("Permanent role in Stockholm.", (folder / "job.md").read_text())

    def test_edited_snapshot_is_preserved_on_refresh(self):
        jobs = new_application.load_report(str(FIXTURES / "import-report.jsonl"))
        job = jobs[0]
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            (folder / "job.md").write_text(
                "# Example Mobility — Senior Backend Engineer\n\nMy reviewed notes.\n",
                encoding="utf-8",
            )
            (folder / "source.json").write_text(json.dumps(job), encoding="utf-8")
            new_application.scaffold_from_report(
                str(folder), job["company"], job["title"], "report.jsonl", job
            )

            self.assertIn("My reviewed notes", (folder / "job.md").read_text())
            self.assertIn("Permanent role in Stockholm", (folder / "job.md.new").read_text())

    def test_jobtech_refresh_uses_detail_and_preserves_shortlist_fields(self):
        job = new_application.load_report(str(FIXTURES / "import-report.jsonl"))[0]
        refreshed = {
            "job_id": job["job_id"],
            "company": job["company"],
            "title": job["title"],
            "description": "Current detail description.",
            "source": "jobtech",
            "source_id": "999001",
        }
        with mock.patch.object(
            new_application, "fetch_jobtech_ad", return_value=refreshed
        ) as fetch:
            result = new_application.refresh_job(job)

        fetch.assert_called_once_with("999001")
        self.assertEqual(result["description"], "Current detail description.")
        self.assertEqual(result["score"], job["score"])
        self.assertEqual(result["attrs"], job["attrs"])
        self.assertEqual(result["source_queries"], job["source_queries"])


class OfflineSourceTests(unittest.TestCase):
    def test_jobtech_detail_normalizes_transport_noise(self):
        payload = {
            "id": "123456",
            "headline": "Fullstack Developer",
            "employer": {"workplace": "Example AB"},
            "workplace_address": {"city": "Stockholm", "country": "Sverige"},
            "application_details": {"url": "https://example.test/apply"},
            "webpage_url": "https://example.test/listing",
            "description": {"text": "React\u200d/TypeScript\r\n\r\nPostgres"},
            "employment_type": {"label": "Vanlig anställning"},
            "duration": {"label": "Tills vidare"},
        }
        with mock.patch.object(jobs_fetch, "get", return_value=payload):
            record = jobs_fetch.fetch_jobtech_ad("123456")

        self.assertEqual(record["job_id"], "jobtech:jobsearch.api.jobtechdev.se:123456")
        self.assertEqual(record["description"], "React/TypeScript\n\nPostgres")
        self.assertEqual(record["company"], "Example AB")

    def test_package_jobtech_detail_matches_cli_normalization(self):
        payload = {
            "id": "123456",
            "headline": "Fullstack Developer",
            "employer": {"workplace": "Example AB"},
            "description": {"text": "React\u200d/TypeScript\r\n\r\nPostgres"},
        }
        record = jobs_core.jobtech_detail(payload, "123456")

        self.assertEqual(record["description"], "React/TypeScript\n\nPostgres")
        self.assertEqual(record["job_id"], "jobtech:jobsearch.api.jobtechdev.se:123456")


# Minimal per-angle cue lists for offline fetch-pipeline tests (issue #17).
TEST_ANGLES = {
    "full_stack_lead": {
        "title": ["tech lead", "full-stack", "fullstack", "full stack"],
        "body": ["architecture", "mentor", "ci/cd"],
    },
    "product_engineer": {
        "title": ["product engineer", "growth engineer"],
        "body": ["conversion", "experimentation", "funnel"],
    },
    "backend_principal": {
        "title": ["backend", "staff engineer", "principal"],
        "body": ["node", "graphql", "typescript", "distributed", "event-driven"],
    },
    "mobile_product": {
        "title": ["react native", "expo"],
        "body": ["react native", "expo", "mobile"],
    },
    "ai_native": {
        "title": ["ai engineer", "ai-native", "llm"],
        "body": ["llm", "agentic", "mcp", "machine learning"],
    },
}


class FetchRunSeamTests(unittest.TestCase):
    def _payload(self):
        return json.loads((FIXTURES / "jobtech-search.json").read_text(encoding="utf-8"))

    def test_fixture_payload_drives_a_full_run_offline(self):
        payload = self._payload()
        policy = jobs_fetch.load_yaml(jobs_fetch.PREFS)
        config = {
            "searches": [{"source": "jobtech", "q": "backend engineer", "limit": 50}],
            "boards": [],
            "angles": TEST_ANGLES,
        }
        requested = []

        def get(url):
            requested.append(url)
            return payload

        with tempfile.TemporaryDirectory() as directory:
            result = fetch_core.run(
                config, policy, get=get, repo_root=directory, today="2026-07-17"
            )
            markdown = pathlib.Path(result.markdown_path).read_text(encoding="utf-8")
            records = [
                json.loads(line)
                for line in pathlib.Path(result.jsonl_path).read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(
            requested, ["https://jobsearch.api.jobtechdev.se/search?q=backend+engineer&limit=50"]
        )
        self.assertEqual(result.scanned, 2)
        self.assertEqual(result.errors, [])
        self.assertEqual(
            [job["job_id"] for job in result.kept],
            ["jobtech:jobsearch.api.jobtechdev.se:29000001"],
        )
        self.assertEqual([job["drop_reason"] for job in result.dropped], ["onsite in US"])
        self.assertIn("# Job shortlist — 2026-07-17", markdown)
        self.assertIn("Senior Backend Engineer (Node) — Nordic Charge AB", markdown)
        self.assertIn("job-id: jobtech:jobsearch.api.jobtechdev.se:29000001", markdown)
        self.assertIn("found-by: backend engineer", markdown)
        self.assertIn("--from-report reports/jobs-2026-07-17.jsonl", markdown)
        self.assertIn(
            "- Staff Engineer — Platform — US Platform Inc (New York, United States): onsite in US",
            markdown,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["job_id"], "jobtech:jobsearch.api.jobtechdev.se:29000001")
        self.assertEqual(records[0]["source_queries"], ["backend engineer"])
        self.assertIn("Node.js and GraphQL services", records[0]["description"])

    def test_transport_error_is_reported_without_aborting_the_run(self):
        policy = jobs_fetch.load_yaml(jobs_fetch.PREFS)
        config = {
            "searches": [{"source": "jobtech", "q": "backend engineer", "limit": 50}],
            "boards": [],
            "angles": TEST_ANGLES,
        }

        def get(url):
            raise ValueError("recorded transport failure")

        with tempfile.TemporaryDirectory() as directory:
            result = fetch_core.run(
                config, policy, get=get, repo_root=directory, today="2026-07-17"
            )
            markdown = pathlib.Path(result.markdown_path).read_text(encoding="utf-8")

        self.assertEqual(result.kept, [])
        self.assertEqual(
            result.errors, ["search jobtech q='backend engineer': recorded transport failure"]
        )
        self.assertIn("### Fetch errors", markdown)
        self.assertIn("recorded transport failure", markdown)

    def test_cli_main_writes_the_same_reports_through_the_seam(self):
        payload = self._payload()
        today = datetime.date.today().isoformat()
        policy = jobs_fetch.load_yaml(jobs_fetch.PREFS)
        config = {
            "searches": [{"source": "jobtech", "q": "backend engineer", "limit": 50}],
            "boards": [],
            "angles": TEST_ANGLES,
        }

        def load_yaml(path):
            if path == jobs_fetch.CFG:
                return config
            if path == jobs_fetch.PREFS:
                return policy
            raise AssertionError(f"unexpected yaml path: {path}")

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(jobs_fetch, "ROOT", directory),
                mock.patch.object(jobs_fetch, "load_yaml", side_effect=load_yaml),
                mock.patch.object(jobs_fetch, "get", side_effect=lambda url: payload),
                mock.patch("sys.argv", ["jobs_fetch.py"]),
                contextlib.redirect_stdout(output),
            ):
                jobs_fetch.main()
            reports = pathlib.Path(directory) / "reports"
            markdown = (reports / f"jobs-{today}.md").read_text(encoding="utf-8")
            records = [
                json.loads(line)
                for line in (reports / f"jobs-{today}.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

        self.assertIn("(1 kept, 1 dropped, 2 scanned, 0 errors)", output.getvalue())
        self.assertIn("[", output.getvalue())
        self.assertIn("Senior Backend Engineer (Node) — Nordic Charge AB", markdown)
        self.assertEqual(records[0]["job_id"], "jobtech:jobsearch.api.jobtechdev.se:29000001")


class AngleFitScoringTests(unittest.TestCase):
    """Primary-angle + fit scoring with weak-floor admission (issue #17)."""

    RETRIEVED_AT = "2026-07-17T06:00:00+00:00"

    def _policy(self):
        return jobs_fetch.load_yaml(jobs_fetch.PREFS)

    def _run(self, directory, payload, *, today="2026-07-17", query="backend engineer"):
        config = {
            "searches": [{"source": "jobtech", "q": query, "limit": 50}],
            "boards": [],
            "angles": TEST_ANGLES,
        }
        return fetch_core.run(
            config,
            self._policy(),
            get=lambda url: payload,
            repo_root=directory,
            today=today,
            retrieved_at=self.RETRIEVED_AT,
        )

    def _hit(
        self,
        ad_id,
        *,
        headline,
        company="Example AB",
        city="Stockholm",
        country="Sverige",
        description,
    ):
        return {
            "id": ad_id,
            "headline": headline,
            "employer": {"workplace": company, "name": company},
            "workplace_address": {"city": city, "country": country},
            "application_details": {"url": f"https://jobs.example.test/{ad_id}"},
            "webpage_url": f"https://arbetsformedlingen.se/platsbanken/annonser/{ad_id}",
            "employment_type": {"label": "Vanlig anställning"},
            "duration": {"label": "Tills vidare"},
            "publication_date": "2026-07-15T08:00:00",
            "description": {"text": description},
        }

    def test_weak_floor_drops_postings_with_no_qualifying_angle(self):
        payload = {
            "total": {"value": 2},
            "hits": [
                self._hit(
                    "410001",
                    headline="Senior Backend Engineer",
                    description="Node.js and GraphQL services. Permanent role in Stockholm, Sweden.",
                ),
                self._hit(
                    "410002",
                    headline="Warehouse Associate",
                    description="Pick and pack orders in our Stockholm warehouse. Permanent.",
                ),
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, payload)
            records = catalog_core.load_records(directory)

        self.assertEqual(
            [job["job_id"] for job in result.kept],
            ["jobtech:jobsearch.api.jobtechdev.se:410001"],
        )
        self.assertEqual(
            [job["job_id"] for job in result.dropped],
            ["jobtech:jobsearch.api.jobtechdev.se:410002"],
        )
        self.assertEqual(result.dropped[0]["drop_reason"], "no qualifying angle")
        self.assertEqual(
            [record["job_id"] for record in records], ["jobtech:jobsearch.api.jobtechdev.se:410001"]
        )
        self.assertNotIn("410002", " ".join(record["job_id"] for record in records))

    def test_admitted_job_gets_primary_angle_fit_score_breakdown_and_cues(self):
        payload = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "410010",
                    headline="Senior Backend Engineer (Node)",
                    description=(
                        "Build Node.js and GraphQL services with TypeScript. "
                        "Permanent hybrid role in Stockholm, Sweden."
                    ),
                )
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, payload)
            record = catalog_core.load_records(directory)[0]
            markdown = pathlib.Path(result.markdown_path).read_text(encoding="utf-8")
            report = json.loads(pathlib.Path(result.jsonl_path).read_text(encoding="utf-8"))

        job = result.kept[0]
        self.assertEqual(job["angle"], "backend_principal")
        self.assertEqual(job["fit_score"], 4)
        self.assertEqual(job["fit_breakdown"], {"angle": 3, "seniority": 1, "rn": 0})
        self.assertEqual(sorted(job["hits"]), ["backend", "graphql", "node", "typescript"])
        # Attribute preference score only — never summed with fit. Recency lives
        # inside attrs (posted → first_seen fallback against the fetch clock).
        self.assertEqual(
            job["score"],
            jobs_core.pref_score(
                job["attrs"],
                self._policy()["weights"],
                self._policy()["pay"],
                posted=job.get("posted", ""),
                first_seen=self.RETRIEVED_AT,
                now=self.RETRIEVED_AT,
            ),
        )
        self.assertEqual(record["angle"], "backend_principal")
        self.assertEqual(record["fit_score"], 4)
        self.assertEqual(record["fit_breakdown"], {"angle": 3, "seniority": 1, "rn": 0})
        self.assertIn("angle: backend_principal", markdown)
        self.assertIn("fit: 4", markdown)
        self.assertIn("angle:3 / seniority:1 / rn:0", markdown)
        self.assertIn("matched: backend, graphql, node, typescript", markdown)
        self.assertEqual(report["angle"], "backend_principal")
        self.assertEqual(report["fit_score"], 4)
        self.assertEqual(report["score"], job["score"])

    def test_ranking_is_lexicographic_fit_then_attributes(self):
        # High-fit hybrid Stockholm vs lower-fit fully-remote Sweden: fit wins.
        payload = {
            "total": {"value": 2},
            "hits": [
                self._hit(
                    "410020",
                    headline="Backend Engineer",
                    description=("Node services. Fully remote within Sweden. Permanent."),
                ),
                self._hit(
                    "410021",
                    headline="Staff Backend Engineer",
                    description=(
                        "Node.js and GraphQL with TypeScript. Hybrid, 2 days in office. "
                        "Permanent role in Stockholm, Sweden."
                    ),
                ),
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, payload)
            markdown = pathlib.Path(result.markdown_path).read_text(encoding="utf-8")

        kept_ids = [job["job_id"] for job in result.kept]
        self.assertEqual(
            kept_ids,
            [
                "jobtech:jobsearch.api.jobtechdev.se:410021",
                "jobtech:jobsearch.api.jobtechdev.se:410020",
            ],
        )
        self.assertGreater(result.kept[0]["fit_score"], result.kept[1]["fit_score"])
        self.assertLess(result.kept[0]["score"], result.kept[1]["score"])
        # Shortlist order matches fit-first ranking.
        first_pos = markdown.index("Staff Backend Engineer")
        second_pos = markdown.index("Backend Engineer — Example AB")
        self.assertLess(first_pos, second_pos)

    def test_fractional_fit_ranks_and_renders_at_report_layer(self):
        # A half-point RN secondary cue must survive fetch->report end to end: it
        # drives the shortlist header and fit-first order even against a higher
        # attribute score. Truncating 2.5 to 2 would silently flip both.
        payload = {
            "total": {"value": 2},
            "hits": [
                self._hit(
                    "410040",
                    headline="Backend Engineer",
                    description=(
                        "Node services with React Native on the side. Hybrid, 2 days "
                        "in office. Permanent role in Stockholm, Sweden."
                    ),
                ),
                self._hit(
                    "410041",
                    headline="Backend Developer",
                    description="Node services. Fully remote within Sweden. Permanent.",
                ),
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, payload)
            markdown = pathlib.Path(result.markdown_path).read_text(encoding="utf-8")

        half = next(job for job in result.kept if job["job_id"].endswith("410040"))
        whole = next(job for job in result.kept if job["job_id"].endswith("410041"))
        self.assertEqual(half["fit_score"], 2.5)
        self.assertEqual(half["fit_breakdown"]["rn"], 0.5)
        self.assertEqual(whole["fit_score"], 2)
        # The fractional job has the LOWER attribute score, so only an intact
        # half-point can rank it first — truncation to 2 would let attrs win.
        self.assertLess(half["score"], whole["score"])

        # Report header keeps the fraction; the whole-number job stays "[fit 2]".
        self.assertIn("[fit 2.5] Backend Engineer", markdown)
        self.assertIn("[fit 2] Backend Developer", markdown)
        self.assertIn("fit: 2.5", markdown)
        self.assertIn("rn:0.5", markdown)
        # Fit-first ordering in the rendered shortlist: 2.5 outranks 2.0.
        self.assertLess(markdown.index("Backend Engineer"), markdown.index("Backend Developer"))

    def test_rn_title_tie_prefers_mobile_product_over_full_stack_lead(self):
        # Equal cue weight on mobile_product and full_stack_lead; RN title wins the tie.
        payload = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "410030",
                    headline="React Native Tech Lead",
                    description="Remote within Sweden. Permanent role.",
                )
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, payload)

        job = result.kept[0]
        self.assertEqual(job["angle"], "mobile_product")
        self.assertEqual(job["fit_breakdown"]["rn"], 1)
        self.assertIn("react native", job["hits"])

    def test_rn_secondary_cue_on_another_primary_is_half_weight(self):
        payload = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "410031",
                    headline="Senior Backend Engineer",
                    description=(
                        "Node.js and GraphQL with TypeScript. Also shipping a React Native "
                        "companion app. Permanent in Stockholm, Sweden."
                    ),
                )
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, payload)

        job = result.kept[0]
        self.assertEqual(job["angle"], "backend_principal")
        self.assertEqual(job["fit_breakdown"]["rn"], 0.5)
        self.assertEqual(job["fit_score"], 4.5)
        self.assertIn("react native", job["hits"])

    def test_catalog_upsert_recomputes_angle_and_fit_from_latest_text(self):
        first = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "410040",
                    headline="Backend Engineer",
                    description="Node.js services. Permanent in Stockholm, Sweden.",
                )
            ],
        }
        second = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "410040",
                    headline="Staff Backend Engineer",
                    description=(
                        "Node.js and GraphQL with TypeScript. Permanent in Stockholm, Sweden."
                    ),
                )
            ],
        }
        job_id = "jobtech:jobsearch.api.jobtechdev.se:410040"
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, first, today="2026-07-16")
            before = catalog_core.load_record(directory, job_id)
            fetch_core.run(
                {
                    "searches": [{"source": "jobtech", "q": "backend engineer", "limit": 50}],
                    "boards": [],
                    "angles": TEST_ANGLES,
                },
                self._policy(),
                get=lambda url: second,
                repo_root=directory,
                today="2026-07-17",
                retrieved_at="2026-07-18T06:00:00+00:00",
            )
            after = catalog_core.load_record(directory, job_id)

        self.assertEqual(before["angle"], "backend_principal")
        self.assertEqual(before["fit_score"], 2)
        self.assertEqual(after["title"], "Staff Backend Engineer")
        self.assertEqual(after["fit_score"], 4)
        self.assertEqual(after["fit_breakdown"], {"angle": 3, "seniority": 1, "rn": 0})
        self.assertEqual(sorted(after["hits"]), ["backend", "graphql", "node", "typescript"])

    def test_scaffold_prefills_angle_and_fit_with_attribute_discovery_score(self):
        payload = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "410050",
                    headline="Senior Backend Engineer",
                    description=(
                        "Node.js and GraphQL with TypeScript. "
                        "Permanent hybrid role in Stockholm, Sweden."
                    ),
                )
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, payload)
            jobs = new_application.load_report(result.jsonl_path)
            job = jobs[0]
            folder = pathlib.Path(directory) / "applications" / "Example"
            folder.mkdir(parents=True)
            (folder / "meta.yaml").write_text(
                "company: Example AB\nrole: Senior Backend Engineer\n"
                'angle: ""\nfit_score: 0\ndiscovery_score: 0\nstatus: draft\n',
                encoding="utf-8",
            )
            (folder / "job.md").write_text(
                f"# Example AB — Senior Backend Engineer\n\n{new_application.JOB_PLACEHOLDER}\n",
                encoding="utf-8",
            )
            new_application.scaffold_from_report(
                str(folder), job["company"], job["title"], result.jsonl_path, job
            )
            metadata = (folder / "meta.yaml").read_text(encoding="utf-8")

        self.assertIn('angle: "backend_principal"', metadata)
        self.assertIn("fit_score: 4", metadata)
        self.assertIn(f"discovery_score: {job['score']}", metadata)
        self.assertNotEqual(job["score"], job["fit_score"])


class CatalogSpineTests(unittest.TestCase):
    """Fetches merge into the persistent catalog under data/jobs (issue #16)."""

    FIRST_FETCH = "2026-07-16T06:00:00+00:00"
    SECOND_FETCH = "2026-07-17T06:00:00+00:00"

    def _payload(self):
        return json.loads((FIXTURES / "jobtech-search.json").read_text(encoding="utf-8"))

    def _config(self, query="backend engineer"):
        return {
            "searches": [{"source": "jobtech", "q": query, "limit": 50}],
            "boards": [],
            "angles": TEST_ANGLES,
        }

    def _run(self, directory, payload, retrieved_at, query="backend engineer", today="2026-07-17"):
        policy = jobs_fetch.load_yaml(jobs_fetch.PREFS)
        return fetch_core.run(
            self._config(query),
            policy,
            get=lambda url: payload,
            repo_root=directory,
            today=today,
            retrieved_at=retrieved_at,
        )

    def _read_index(self, directory):
        index_path = pathlib.Path(directory) / "data" / "jobs" / "index.json"
        return json.loads(index_path.read_text(encoding="utf-8"))

    def test_fetch_admits_jobs_into_catalog_and_hard_drops_stay_out(self):
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, self._payload(), self.FIRST_FETCH)
            records = catalog_core.load_records(directory)
            index = self._read_index(directory)

        admitted = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        dropped = "jobtech:jobsearch.api.jobtechdev.se:29000002"
        self.assertEqual([record["job_id"] for record in records], [admitted])
        record = records[0]
        self.assertEqual(record["schema_version"], catalog_core.SCHEMA_VERSION)
        self.assertEqual(record["triage"], "open")
        self.assertEqual(record["first_seen"], self.FIRST_FETCH)
        self.assertEqual(record["last_seen"], self.FIRST_FETCH)
        self.assertEqual(record["source_queries"], ["backend engineer"])
        self.assertIn("Node.js and GraphQL services", record["description"])
        self.assertIn(admitted, index["jobs"])
        self.assertNotIn(dropped, index["jobs"])

    def test_refetch_is_idempotent_and_unions_source_queries(self):
        admitted = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        truncated = self._payload()
        truncated["hits"][0]["description"]["text"] = "Node.js and GraphQL. Stockholm, Sweden."
        truncated["hits"][0]["headline"] = "Senior Backend Engineer (Node.js)"
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, self._payload(), self.FIRST_FETCH)
            first = catalog_core.load_record(directory, admitted)
            self._run(directory, truncated, self.SECOND_FETCH, query="node graphql")
            second = catalog_core.load_record(directory, admitted)

        self.assertEqual(first["first_seen"], self.FIRST_FETCH)
        self.assertEqual(second["first_seen"], self.FIRST_FETCH)
        self.assertEqual(second["last_seen"], self.SECOND_FETCH)
        self.assertEqual(second["source_queries"], ["backend engineer", "node graphql"])
        # Newer non-empty description wins even when shorter; identity fields refresh.
        self.assertEqual(second["description"], "Node.js and GraphQL. Stockholm, Sweden.")
        self.assertEqual(second["title"], "Senior Backend Engineer (Node.js)")
        self.assertEqual(second["triage"], "open")

    def test_triage_decisions_survive_a_refetch(self):
        admitted = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, self._payload(), self.FIRST_FETCH)
            catalog_core.set_triage(directory, admitted, "skipped", skip_reason="onsite too far")
            self._run(directory, self._payload(), self.SECOND_FETCH)
            record = catalog_core.load_record(directory, admitted)
            index = self._read_index(directory)

        self.assertEqual(record["triage"], "skipped")
        self.assertEqual(record["skip_reason"], "onsite too far")
        self.assertEqual(record["last_seen"], self.SECOND_FETCH)
        self.assertEqual(index["jobs"][admitted]["triage"], "skipped")

    def test_set_triage_validates_state_and_skip_reason(self):
        admitted = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, self._payload(), self.FIRST_FETCH)
            with self.assertRaises(ValueError):
                catalog_core.set_triage(directory, admitted, "skipped")
            with self.assertRaises(ValueError):
                catalog_core.set_triage(directory, admitted, "shortlisted")
            with self.assertRaises(ValueError):
                catalog_core.set_triage(directory, "unknown:id", "interested")
            catalog_core.set_triage(directory, admitted, "interested")
            record = catalog_core.load_record(directory, admitted)

        self.assertEqual(record["triage"], "interested")

    def _second_payload(self):
        return {
            "total": {"value": 1},
            "hits": [
                {
                    "id": "29000003",
                    "headline": "Fullstack TypeScript Engineer",
                    "employer": {"workplace": "Fjord Labs AB", "name": "Fjord Labs AB"},
                    "workplace_address": {"city": "Stockholm", "country": "Sverige"},
                    "application_details": {"url": "https://jobs.fjordlabs.example/fullstack"},
                    "webpage_url": "https://arbetsformedlingen.se/platsbanken/annonser/29000003",
                    "employment_type": {"label": "Vanlig anställning"},
                    "duration": {"label": "Tills vidare"},
                    "publication_date": "2026-07-16T08:00:00",
                    "description": {
                        "text": "TypeScript and Node backend. Permanent, Stockholm, Sweden."
                    },
                }
            ],
        }

    def test_markdown_shortlist_is_a_view_over_the_catalog(self):
        first_id = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, self._payload(), self.FIRST_FETCH, today="2026-07-16")
            catalog_core.set_triage(directory, first_id, "interested")
            result = self._run(
                directory, self._second_payload(), self.SECOND_FETCH, query="typescript developer"
            )
            markdown = pathlib.Path(result.markdown_path).read_text(encoding="utf-8")

        # The job admitted yesterday is absent from today's payload but still listed.
        self.assertIn("Senior Backend Engineer (Node) — Nordic Charge AB", markdown)
        self.assertIn("Fullstack TypeScript Engineer — Fjord Labs AB", markdown)
        self.assertIn("triage: interested", markdown)

    def test_skipped_jobs_are_excluded_from_the_shortlist_view(self):
        first_id = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, self._payload(), self.FIRST_FETCH, today="2026-07-16")
            catalog_core.set_triage(directory, first_id, "skipped", skip_reason="not my stack")
            result = self._run(
                directory, self._second_payload(), self.SECOND_FETCH, query="typescript developer"
            )
            markdown = pathlib.Path(result.markdown_path).read_text(encoding="utf-8")

        self.assertNotIn("Nordic Charge AB", markdown)
        self.assertIn("Fullstack TypeScript Engineer — Fjord Labs AB", markdown)

    def test_report_jsonl_view_still_supports_scaffolding(self):
        first_id = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, self._payload(), self.FIRST_FETCH, today="2026-07-16")
            result = self._run(
                directory, self._second_payload(), self.SECOND_FETCH, query="typescript developer"
            )
            jobs = new_application.load_report(result.jsonl_path)
            job = new_application.select_report_job(jobs, job_id=first_id)

        # Yesterday's admission scaffolds from today's report view.
        self.assertEqual(job["company"], "Nordic Charge AB")
        self.assertIn("Node.js and GraphQL services", job["description"])
        self.assertEqual(job["source_queries"], ["backend engineer"])
        imported = new_application.imported_job_markdown(
            job["company"], job["title"], result.jsonl_path, job
        )
        self.assertIn(f"<!-- job-id: {first_id} -->", imported)


class MetadataPipelineTests(unittest.TestCase):
    """Fetch watermark, New/Updated/Stale labels, posted/deadline (issue #18)."""

    FIRST_FETCH = "2026-07-16T06:00:00+00:00"
    SECOND_FETCH = "2026-07-17T06:00:00+00:00"
    STALE_FETCH = "2026-06-01T06:00:00+00:00"

    def _policy(self):
        return jobs_fetch.load_yaml(jobs_fetch.PREFS)

    def _config(self, query="backend engineer"):
        return {
            "searches": [{"source": "jobtech", "q": query, "limit": 50}],
            "boards": [],
            "angles": TEST_ANGLES,
        }

    def _hit(
        self,
        ad_id,
        *,
        headline,
        company="Example AB",
        description,
        publication_date="2026-07-15T08:00:00",
        application_deadline="",
    ):
        hit = {
            "id": ad_id,
            "headline": headline,
            "employer": {"workplace": company, "name": company},
            "workplace_address": {"city": "Stockholm", "country": "Sverige"},
            "application_details": {"url": f"https://jobs.example.test/{ad_id}"},
            "webpage_url": f"https://arbetsformedlingen.se/platsbanken/annonser/{ad_id}",
            "employment_type": {"label": "Vanlig anställning"},
            "duration": {"label": "Tills vidare"},
            "publication_date": publication_date,
            "description": {"text": description},
        }
        if application_deadline:
            hit["application_deadline"] = application_deadline
        return hit

    def _run(
        self, directory, payload, retrieved_at, *, today="2026-07-17", query="backend engineer"
    ):
        return fetch_core.run(
            self._config(query),
            self._policy(),
            get=lambda url: payload,
            repo_root=directory,
            today=today,
            retrieved_at=retrieved_at,
        )

    def test_fetch_persists_watermark_after_successful_run(self):
        payload = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "510001",
                    headline="Senior Backend Engineer",
                    description="Node.js and GraphQL. Permanent role in Stockholm, Sweden.",
                )
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, payload, self.FIRST_FETCH)
            watermark_path = pathlib.Path(directory) / "data" / "jobs" / "last_fetch_at"
            self.assertTrue(watermark_path.is_file())
            self.assertEqual(watermark_path.read_text(encoding="utf-8"), self.FIRST_FETCH)
            self._run(directory, payload, self.SECOND_FETCH)
            self.assertEqual(watermark_path.read_text(encoding="utf-8"), self.SECOND_FETCH)

    def test_shortlist_marks_new_and_updated_relative_to_watermark(self):
        first = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "510010",
                    headline="Senior Backend Engineer",
                    company="Nordic Charge AB",
                    description="Node.js and GraphQL. Permanent role in Stockholm, Sweden.",
                )
            ],
        }
        second = {
            "total": {"value": 2},
            "hits": [
                self._hit(
                    "510010",
                    headline="Senior Backend Engineer",
                    company="Nordic Charge AB",
                    description="Node.js and GraphQL. Permanent role in Stockholm, Sweden.",
                ),
                self._hit(
                    "510011",
                    headline="Staff Backend Engineer",
                    company="Fjord Labs AB",
                    description="Node.js and TypeScript. Permanent role in Stockholm, Sweden.",
                ),
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, first, self.FIRST_FETCH, today="2026-07-16")
            result = self._run(directory, second, self.SECOND_FETCH, today="2026-07-17")
            markdown = pathlib.Path(result.markdown_path).read_text(encoding="utf-8")

        # New insert this fetch.
        self.assertRegex(
            markdown,
            r"## \[fit \d+\] Staff Backend Engineer — Fjord Labs AB\nlabel: New\n",
        )
        # Seen again; first_seen is older than this fetch's watermark.
        self.assertRegex(
            markdown,
            r"## \[fit \d+\] Senior Backend Engineer — Nordic Charge AB\nlabel: Updated\n",
        )

    def test_stale_jobs_are_hidden_from_shortlist_but_kept_in_catalog(self):
        stale_payload = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "510020",
                    headline="Senior Backend Engineer",
                    company="Old Co AB",
                    description="Node.js and GraphQL. Permanent role in Stockholm, Sweden.",
                )
            ],
        }
        fresh_payload = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "510021",
                    headline="Staff Backend Engineer",
                    company="Fresh Co AB",
                    description="Node.js and TypeScript. Permanent role in Stockholm, Sweden.",
                )
            ],
        }
        stale_id = "jobtech:jobsearch.api.jobtechdev.se:510020"
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, stale_payload, self.STALE_FETCH, today="2026-06-01")
            result = self._run(directory, fresh_payload, self.SECOND_FETCH, today="2026-07-17")
            markdown = pathlib.Path(result.markdown_path).read_text(encoding="utf-8")
            records = catalog_core.load_records(directory)

        self.assertIn(stale_id, [record["job_id"] for record in records])
        self.assertNotIn("Old Co AB", markdown)
        self.assertIn("Fresh Co AB", markdown)

    def test_posted_keeps_first_non_empty_and_prefers_earlier_when_both_parse(self):
        first = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "510030",
                    headline="Senior Backend Engineer",
                    description="Node.js and GraphQL. Permanent role in Stockholm, Sweden.",
                    publication_date="2026-07-10T08:00:00",
                )
            ],
        }
        second = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "510030",
                    headline="Senior Backend Engineer",
                    description="Node.js and GraphQL. Permanent role in Stockholm, Sweden.",
                    publication_date="2026-07-12T08:00:00",
                )
            ],
        }
        third = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "510030",
                    headline="Senior Backend Engineer",
                    description="Node.js and GraphQL. Permanent role in Stockholm, Sweden.",
                    publication_date="2026-07-08T08:00:00",
                )
            ],
        }
        job_id = "jobtech:jobsearch.api.jobtechdev.se:510030"
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, first, self.FIRST_FETCH)
            after_first = catalog_core.load_record(directory, job_id)
            self._run(directory, second, self.SECOND_FETCH)
            after_later = catalog_core.load_record(directory, job_id)
            self._run(directory, third, "2026-07-18T06:00:00+00:00")
            after_earlier = catalog_core.load_record(directory, job_id)

        self.assertEqual(after_first["posted"], "2026-07-10T08:00:00")
        # Later non-empty must not clobber the first posted date.
        self.assertEqual(after_later["posted"], "2026-07-10T08:00:00")
        # When both parse, keep the earlier calendar date.
        self.assertEqual(after_earlier["posted"], "2026-07-08T08:00:00")

    def test_deadline_comes_from_structured_field_and_appears_in_shortlist(self):
        payload = {
            "total": {"value": 1},
            "hits": [
                self._hit(
                    "510040",
                    headline="Senior Backend Engineer",
                    company="Deadline Co AB",
                    description="Node.js and GraphQL. Permanent role in Stockholm, Sweden.",
                    publication_date="2026-07-15T08:00:00",
                    application_deadline="2026-07-25T23:59:59",
                )
            ],
        }
        job_id = "jobtech:jobsearch.api.jobtechdev.se:510040"
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, payload, self.SECOND_FETCH)
            record = catalog_core.load_record(directory, job_id)
            markdown = pathlib.Path(result.markdown_path).read_text(encoding="utf-8")

        self.assertEqual(record["deadline"], "2026-07-25T23:59:59")
        self.assertEqual(record["posted"], "2026-07-15T08:00:00")
        self.assertIn("posted: 2026-07-15T08:00:00", markdown)
        self.assertIn("deadline: 2026-07-25T23:59:59", markdown)
        self.assertIn("label: New", markdown)

    def test_recency_bonus_lives_inside_attribute_score_only(self):
        recent = self._hit(
            "510050",
            headline="Senior Backend Engineer",
            company="Recent Co AB",
            description="Node.js and GraphQL. Permanent remote role in Stockholm, Sweden.",
            publication_date="2026-07-16T08:00:00",
        )
        older = self._hit(
            "510051",
            headline="Senior Backend Engineer",
            company="Older Co AB",
            description="Node.js and GraphQL. Permanent remote role in Stockholm, Sweden.",
            publication_date="2026-06-01T08:00:00",
        )
        payload = {"total": {"value": 2}, "hits": [older, recent]}
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, payload, self.SECOND_FETCH)
            records = {record["job_id"]: record for record in catalog_core.load_records(directory)}

        recent_id = "jobtech:jobsearch.api.jobtechdev.se:510050"
        older_id = "jobtech:jobsearch.api.jobtechdev.se:510051"
        # Same angle/fit; recency only moves the attribute score (+2 within 7d vs 0).
        self.assertEqual(records[recent_id]["fit_score"], records[older_id]["fit_score"])
        self.assertEqual(records[recent_id]["score"], records[older_id]["score"] + 2)
        self.assertEqual(
            [job["job_id"] for job in result.kept],
            [recent_id, older_id],
        )


class RemotiveDiscoveryTests(unittest.TestCase):
    """Remotive category pulls through the fetch seam (issue #19)."""

    RETRIEVED_AT = "2026-07-17T06:00:00+00:00"

    def _payload(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_remotive_fixture_payload_drives_catalog_and_shortlist(self):
        software = self._payload("remotive-software-dev.json")
        ai = self._payload("remotive-artificial-intelligence.json")
        policy = jobs_fetch.load_yaml(jobs_fetch.PREFS)
        config = {
            "searches": [
                {"source": "remotive", "category": "software-dev"},
                {"source": "remotive", "category": "artificial-intelligence"},
            ],
            "boards": [],
            "angles": TEST_ANGLES,
        }
        requested = []

        def get(url):
            requested.append(url)
            if "category=software-dev" in url:
                return software
            if "category=artificial-intelligence" in url:
                return ai
            raise AssertionError(f"unexpected Remotive URL: {url}")

        with tempfile.TemporaryDirectory() as directory:
            result = fetch_core.run(
                config,
                policy,
                get=get,
                repo_root=directory,
                today="2026-07-17",
                retrieved_at=self.RETRIEVED_AT,
            )
            markdown = pathlib.Path(result.markdown_path).read_text(encoding="utf-8")
            records = catalog_core.load_records(directory)
            report_rows = [
                json.loads(line)
                for line in pathlib.Path(result.jsonl_path).read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(
            requested,
            [
                "https://remotive.com/api/remote-jobs?category=software-dev",
                "https://remotive.com/api/remote-jobs?category=artificial-intelligence",
            ],
        )
        self.assertEqual(result.errors, [])
        # Two category payloads → four unique ids (one shared id merged).
        self.assertEqual(result.scanned, 4)
        self.assertEqual(
            [job["job_id"] for job in result.kept],
            [
                "remotive:remotive.com:880001",
                "remotive:remotive.com:880010",
            ],
        )
        self.assertEqual(
            [job["job_id"] for job in result.dropped],
            ["remotive:remotive.com:880002", "remotive:remotive.com:880003"],
        )
        self.assertEqual(
            {job["job_id"]: job["drop_reason"] for job in result.dropped},
            {
                "remotive:remotive.com:880002": "remote but US-bound",
                "remotive:remotive.com:880003": "no qualifying angle",
            },
        )

        backend = next(job for job in result.kept if job["source_id"] == "880001")
        self.assertEqual(backend["url"], software["jobs"][0]["url"])
        self.assertEqual(backend["listing_url"], software["jobs"][0]["url"])
        self.assertEqual(backend["apply_url"], "")
        self.assertEqual(backend["attrs"]["arrangement"], "remote")
        self.assertEqual(backend["attrs"]["employment"], "permanent")
        self.assertEqual(backend["attrs"]["pay"]["raw"], "€80,000 - €100,000 per year")
        self.assertEqual(backend["posted"], "2026-07-15T08:00:00")
        self.assertEqual(
            backend["source_queries"],
            ["artificial-intelligence", "software-dev"],
        )
        self.assertIn("Build Node.js and GraphQL services.", backend["desc"])
        self.assertNotIn("<p>", backend["desc"])
        # Tags feed scoring only — they must not appear in the stored body.
        self.assertNotIn("\ntypescript", backend["desc"])
        self.assertIn("typescript", backend["hits"])
        self.assertEqual(backend["tags"], ["graphql", "llm", "node", "typescript"])

        ai_job = next(job for job in result.kept if job["source_id"] == "880010")
        self.assertEqual(ai_job["attrs"]["employment"], "contract")
        self.assertEqual(ai_job["attrs"]["pay"]["raw"], "$90 - $150 /hour")
        self.assertEqual(ai_job["angle"], "ai_native")
        self.assertEqual(ai_job["source_queries"], ["artificial-intelligence"])

        self.assertEqual(
            [record["job_id"] for record in records],
            [
                "remotive:remotive.com:880001",
                "remotive:remotive.com:880010",
            ],
        )
        catalog_backend = records[0]
        self.assertEqual(
            catalog_backend["source_queries"],
            ["artificial-intelligence", "software-dev"],
        )
        self.assertEqual(catalog_backend["first_seen"], self.RETRIEVED_AT)
        self.assertIn("Build Node.js and GraphQL services.", catalog_backend["description"])
        self.assertNotIn("typescript graphql node", catalog_backend["description"])

        self.assertIn("Senior Backend Engineer — Nordic Remote Labs", markdown)
        self.assertIn("AI Engineer — Agentic EU", markdown)
        self.assertIn("job-id: remotive:remotive.com:880001", markdown)
        self.assertIn("found-by: artificial-intelligence, software-dev", markdown)
        self.assertIn("### Dropped — no qualifying angle", markdown)
        self.assertIn("Office Manager — Admin Co", markdown)
        self.assertIn(
            "- Staff Backend Engineer — US Only Remote Inc (USA Only): remote but US-bound",
            markdown,
        )
        self.assertEqual(
            [row["job_id"] for row in report_rows],
            [
                "remotive:remotive.com:880001",
                "remotive:remotive.com:880010",
            ],
        )


class MultiSourceDedupeTests(unittest.TestCase):
    """Cross-source clusters through the fetch seam (issue #23)."""

    RETRIEVED_AT = "2026-07-17T06:00:00+00:00"
    INGESTED_AT = "2026-07-17T12:00:00+00:00"
    APPLY_URL = "https://careers.nordiclabs.example/jobs/senior-backend"
    JOBTECH_ID = "jobtech:jobsearch.api.jobtechdev.se:77000001"
    REMOTIVE_ID = "remotive:remotive.com:990001"
    PASTE = (
        "Senior Backend Engineer at Nordic Labs — curated paste.\n\n"
        "We are hiring a senior backend engineer to own Node.js and GraphQL "
        "services with TypeScript. Permanent remote role across Europe.\n\n"
        "Responsibilities include architecture, mentoring, and shipping "
        "reliable APIs. Requirements: 5+ years experience, distributed systems.\n"
        "This manual-paste body is shorter than the JobTech listing on purpose.\n"
    )

    def _payload(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def _policy(self):
        return jobs_fetch.load_yaml(jobs_fetch.PREFS)

    def _fetch_cluster(self, directory):
        jobtech = self._payload("cluster-jobtech-search.json")
        remotive = self._payload("cluster-remotive-software-dev.json")
        config = {
            "searches": [
                {"source": "jobtech", "q": "backend engineer", "limit": 50},
                {"source": "remotive", "category": "software-dev"},
            ],
            "boards": [],
            "angles": TEST_ANGLES,
        }

        def get(url):
            if "jobsearch.api.jobtechdev.se/search" in url:
                return jobtech
            if "category=software-dev" in url:
                return remotive
            raise AssertionError(f"unexpected URL: {url}")

        return fetch_core.run(
            config,
            self._policy(),
            get=get,
            repo_root=directory,
            today="2026-07-17",
            retrieved_at=self.RETRIEVED_AT,
        )

    def test_jobtech_remotive_ingest_cluster_skip_and_manual_paste_display(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._fetch_cluster(directory)
            self.assertEqual(result.errors, [])
            records = {record["job_id"]: record for record in catalog_core.load_records(directory)}
            self.assertIn(self.JOBTECH_ID, records)
            self.assertIn(self.REMOTIVE_ID, records)
            cluster_id = records[self.JOBTECH_ID]["cluster_id"]
            self.assertTrue(cluster_id)
            self.assertEqual(records[self.REMOTIVE_ID]["cluster_id"], cluster_id)
            # Remotive board URL is preserved but clustering keys on the employer apply URL.
            self.assertTrue(records[self.REMOTIVE_ID]["url"].startswith("https://remotive.com/"))
            self.assertEqual(records[self.REMOTIVE_ID]["apply_url"], self.APPLY_URL)
            self.assertEqual(records[self.JOBTECH_ID]["apply_url"], self.APPLY_URL)

            # Ingest joins the cluster and adopts the mates' open triage (not its
            # default interested), without rewriting source-native fields.
            ingest_result = ingest_core.ingest(
                directory,
                self.PASTE,
                title="Senior Backend Engineer",
                company="Nordic Labs",
                location="Remote — Europe",
                url=self.APPLY_URL,
                policy=self._policy(),
                angles=TEST_ANGLES,
                ingested_at=self.INGESTED_AT,
            )
            ingest_id = ingest_result.record["job_id"]
            records = {record["job_id"]: record for record in catalog_core.load_records(directory)}
            self.assertEqual(records[ingest_id]["cluster_id"], cluster_id)
            self.assertEqual(records[ingest_id]["triage"], "open")
            self.assertEqual(records[self.JOBTECH_ID]["triage"], "open")
            self.assertEqual(records[self.REMOTIVE_ID]["triage"], "open")

            # Shortlist is one display-winner row: JobTech wins on description
            # length; the shown body is the shorter manual paste.
            result_after = self._fetch_cluster(directory)
            records = {record["job_id"]: record for record in catalog_core.load_records(directory)}
            report_rows = [
                json.loads(line)
                for line in pathlib.Path(result_after.jsonl_path)
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            markdown = pathlib.Path(result_after.markdown_path).read_text(encoding="utf-8")
            self.assertEqual([row["job_id"] for row in report_rows], [self.JOBTECH_ID])
            self.assertEqual(report_rows[0]["description"], self.PASTE)
            # When the view shows paste text, its provenance travels with it so the
            # row never labels paste content as another source (ADR-0003).
            self.assertEqual(report_rows[0]["description_source"], "manual-paste")
            self.assertEqual(
                report_rows[0]["fit_score"],
                records[self.JOBTECH_ID]["fit_score"],
            )
            self.assertEqual(
                max(record["fit_score"] for record in records.values()),
                catalog_core.rank_fit_score(
                    catalog_core.view_record_for_cluster(list(records.values()))
                ),
            )
            self.assertIn(f"job-id: {self.JOBTECH_ID}", markdown)
            self.assertNotIn(self.REMOTIVE_ID, markdown)
            self.assertNotIn(ingest_id, markdown)

            # Skip one mate → every current mate is skipped; shortlist drops them.
            catalog_core.set_triage(
                directory, self.REMOTIVE_ID, "skipped", skip_reason="comp too low"
            )
            for job_id in (self.JOBTECH_ID, self.REMOTIVE_ID, ingest_id):
                mate = catalog_core.load_record(directory, job_id)
                self.assertEqual(mate["triage"], "skipped")
                self.assertEqual(mate["skip_reason"], "comp too low")

            final = self._fetch_cluster(directory)
            final_rows = [
                json.loads(line)
                for line in pathlib.Path(final.jsonl_path).read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(final_rows, [])
            self.assertNotIn("Nordic Labs", pathlib.Path(final.markdown_path).read_text())

            # Source-native files stay unmerged aside from cluster_id + triage.
            jobtech = catalog_core.load_record(directory, self.JOBTECH_ID)
            remotive = catalog_core.load_record(directory, self.REMOTIVE_ID)
            pasted = catalog_core.load_record(directory, ingest_id)
            self.assertIn("JobTech listing body", jobtech["description"])
            self.assertEqual(jobtech["description_source"], "search")
            self.assertIn("Short Remotive blurb", remotive["description"])
            self.assertEqual(pasted["description"], self.PASTE)
            self.assertEqual(pasted["description_source"], "manual-paste")


class HnWhoIsHiringTests(unittest.TestCase):
    """HN Who's Hiring discovery through the fetch seam (issue #20)."""

    RETRIEVED_AT = "2026-07-17T06:00:00+00:00"
    PERMALINK = "https://news.ycombinator.com/item?id=48750001"
    APPLY_URL = "https://nordiclabs.example/careers/backend"

    def _payload(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def _transport(self, *, search=None, thread=None, requested=None):
        search = search if search is not None else self._payload("hn-search-who-is-hiring.json")
        thread = thread if thread is not None else self._payload("hn-thread-48747976.json")
        requested = requested if requested is not None else []

        def get(url):
            requested.append(url)
            if "search_by_date" in url and "whoishiring" in url:
                return search
            if url.endswith("/items/48747976"):
                return thread
            raise AssertionError(f"unexpected HN URL: {url}")

        return get, requested

    def test_hn_fixture_payload_drives_catalog_and_shortlist(self):
        policy = jobs_fetch.load_yaml(jobs_fetch.PREFS)
        config = {
            "searches": [{"source": "hn"}],
            "boards": [],
            "angles": TEST_ANGLES,
        }
        get, requested = self._transport()

        with tempfile.TemporaryDirectory() as directory:
            result = fetch_core.run(
                config,
                policy,
                get=get,
                repo_root=directory,
                today="2026-07-17",
                retrieved_at=self.RETRIEVED_AT,
            )
            markdown = pathlib.Path(result.markdown_path).read_text(encoding="utf-8")
            records = catalog_core.load_records(directory)
            # Re-walk is idempotent: same comment id upserts without duplicating.
            second = fetch_core.run(
                config,
                policy,
                get=self._transport()[0],
                repo_root=directory,
                today="2026-07-17",
                retrieved_at="2026-07-18T06:00:00+00:00",
            )
            records_after = catalog_core.load_records(directory)

        self.assertEqual(
            requested,
            [
                "https://hn.algolia.com/api/v1/search_by_date?tags=story%2Cauthor_whoishiring"
                "&query=Ask+HN%3A+Who+is+hiring&hitsPerPage=5",
                "https://hn.algolia.com/api/v1/items/48747976",
            ],
        )
        self.assertEqual(result.errors, [])
        self.assertEqual(result.parse_failures, 1)
        # Nested ignored; unparseable counted out; weak-floor still scanned.
        self.assertEqual(result.scanned, 3)
        self.assertEqual([job["job_id"] for job in result.kept], ["hn:48750001"])
        self.assertEqual(
            {(job["job_id"], job["drop_reason"]) for job in result.dropped},
            {
                ("hn:48750002", "remote but US-bound"),
                # "calendars, coffee" trips the legacy ", co" US location term.
                ("hn:48750004", "remote but US-bound"),
            },
        )

        backend = result.kept[0]
        self.assertEqual(backend["company"], "Nordic Labs")
        self.assertEqual(backend["title"], "Senior Backend Engineer")
        self.assertEqual(backend["url"], self.APPLY_URL)
        self.assertEqual(backend["apply_url"], self.APPLY_URL)
        self.assertEqual(backend["listing_url"], self.PERMALINK)
        self.assertEqual(backend["description_source"], "hn-comment")
        self.assertEqual(backend["posted"], "2026-07-01T16:00:00.000Z")
        self.assertEqual(backend["hn_thread_id"], "48747976")
        self.assertEqual(backend["source_id"], "48750001")
        self.assertEqual(backend["attrs"]["arrangement"], "remote")
        self.assertEqual(backend["angle"], "backend_principal")
        self.assertIn("Build Node.js and GraphQL services", backend["desc"])
        self.assertNotIn("<p>", backend["desc"])
        self.assertNotIn("Should never enter the catalog", backend["desc"])

        self.assertEqual([record["job_id"] for record in records], ["hn:48750001"])
        self.assertEqual(records[0]["description_source"], "hn-comment")
        self.assertEqual(records[0]["hn_thread_id"], "48747976")
        self.assertEqual(records[0]["url"], self.APPLY_URL)
        self.assertEqual(records[0]["listing_url"], self.PERMALINK)
        self.assertEqual(records[0]["first_seen"], self.RETRIEVED_AT)

        self.assertIn("Senior Backend Engineer — Nordic Labs", markdown)
        self.assertIn("job-id: hn:48750001", markdown)
        self.assertIn("hn parse failures: 1", markdown)
        self.assertIn(
            "- Staff Platform Engineer — Stateside Labs (USA Only): remote but US-bound",
            markdown,
        )
        self.assertIn("Office Coordinator", markdown)
        self.assertNotIn("Fake Role", markdown)
        self.assertNotIn("Just chiming in", markdown)

        self.assertEqual([record["job_id"] for record in records_after], ["hn:48750001"])
        self.assertEqual(records_after[0]["first_seen"], self.RETRIEVED_AT)
        self.assertEqual(records_after[0]["last_seen"], "2026-07-18T06:00:00+00:00")
        self.assertEqual(second.parse_failures, 1)

    def test_hn_thread_id_override_skips_search(self):
        policy = jobs_fetch.load_yaml(jobs_fetch.PREFS)
        config = {
            "searches": [{"source": "hn", "thread_id": "48747976"}],
            "boards": [],
            "angles": TEST_ANGLES,
        }
        requested = []
        thread = self._payload("hn-thread-48747976.json")

        def get(url):
            requested.append(url)
            if url.endswith("/items/48747976"):
                return thread
            raise AssertionError(f"search must not run when thread_id is set: {url}")

        with tempfile.TemporaryDirectory() as directory:
            result = fetch_core.run(
                config,
                policy,
                get=get,
                repo_root=directory,
                today="2026-07-17",
                retrieved_at=self.RETRIEVED_AT,
            )

        self.assertEqual(requested, ["https://hn.algolia.com/api/v1/items/48747976"])
        self.assertEqual([job["job_id"] for job in result.kept], ["hn:48750001"])
        self.assertEqual(result.parse_failures, 1)


class DraftProtectionTests(unittest.TestCase):
    def test_job_placeholder_ignores_import_comments(self):
        content = (
            "# Example Mobility — Senior Backend Engineer\n\n"
            "<!-- imported from report.jsonl -->\n"
            "<!-- job-id: example -->\n"
            f"{new_application.JOB_PLACEHOLDER}\n"
        )
        self.assertTrue(
            new_application.is_job_placeholder(
                content, "Example Mobility", "Senior Backend Engineer"
            )
        )
        self.assertFalse(
            new_application.is_job_placeholder(
                content.replace(new_application.JOB_PLACEHOLDER, "A real description."),
                "Example Mobility",
                "Senior Backend Engineer",
            )
        )

    def test_cv_placeholder_detection_allows_completed_fixture(self):
        stub = new_application.CV_STUB
        complete = (FIXTURES / "cv.md").read_text(encoding="utf-8")

        self.assertTrue(render_cv.find_placeholders(stub))
        self.assertEqual(render_cv.find_placeholders(complete), [])


class RenderingAndAtsTests(unittest.TestCase):
    def test_rendering_produces_one_page_html_for_fixture(self):
        text = (FIXTURES / "cv.md").read_text(encoding="utf-8")
        body = render_cv.md_to_body(text)
        self.assertIn('<p class="headline">Senior Backend Engineer & Technical Lead</p>', body)
        self.assertEqual(render_cv.page_count(render_cv.build_html(body, 1.0)), 1)

    def test_ats_cli_reports_coverage_and_verdict(self):
        job = (FIXTURES / "job.md").read_text(encoding="utf-8")
        cv = (FIXTURES / "cv.md").read_text(encoding="utf-8")
        uni, bi = ats_lint.phrases(job)
        sections = ats_lint.section_map(cv)

        self.assertIn("node.js", uni)
        self.assertIn("graphql services", bi)
        self.assertIn("SUMMARY", sections)
        self.assertIn("CORE SKILLS", sections)

        output = io.StringIO()
        args = ["ats_lint.py", str(FIXTURES / "job.md"), str(FIXTURES / "cv.md")]
        with mock.patch("sys.argv", args), contextlib.redirect_stdout(output):
            ats_lint.main()
        self.assertIn("=== ATS LINT ===", output.getvalue())
        self.assertIn("VERDICT:", output.getvalue())

    def test_package_ats_evaluation_and_rendering_seams(self):
        job = (FIXTURES / "job.md").read_text(encoding="utf-8")
        cv = (FIXTURES / "cv.md").read_text(encoding="utf-8")
        result = ats_core.evaluate(job, cv)
        self.assertIn("node.js", result.top_terms)
        self.assertIn("SUMMARY", ats_core.section_map(cv))
        self.assertIn("VERDICT:", ats_core.format_report(result))

        css = (pathlib.Path(__file__).parent.parent / "templates" / "cv.css").read_text(
            encoding="utf-8"
        )
        rendered = rendering_core.render_document(cv, css)
        self.assertTrue(rendered.fits_one_page)
        self.assertEqual(rendering_core.page_count(rendered.html), 1)


class DraftWorkflowTests(unittest.TestCase):
    STRONG_DRAFT = """# PIET GROOT KORMELINK
%%headline%% Senior Backend Engineer
%%contact%% piet@example.test · Stockholm

## SUMMARY
Backend engineer and technical lead building Node.js GraphQL services with PostgreSQL for reliable delivery and pragmatic system design. Improved systems by 20% and delivered 4 releases weekly. Permanent Stockholm candidate who values clear communication.

## CORE SKILLS
- **Backend:** Node.js, GraphQL, PostgreSQL, REST, services
- **Architecture:** system design, distributed systems, API design
- **Quality & Delivery:** reliable delivery, communication, TypeScript, CI/CD, testing, code review

## EXPERIENCE
### Example Mobility — Technical Lead · Stockholm · 2022–2026
- Delivered Node.js and GraphQL services backed by PostgreSQL for 100 customers.
- Improved release cadence from 1 release per month to 4 releases per week, reducing incidents 30%.
- Led 6 engineers and maintained 99% availability through testing and code review.

## EDUCATION
Computer Technology

## LANGUAGES
English
"""

    def _application(self) -> tuple[tempfile.TemporaryDirectory, pathlib.Path]:
        temporary = tempfile.TemporaryDirectory()
        folder = pathlib.Path(temporary.name) / "applications" / "ExampleMobility"
        folder.mkdir(parents=True)
        (folder / "job.md").write_text(
            (FIXTURES / "job.md").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (folder / "meta.yaml").write_text(
            "company: Example Mobility\nrole: Senior Backend Engineer\nstatus: draft\n",
            encoding="utf-8",
        )
        profile = folder.parent.parent / "profile" / "master-profile.yaml"
        profile.parent.mkdir()
        profile.write_text("name: Example\n", encoding="utf-8")
        return temporary, folder

    def test_start_is_idempotent_and_creates_context(self):
        temporary, folder = self._application()
        self.addCleanup(temporary.cleanup)
        paths = workflow_core.start(folder)
        self.assertTrue(paths.analysis.exists())
        self.assertTrue(paths.feedback.exists())
        self.assertTrue(paths.draft.exists())
        self.assertEqual(
            workflow_core._metadata_value(folder / "meta.yaml", "workflow_state"),
            "drafting",
        )
        workflow_core.start(folder)
        self.assertFalse((folder / "cv-draft.md.bak").exists())

    def test_start_refuses_to_overwrite_real_draft(self):
        temporary, folder = self._application()
        self.addCleanup(temporary.cleanup)
        workflow_core.start(folder)
        draft = folder / "cv-draft.md"
        draft.write_text("# A reviewed draft\n", encoding="utf-8")
        with self.assertRaises(workflow_core.WorkflowError):
            workflow_core.start(folder)
        self.assertEqual(draft.read_text(encoding="utf-8"), "# A reviewed draft\n")

    def test_check_writes_actionable_failure_review(self):
        temporary, folder = self._application()
        self.addCleanup(temporary.cleanup)
        workflow_core.start(folder)
        result = workflow_core.check(folder)
        self.assertFalse(result.passed)
        review = (folder / "cv-review.md").read_text(encoding="utf-8")
        self.assertIn("scaffold placeholders", review)
        self.assertIn("Action:", review)
        self.assertFalse((folder / "cv-draft.pdf").exists())

    def test_finalize_requires_approval_and_promotes_passing_draft(self):
        temporary, folder = self._application()
        self.addCleanup(temporary.cleanup)
        workflow_core.start(folder)
        (folder / "cv-analysis.md").write_text(
            "# CV analysis\n\nNode.js and GraphQL evidence reviewed.\n",
            encoding="utf-8",
        )
        (folder / "cv-draft.md").write_text(self.STRONG_DRAFT, encoding="utf-8")
        with self.assertRaises(workflow_core.WorkflowError):
            workflow_core.finalize(folder)

        result = workflow_core.finalize(folder, approve=True)
        self.assertTrue(result.passed)
        self.assertEqual((folder / "cv.md").read_text(encoding="utf-8"), self.STRONG_DRAFT)
        self.assertTrue((folder / "cv-draft.pdf").exists())
        self.assertTrue((folder / "cv.pdf").exists())
        self.assertEqual(
            workflow_core._metadata_value(folder / "meta.yaml", "workflow_state"),
            "finalized",
        )

    def test_create_and_approve_wrappers_follow_real_cli_flow(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = pathlib.Path(temporary.name)
        apps = root / "applications"
        profile = root / "profile" / "master-profile.yaml"
        profile.parent.mkdir(parents=True)
        profile.write_text("name: Example\n", encoding="utf-8")

        with mock.patch.object(new_application, "APPS", str(apps)):
            create_code = cv_workflow.main(
                [
                    "create",
                    "--from-report",
                    str(FIXTURES / "workflow-report.jsonl"),
                    "--job-id",
                    "jobtech:jobsearch.api.jobtechdev.se:999101",
                    "--date",
                    "2026-07-10",
                    "--profile",
                    str(profile),
                ]
            )
        self.assertEqual(create_code, 0)
        application = apps / "2026-07-10_ExampleMobility"
        (application / "cv-analysis.md").write_text(
            "# CV analysis\n\nEvidence reviewed against the job description.\n",
            encoding="utf-8",
        )
        (application / "cv-draft.md").write_text(self.STRONG_DRAFT, encoding="utf-8")

        approve_code = cv_workflow.main(["approve", str(application), "--profile", str(profile)])
        self.assertEqual(approve_code, 0)
        self.assertTrue((application / "cv.md").exists())
        self.assertTrue((application / "cv.pdf").exists())
        self.assertTrue((application / "cv-review.md").exists())


class ClipboardIngestTests(unittest.TestCase):
    """Clipboard ingest helper seam (issue #21)."""

    INGESTED_AT = "2026-07-17T12:00:00+00:00"
    POSTING = (
        "Senior Backend Engineer\n\n"
        "We are hiring a senior backend engineer to own Node.js and GraphQL "
        "services with TypeScript. Permanent remote role across Europe.\n\n"
        "Responsibilities include architecture, mentoring, and shipping "
        "reliable APIs. Requirements: 5+ years experience, distributed systems.\n"
    )

    def _policy(self):
        return jobs_fetch.load_yaml(jobs_fetch.PREFS)

    def test_sanity_check_hard_rejects_empty_short_and_bare_url(self):
        with self.assertRaises(ingest_core.IngestError):
            ingest_core.sanity_check("")
        with self.assertRaises(ingest_core.IngestError):
            ingest_core.sanity_check("   \n\t  ")
        with self.assertRaises(ingest_core.IngestError):
            ingest_core.sanity_check("too short to be a job posting")
        with self.assertRaises(ingest_core.IngestError):
            ingest_core.sanity_check("https://linkedin.com/jobs/view/12345")
        with self.assertRaises(ingest_core.IngestError):
            ingest_core.sanity_check("  https://example.com/careers/role  \n")

    def test_sanity_check_warns_when_posting_words_are_missing(self):
        filler = "x" * 220
        warnings = ingest_core.sanity_check(filler)
        self.assertTrue(any("posting" in warning.lower() for warning in warnings))

    def test_ingest_writes_catalog_record_with_provenance_and_interested_triage(self):
        url = "https://linkedin.com/jobs/view/998877"
        expected_id = "ingest:" + __import__("hashlib").sha1(url.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            result = ingest_core.ingest(
                directory,
                self.POSTING,
                title="Senior Backend Engineer",
                company="Acme Labs",
                location="Remote — Europe",
                url=url,
                policy=self._policy(),
                angles=TEST_ANGLES,
                ingested_at=self.INGESTED_AT,
            )
            record = catalog_core.load_record(directory, expected_id)

        self.assertEqual(result.record["job_id"], expected_id)
        self.assertEqual(record["job_id"], expected_id)
        self.assertEqual(record["source"], "ingest")
        self.assertEqual(record["title"], "Senior Backend Engineer")
        self.assertEqual(record["company"], "Acme Labs")
        self.assertEqual(record["location"], "Remote — Europe")
        self.assertEqual(record["url"], url)
        self.assertEqual(record["source_url"], url)
        self.assertEqual(record["description"], self.POSTING)
        self.assertEqual(record["raw_paste"], self.POSTING)
        self.assertEqual(record["description_source"], "manual-paste")
        self.assertEqual(record["ingested_at"], self.INGESTED_AT)
        self.assertEqual(record["parsed_by"], "agent")
        self.assertIs(record["parse_confirmed"], True)
        self.assertEqual(record["triage"], "interested")
        self.assertEqual(record["first_seen"], self.INGESTED_AT)
        self.assertEqual(record["last_seen"], self.INGESTED_AT)
        self.assertEqual(record["angle"], "backend_principal")
        self.assertGreaterEqual(record["fit_score"], 1)

    def test_paste_only_ingest_uses_field_hash_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            result = ingest_core.ingest(
                directory,
                self.POSTING,
                title="Senior Backend Engineer",
                company="Acme Labs",
                location="Stockholm",
                url="",
                policy=self._policy(),
                angles=TEST_ANGLES,
                ingested_at=self.INGESTED_AT,
            )
            record = catalog_core.load_record(directory, result.record["job_id"])

        self.assertTrue(result.record["job_id"].startswith("ingest:"))
        self.assertEqual(len(result.record["job_id"]), len("ingest:") + 12)
        self.assertEqual(record["source_url"], "")
        self.assertEqual(record["description_source"], "manual-paste")

    def test_triage_open_override_and_advisory_gates_never_drop(self):
        # US-only remote + no angle cues → would drop on a fetch; ingest admits.
        weak_text = (
            "Join our team in a unique opportunity based in the United States only. "
            "Must be located in the United States. Eastern time zone required. " + ("word " * 40)
        )
        with tempfile.TemporaryDirectory() as directory:
            result = ingest_core.ingest(
                directory,
                weak_text,
                title="Mystery Role",
                company="US Corp",
                location="United States",
                url="https://example.com/jobs/us-only",
                triage="open",
                policy=self._policy(),
                angles=TEST_ANGLES,
                ingested_at=self.INGESTED_AT,
            )
            record = catalog_core.load_record(directory, result.record["job_id"])

        self.assertEqual(record["triage"], "open")
        self.assertEqual(record["description_source"], "manual-paste")
        self.assertTrue(
            any(
                "location" in w.lower() or "timezone" in w.lower() or "tz" in w.lower()
                for w in result.warnings
            )
        )
        self.assertTrue(
            any(
                "angle" in w.lower() or "fit" in w.lower() or "weak" in w.lower()
                for w in result.warnings
            )
        )
        self.assertEqual(record.get("angle", ""), "")
        self.assertEqual(record.get("fit_score", 0), 0)

    def test_reingest_same_url_is_idempotent_without_force(self):
        url = "https://example.com/jobs/backend"
        with tempfile.TemporaryDirectory() as directory:
            first = ingest_core.ingest(
                directory,
                self.POSTING,
                title="Senior Backend Engineer",
                company="Acme Labs",
                location="Remote",
                url=url,
                policy=self._policy(),
                angles=TEST_ANGLES,
                ingested_at=self.INGESTED_AT,
            )
            path = catalog_core.record_path(directory, first.record["job_id"])
            before = pathlib.Path(path).read_text(encoding="utf-8")
            second = ingest_core.ingest(
                directory,
                self.POSTING + "\nExtra paragraph that must not replace.\n",
                title="Different Title",
                company="Other Co",
                location="US",
                url=url,
                policy=self._policy(),
                angles=TEST_ANGLES,
                ingested_at="2026-07-18T12:00:00+00:00",
            )
            after = pathlib.Path(path).read_text(encoding="utf-8")
            record = catalog_core.load_record(directory, first.record["job_id"])

        self.assertFalse(second.created)
        self.assertEqual(before, after)
        self.assertEqual(record["title"], "Senior Backend Engineer")
        self.assertEqual(record["description"], self.POSTING)
        self.assertTrue(any("force" in w.lower() for w in second.warnings))

    def test_force_reingest_replaces_paste_and_writes_bak(self):
        url = "https://example.com/jobs/backend"
        replacement = self.POSTING + "\nUpdated paste body with architecture and mentoring.\n"
        with tempfile.TemporaryDirectory() as directory:
            first = ingest_core.ingest(
                directory,
                self.POSTING,
                title="Senior Backend Engineer",
                company="Acme Labs",
                location="Remote",
                url=url,
                policy=self._policy(),
                angles=TEST_ANGLES,
                ingested_at=self.INGESTED_AT,
            )
            job_id = first.record["job_id"]
            path = pathlib.Path(catalog_core.record_path(directory, job_id))
            second = ingest_core.ingest(
                directory,
                replacement,
                title="Staff Backend Engineer",
                company="Acme Labs",
                location="Remote — EU",
                url=url,
                force=True,
                policy=self._policy(),
                angles=TEST_ANGLES,
                ingested_at="2026-07-18T12:00:00+00:00",
            )
            record = catalog_core.load_record(directory, job_id)
            bak = pathlib.Path(str(path) + ".bak")

            self.assertFalse(second.created)
            self.assertEqual(second.backup_path, str(bak))
            self.assertTrue(bak.exists())
            self.assertIn("Senior Backend Engineer", bak.read_text(encoding="utf-8"))
            self.assertEqual(record["title"], "Staff Backend Engineer")
            self.assertEqual(record["description"], replacement)
            self.assertEqual(record["raw_paste"], replacement)
            self.assertEqual(record["first_seen"], self.INGESTED_AT)
            self.assertEqual(record["last_seen"], "2026-07-18T12:00:00+00:00")
            self.assertEqual(record["triage"], "interested")

    def test_force_reingest_preserves_existing_triage(self):
        url = "https://example.com/jobs/preserve-triage"
        with tempfile.TemporaryDirectory() as directory:
            first = ingest_core.ingest(
                directory,
                self.POSTING,
                title="Senior Backend Engineer",
                company="Acme Labs",
                location="Remote",
                url=url,
                triage="interested",
                policy=self._policy(),
                angles=TEST_ANGLES,
                ingested_at=self.INGESTED_AT,
            )
            catalog_core.set_triage(
                directory, first.record["job_id"], "skipped", skip_reason="comp too low"
            )
            ingest_core.ingest(
                directory,
                self.POSTING + "\nForce refresh.\n",
                title="Senior Backend Engineer",
                company="Acme Labs",
                location="Remote",
                url=url,
                force=True,
                triage="open",  # must not clobber the stored skip
                policy=self._policy(),
                angles=TEST_ANGLES,
                ingested_at="2026-07-18T12:00:00+00:00",
            )
            record = catalog_core.load_record(directory, first.record["job_id"])

        self.assertEqual(record["triage"], "skipped")
        self.assertEqual(record["skip_reason"], "comp too low")

    def test_fetch_does_not_overwrite_manual_paste_description(self):
        # Seed a catalog record that looks like a fetch-admitted job but carries
        # a manual-paste description, then upsert a richer fetch hit for the
        # same id — the paste must stick.
        job_id = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        with tempfile.TemporaryDirectory() as directory:
            seed = {
                "schema_version": catalog_core.SCHEMA_VERSION,
                "job_id": job_id,
                "company": "Nordic Charge AB",
                "title": "Senior Backend Engineer (Node)",
                "location": "Stockholm",
                "url": "https://jobs.example.test/29000001",
                "apply_url": "https://jobs.example.test/29000001",
                "listing_url": "",
                "description": self.POSTING,
                "posted": "",
                "deadline": "",
                "source": "jobtech",
                "source_id": "29000001",
                "source_ref": "jobsearch.api.jobtechdev.se",
                "source_queries": ["backend engineer"],
                "description_source": "manual-paste",
                "detail_url": "",
                "hn_thread_id": "",
                "source_url": "",
                "raw_paste": self.POSTING,
                "ingested_at": self.INGESTED_AT,
                "parsed_by": "agent",
                "parse_confirmed": True,
                "retrieved_at": self.INGESTED_AT,
                "first_seen": self.INGESTED_AT,
                "last_seen": self.INGESTED_AT,
                "score": 1,
                "angle": "backend_principal",
                "fit_score": 2,
                "fit_breakdown": {"angle": 2, "seniority": 0, "rn": 0},
                "attrs": {},
                "hits": ["backend"],
                "triage": "interested",
                "skip_reason": "",
                "application": "",
            }
            catalog_core.put_record(directory, seed)
            payload = json.loads((FIXTURES / "jobtech-search.json").read_text(encoding="utf-8"))
            fetch_core.run(
                {
                    "searches": [{"source": "jobtech", "q": "backend engineer", "limit": 50}],
                    "boards": [],
                    "angles": TEST_ANGLES,
                },
                self._policy(),
                get=lambda url: payload,
                repo_root=directory,
                today="2026-07-17",
                retrieved_at="2026-07-18T06:00:00+00:00",
            )
            record = catalog_core.load_record(directory, job_id)

        self.assertEqual(record["description"], self.POSTING)
        self.assertEqual(record["description_source"], "manual-paste")
        self.assertEqual(record["raw_paste"], self.POSTING)
        self.assertEqual(record["last_seen"], "2026-07-18T06:00:00+00:00")


class CatalogFixupTests(unittest.TestCase):
    """Issue #14 close-out: schema discard, description precedence, cluster URLs."""

    RETRIEVED_AT = "2026-07-18T06:00:00+00:00"

    def _policy(self):
        return jobs_fetch.load_yaml(jobs_fetch.PREFS)

    def test_fetch_discards_schema_v1_and_stamps_v3_on_upsert(self):
        job_id = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        with tempfile.TemporaryDirectory() as directory:
            catalog_core.put_record(
                directory,
                {
                    "schema_version": 1,
                    "job_id": job_id,
                    "company": "Nordic Charge AB",
                    "title": "Senior Backend Engineer (Node)",
                    "location": "Stockholm",
                    "url": "https://jobs.example.test/29000001",
                    "apply_url": "https://jobs.example.test/29000001",
                    "listing_url": "",
                    "description": "Old v1 body with Node.js and GraphQL.",
                    "posted": "",
                    "deadline": "",
                    "source": "jobtech",
                    "source_id": "29000001",
                    "source_ref": "jobsearch.api.jobtechdev.se",
                    "source_queries": ["backend engineer"],
                    "description_source": "search",
                    "detail_url": "",
                    "hn_thread_id": "",
                    "source_url": "",
                    "raw_paste": "",
                    "ingested_at": "",
                    "parsed_by": "",
                    "parse_confirmed": False,
                    "retrieved_at": "2026-07-01T00:00:00+00:00",
                    "first_seen": "2026-07-01T00:00:00+00:00",
                    "last_seen": "2026-07-01T00:00:00+00:00",
                    "score": 99,
                    "angle": "",
                    "fit_score": 0,
                    "fit_breakdown": {},
                    "attrs": {},
                    "hits": [],
                    "triage": "skipped",
                    "skip_reason": "stale v1 decision",
                    "application": "",
                    "cluster_id": "",
                },
            )
            # Force the on-disk label back to v1 (put_record stamps current).
            path = catalog_core.record_path(directory, job_id)
            stored = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
            stored["schema_version"] = 1
            pathlib.Path(path).write_text(json.dumps(stored), encoding="utf-8")

            payload = json.loads((FIXTURES / "jobtech-search.json").read_text(encoding="utf-8"))
            fetch_core.run(
                {
                    "searches": [{"source": "jobtech", "q": "backend engineer", "limit": 50}],
                    "boards": [],
                    "angles": TEST_ANGLES,
                },
                self._policy(),
                get=lambda url: payload,
                repo_root=directory,
                today="2026-07-18",
                retrieved_at=self.RETRIEVED_AT,
            )
            record = catalog_core.load_record(directory, job_id)

        self.assertIsNotNone(record)
        self.assertEqual(record["schema_version"], catalog_core.SCHEMA_VERSION)
        # v1 discarded — triage does not survive.
        self.assertEqual(record["triage"], "open")
        self.assertNotEqual(record["score"], 99)

    def test_newer_shorter_description_replaces_older_longer(self):
        job_id = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        with tempfile.TemporaryDirectory() as directory:
            seed = {
                "schema_version": catalog_core.SCHEMA_VERSION,
                "job_id": job_id,
                "company": "Nordic Charge AB",
                "title": "Senior Backend Engineer (Node)",
                "location": "Stockholm",
                "url": "https://jobs.example.test/29000001",
                "apply_url": "https://jobs.example.test/29000001",
                "listing_url": "",
                "description": "Long original description. " + ("detail " * 80),
                "posted": "",
                "deadline": "",
                "source": "jobtech",
                "source_id": "29000001",
                "source_ref": "jobsearch.api.jobtechdev.se",
                "source_queries": ["backend engineer"],
                "description_source": "search",
                "detail_url": "",
                "hn_thread_id": "",
                "source_url": "",
                "raw_paste": "",
                "ingested_at": "",
                "parsed_by": "",
                "parse_confirmed": False,
                "retrieved_at": "2026-07-01T00:00:00+00:00",
                "first_seen": "2026-07-01T00:00:00+00:00",
                "last_seen": "2026-07-01T00:00:00+00:00",
                "score": 1,
                "angle": "backend_principal",
                "fit_score": 2,
                "fit_breakdown": {"angle": 2, "seniority": 0, "rn": 0},
                "attrs": {},
                "hits": ["backend"],
                "triage": "open",
                "skip_reason": "",
                "application": "",
                "cluster_id": "",
            }
            catalog_core.put_record(directory, seed)
            payload = json.loads((FIXTURES / "jobtech-search.json").read_text(encoding="utf-8"))
            # Fixture body for 29000001 is shorter than the seeded long description.
            fetch_core.run(
                {
                    "searches": [{"source": "jobtech", "q": "backend engineer", "limit": 50}],
                    "boards": [],
                    "angles": TEST_ANGLES,
                },
                self._policy(),
                get=lambda url: payload,
                repo_root=directory,
                today="2026-07-18",
                retrieved_at=self.RETRIEVED_AT,
            )
            record = catalog_core.load_record(directory, job_id)

        self.assertNotIn("Long original description", record["description"])
        self.assertLess(len(record["description"]), len(seed["description"]))
        self.assertEqual(record["last_seen"], self.RETRIEVED_AT)

    def test_homepage_and_privacy_urls_do_not_cluster_unrelated_remotive_jobs(self):
        shared_homepage = "https://acme.example/"
        privacy = "https://acme.example/privacy"
        payload = {
            "job-count": 2,
            "jobs": [
                {
                    "id": 1001,
                    "url": "https://remotive.com/remote-jobs/software-development/role-a-1001",
                    "title": "Senior Backend Engineer",
                    "company_name": "Acme One",
                    "category": "Software Development",
                    "tags": ["typescript", "node"],
                    "job_type": "full_time",
                    "publication_date": "2026-07-16T08:00:00",
                    "candidate_required_location": "Europe",
                    "salary": "",
                    "description": (
                        f"<p>Node.js and GraphQL. Remote Europe.</p>"
                        f'<p>Home: <a href="{shared_homepage}">acme</a></p>'
                    ),
                },
                {
                    "id": 1002,
                    "url": "https://remotive.com/remote-jobs/software-development/role-b-1002",
                    "title": "Staff Backend Engineer",
                    "company_name": "Acme Two",
                    "category": "Software Development",
                    "tags": ["typescript", "node"],
                    "job_type": "full_time",
                    "publication_date": "2026-07-16T08:00:00",
                    "candidate_required_location": "Europe",
                    "salary": "",
                    "description": (
                        f"<p>Node.js services. Remote Europe.</p>"
                        f'<p>Policy: <a href="{privacy}">privacy</a></p>'
                    ),
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = fetch_core.run(
                {
                    "searches": [{"source": "remotive", "category": "software-dev"}],
                    "boards": [],
                    "angles": TEST_ANGLES,
                },
                self._policy(),
                get=lambda url: payload,
                repo_root=directory,
                today="2026-07-18",
                retrieved_at=self.RETRIEVED_AT,
            )
            records = {record["job_id"]: record for record in catalog_core.load_records(directory)}

        self.assertEqual(len(result.kept), 2)
        self.assertEqual(records["remotive:remotive.com:1001"]["apply_url"], "")
        self.assertEqual(records["remotive:remotive.com:1002"]["apply_url"], "")
        self.assertEqual(records["remotive:remotive.com:1001"]["cluster_id"], "")
        self.assertEqual(records["remotive:remotive.com:1002"]["cluster_id"], "")
        self.assertIsNotNone(result.source_stats)
        remotive = next(row for row in result.source_stats if row.key == "remotive/software-dev")
        self.assertEqual(remotive.scanned, 2)
        self.assertEqual(remotive.kept, 2)


class ReviewCloseoutRegressionTests(unittest.TestCase):
    """Regression guards for the #14 review close-out fixes."""

    RETRIEVED_AT = "2026-07-18T06:00:00+00:00"

    def _record(self, job_id, *, retrieved_at=None, **fields):
        job = {"job_id": job_id, "company": "Acme", "title": "Engineer", **fields}
        return catalog_core.record_from_job(job, retrieved_at or self.RETRIEVED_AT)

    def test_triage_stamps_acknowledgement_and_clears_new(self):
        # Triaging a same-fetch job must clear its derived New label (#14).
        job_id = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        watermark = self.RETRIEVED_AT
        with tempfile.TemporaryDirectory() as directory:
            record = self._record(job_id, retrieved_at=watermark, desc="Node backend.", fit_score=2)
            catalog_core.put_record(directory, record)
            seeded = catalog_core.load_record(directory, job_id)
            self.assertEqual(catalog_core.freshness_label(seeded, watermark), "New")

            updated = catalog_core.set_triage(
                directory, job_id, "interested", at="2026-07-18T07:00:00+00:00"
            )

        self.assertEqual(updated["acknowledged_at"], "2026-07-18T07:00:00+00:00")
        self.assertNotEqual(catalog_core.freshness_label(updated, watermark), "New")

    def test_triage_preserves_prior_acknowledgement_timestamp(self):
        # A second triage never rewrites an existing acknowledgement moment.
        job_id = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        with tempfile.TemporaryDirectory() as directory:
            record = self._record(
                job_id, desc="Node backend.", acknowledged_at="2026-07-18T05:00:00+00:00"
            )
            catalog_core.put_record(directory, record)
            updated = catalog_core.set_triage(
                directory, job_id, "interested", at="2026-07-18T07:00:00+00:00"
            )
        self.assertEqual(updated["acknowledged_at"], "2026-07-18T05:00:00+00:00")

    def test_new_cluster_mate_inherits_acknowledgement(self):
        # A richer duplicate joining an acknowledged cluster must inherit the
        # acknowledgement so the cluster never resurfaces as New (#14).
        apply_url = "https://acme.example/careers/eng-42"
        ack_at = "2026-07-18T05:00:00+00:00"
        first_id = "remotive:remotive.com:1"
        second_id = "jobtech:jobsearch.api.jobtechdev.se:2"
        later = "2026-07-19T06:00:00+00:00"
        with tempfile.TemporaryDirectory() as directory:
            first = self._record(
                first_id, apply_url=apply_url, desc="Short.", acknowledged_at=ack_at
            )
            catalog_core.put_record(directory, first)
            second = self._record(
                second_id, retrieved_at=later, apply_url=apply_url, desc="Much longer body " * 10
            )
            catalog_core.put_record(directory, second)

            stored_second = catalog_core.load_record(directory, second_id)
            mates = [catalog_core.load_record(directory, jid) for jid in (first_id, second_id)]
            view = catalog_core.view_record_for_cluster(mates)

        self.assertNotEqual(stored_second["cluster_id"], "")
        self.assertEqual(stored_second["cluster_id"], mates[0]["cluster_id"])
        self.assertEqual(stored_second["acknowledged_at"], ack_at)
        # The richer new mate wins display, yet the cluster stays acknowledged.
        self.assertEqual(view["job_id"], second_id)
        self.assertNotEqual(catalog_core.freshness_label(view, later), "New")

    def test_fractional_fit_survives_ranking_chrome(self):
        # Half-point RN fit must not be truncated in ranking chrome (#14).
        half = {
            "job_id": "a",
            "cluster_id": "",
            "fit_score": 2.5,
            "score": 9,
            "first_seen": self.RETRIEVED_AT,
            "last_seen": self.RETRIEVED_AT,
        }
        whole = {
            "job_id": "b",
            "cluster_id": "",
            "fit_score": 2.0,
            "score": 50,
            "first_seen": self.RETRIEVED_AT,
            "last_seen": self.RETRIEVED_AT,
        }
        views = catalog_core.cluster_view_records([whole, half])
        by_id = {row["job_id"]: row for row in views}
        self.assertEqual(by_id["a"]["cluster_fit_score"], 2.5)
        self.assertEqual(catalog_core.rank_fit_score(by_id["a"]), 2.5)
        views.sort(
            key=lambda row: (catalog_core.rank_fit_score(row), row.get("score", 0)), reverse=True
        )
        # Despite b's far higher attribute score, the half-point fit ranks first.
        self.assertEqual([row["job_id"] for row in views], ["a", "b"])

    def test_cluster_fit_score_is_max_without_truncation(self):
        mates = [
            {"job_id": "a", "cluster_id": "c", "fit_score": 2.5, "description": "short"},
            {
                "job_id": "b",
                "cluster_id": "c",
                "fit_score": 2.0,
                "description": "a much longer body",
            },
        ]
        view = catalog_core.view_record_for_cluster(mates)
        self.assertEqual(view["cluster_fit_score"], 2.5)

    def test_view_labels_paste_provenance_on_overlay(self):
        # Paste text shown on the display winner carries its own provenance so the
        # row never labels paste content as the winner's board source (ADR-0003).
        mates = [
            {
                "job_id": "win",
                "cluster_id": "c",
                "fit_score": 3,
                "description": "winner body from the board",
                "description_source": "search",
                "source": "remotive",
            },
            {
                "job_id": "paste",
                "cluster_id": "c",
                "fit_score": 1,
                "description": "PASTED TEXT",
                "description_source": "manual-paste",
                "source": "ingest",
                "source_url": "https://linkedin.example/x",
                "raw_paste": "PASTED TEXT",
            },
        ]
        view = catalog_core.view_record_for_cluster(mates)
        self.assertEqual(view["description"], "PASTED TEXT")
        self.assertEqual(view["description_source"], "manual-paste")
        self.assertEqual(view["source_url"], "https://linkedin.example/x")
        self.assertEqual(view["raw_paste"], "PASTED TEXT")
        self.assertEqual(view["source"], "remotive")

    def test_triage_write_restamps_schema_version(self):
        # The central write chokepoint stamps v3 even for a stale on-disk record.
        job_id = "jobtech:jobsearch.api.jobtechdev.se:29000001"
        with tempfile.TemporaryDirectory() as directory:
            catalog_core.put_record(directory, self._record(job_id, desc="Body", fit_score=2))
            path = catalog_core.record_path(directory, job_id)
            stored = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
            stored["schema_version"] = 2
            pathlib.Path(path).write_text(json.dumps(stored), encoding="utf-8")

            updated = catalog_core.set_triage(directory, job_id, "interested")
            on_disk = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))

        self.assertEqual(updated["schema_version"], catalog_core.SCHEMA_VERSION)
        self.assertEqual(on_disk["schema_version"], catalog_core.SCHEMA_VERSION)

    def test_save_records_restamps_schema_version(self):
        with tempfile.TemporaryDirectory() as directory:
            record = self._record("ingest:1", desc="Body")
            record["schema_version"] = 1
            catalog_core.save_records(directory, [record])
            on_disk = catalog_core.load_record(directory, "ingest:1")
        self.assertEqual(on_disk["schema_version"], catalog_core.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
