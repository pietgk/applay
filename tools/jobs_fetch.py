#!/usr/bin/env python3
"""CLI adapter for public job-board discovery and shortlist reports."""

import argparse
import json
import os
import ssl
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, os.path.join(HERE, "..", "src"))

from apply import fetch as fetch_core  # noqa: E402
from apply import jobs as core  # noqa: E402

CFG = os.path.join(HERE, "jobs_sources.yaml")
PREFS = os.path.join(HERE, "preferences.yaml")
ROOT = os.path.join(HERE, "..")
UA = {"User-Agent": "Mozilla/5.0 (job-scan; personal use)"}


def build_ssl_context(insecure=False):
    """Build the transport trust context used by the command-line fetcher."""
    if insecure:
        return ssl._create_unverified_context()
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        pass
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL_CTX = build_ssl_context()


def get(url):
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=25, context=_SSL_CTX) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


# Thin wrappers over the fetch core that resolve this module's `get` at call
# time, so tests and --self-test can swap the transport by patching `get`.
def from_greenhouse(token, company):
    return fetch_core.greenhouse(get, token, company)


def from_lever(token, company):
    return fetch_core.lever(get, token, company)


def from_ashby(token, company):
    return fetch_core.ashby(get, token, company)


def from_jobtech(spec):
    return fetch_core.jobtech_search(get, spec)


def from_remotive(spec):
    return fetch_core.remotive_search(get, spec)


def from_hn(spec):
    return fetch_core.hn_search(get, spec)


def fetch_jobtech_ad(ad_id):
    return fetch_core.jobtech_ad(get, ad_id)


FETCHERS = {"greenhouse": from_greenhouse, "lever": from_lever, "ashby": from_ashby}
SEARCHERS = {"jobtech": from_jobtech, "remotive": from_remotive, "hn": from_hn}

# Preserve the helper names that existing offline users import from the CLI.
strip_html = core.strip_html
clean_job_description = core.clean_job_description
stable_job_id = core.stable_job_id
shell_quote = core.shell_quote
detect_employment = core.detect_employment
detect_arrangement = core.detect_arrangement
classify_region = core.classify_region
detect_pay = core.detect_pay
extract = core.extract
location_verdict = core.location_verdict
keyword_score = core.keyword_score
classify_angle = core.classify_angle
pref_score = core.pref_score
pay_points = core.pay_points
fmt_attrs = core.fmt_attrs
missing = core.missing


def load_yaml(path):
    import yaml

    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def self_test():
    policy = load_yaml(PREFS)
    weights = policy["weights"]
    cases = [
        dict(
            company="A",
            title="Senior Full-Stack Engineer (TypeScript)",
            location="Remote - Europe",
            desc="Node, GraphQL. Hybrid, 2 days in office. €600 per day.",
            commitment="Contract",
            workplace="hybrid",
            remote_flag=None,
        ),
        dict(
            company="B",
            title="Staff Engineer",
            location="New York, NY",
            desc="Onsite in our NYC office. US only.",
            commitment="Full Time",
            workplace="onsite",
            remote_flag=None,
        ),
        dict(
            company="C",
            title="Backend Engineer",
            location="Stockholm, Sweden",
            desc="Permanent role. Fully remote within Sweden.",
            commitment="",
            workplace="remote",
            remote_flag=True,
        ),
    ]
    for job in cases:
        attrs = extract(job, policy)
        keep, reason = location_verdict(attrs)
        keyword = keyword_score(job, ["typescript", "graphql", "backend"], weights)
        preference = pref_score(attrs, weights, policy["pay"])
        print(
            f"{job['company']}: keep={keep} ({reason or 'ok'}) total={keyword + preference} | "
            f"{fmt_attrs(attrs)} | missing={missing(attrs)}"
        )

    payload = {
        "hits": [
            {
                "headline": "Senior Backend Engineer (Node)",
                "employment_type": {"label": "Vanlig anställning"},
                "duration": {"label": "Tills vidare"},
                "workplace_address": {
                    "city": "Stockholm",
                    "region": "Stockholms län",
                    "country": "Sverige",
                },
                "employer": {"workplace": "Acme AB", "name": "Acme AB"},
                "application_details": {"url": "https://jobs.acme.se/1"},
                "description": {"text": "Node, GraphQL, PostgreSQL. Hybrid, 2 days in office."},
                "publication_date": "2026-07-09",
            }
        ]
    }
    original_get = globals()["get"]
    try:
        globals()["get"] = lambda url: payload
        jobtech = from_jobtech({"q": "backend", "limit": 10})[0]
        attrs = extract(jobtech, policy)
        print(
            f"jobtech: {jobtech['company']} | commit->{jobtech['commitment']} | "
            f"{fmt_attrs(attrs)} | url={jobtech['url']}"
        )
        assert jobtech["commitment"] == "permanent" and attrs["region"] == "sweden"
    finally:
        globals()["get"] = original_get
    print("self-test done")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="disable TLS verification (last resort behind a MITM proxy)",
    )
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.insecure:
        global _SSL_CTX
        _SSL_CTX = build_ssl_context(insecure=True)

    config = load_yaml(CFG)
    policy = load_yaml(PREFS)
    result = fetch_core.run(config, policy, get=get, repo_root=ROOT)
    print(
        f"wrote {result.markdown_path}  ({len(result.kept)} kept, {len(result.dropped)} dropped, {result.scanned} scanned, {len(result.errors)} errors)"
    )
    for job in result.kept[:10]:
        print(
            f"  [fit {job['fit_score']}] {job['title']} — {job['company']} — "
            f"{job['angle']} — {fmt_attrs(job['attrs'])}"
        )
    ui_port = os.environ.get("APPLY_UI_PORT", "5052")
    print(
        f"Next: open http://127.0.0.1:{ui_port}/jobs and click Interested on the "
        "roles to pursue, then say 'refresh drafts'."
    )


if __name__ == "__main__":
    main()
