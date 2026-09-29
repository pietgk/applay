#!/usr/bin/env python3
"""CLI adapter for creating and importing application folders."""

import argparse
import datetime
import os
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from apply import applications as core  # noqa: E402

try:
    from jobs_fetch import fetch_jobtech_ad
except ModuleNotFoundError:  # pragma: no cover - supports importing as tools.new_application
    from tools.jobs_fetch import fetch_jobtech_ad

APPS = os.path.join(HERE, "..", "applications")

# Keep the established helper/constants surface available to existing callers.
CV_STUB = core.CV_STUB
META_STUB = core.META_STUB
JOB_PLACEHOLDER = core.JOB_PLACEHOLDER
slug = core.slug
yaml_quote = core.yaml_quote
yaml_scalar = core.yaml_scalar
load_report = core.load_report
select_report_job = core.select_report_job
imported_job_markdown = core.imported_job_markdown
normalize_for_compare = core.normalize_for_compare
job_body = core.job_body
existing_matches_source = core.existing_matches_source
is_job_placeholder = core.is_job_placeholder
update_meta = core.update_meta
scaffold_from_report = core.scaffold_from_report
jobtech_ad_id = core.jobtech_ad_id


def refresh_job(job):
    return core.refresh_job(job, fetch_jobtech_ad)


def create_from_source(
    company: str | None = None,
    role: str = "",
    date: str | None = None,
    from_report: str | None = None,
    job_id: str | None = None,
    job_index: int | None = None,
    match: str | None = None,
    refresh: bool = False,
    force: bool = False,
) -> str:
    """Create/import an application and return its folder path.

    This is shared by the original ``new`` command and the higher-level CV
    workflow command so orchestration does not have to shell out to another
    CLI process.
    """
    date = date or datetime.date.today().isoformat()
    job = None
    report_path = ""
    did_refresh = False
    if from_report:
        jobs = load_report(from_report)
        job = select_report_job(jobs, job_id or "", job_index, match or "")
        report_path = from_report
        if refresh:
            try:
                job = refresh_job(job)
                did_refresh = True
            except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as error:
                if job.get("description"):
                    print(f"detail refresh failed; using saved report snapshot: {error}")
                else:
                    raise SystemExit(f"could not fetch selected job detail: {error}") from error
        company = company or str(job.get("company", ""))
        role = role or str(job.get("title", ""))
    elif job_id:
        try:
            job = fetch_jobtech_ad(jobtech_ad_id(job_id))
            did_refresh = True
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as error:
            raise SystemExit(f"could not fetch job detail: {error}") from error
        company = company or str(job.get("company", ""))
        role = role or str(job.get("title", ""))
    else:
        if not company:
            raise SystemExit("company is required unless --from-report is used")

    if not company:
        raise SystemExit("selected report job has no company")

    folder = os.path.join(APPS, f"{date}_{slug(company)}")
    core.create_application(folder, company, role, date)
    if job is not None:
        scaffold_from_report(
            folder,
            company,
            role or str(job.get("title", "role")),
            report_path,
            job,
            force,
            did_refresh or not report_path,
        )
    return folder


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("company", nargs="?")
    parser.add_argument("--role", default="")
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    parser.add_argument("--from-report", help="import the job description from a JSONL shortlist")
    parser.add_argument("--job-id", help="stable job ID from the JSONL shortlist")
    parser.add_argument("--job-index", type=int, help="1-based line number in the JSONL shortlist")
    parser.add_argument("--match", help="case-insensitive company/title match in the shortlist")
    parser.add_argument("--refresh", action="store_true", help="fetch the current detail record")
    parser.add_argument("--force", action="store_true", help="replace imported job.md/source.json")
    args = parser.parse_args()
    print(
        create_from_source(
            args.company,
            args.role,
            args.date,
            args.from_report,
            args.job_id,
            args.job_index,
            args.match,
            args.refresh,
            args.force,
        )
    )


if __name__ == "__main__":
    main()
