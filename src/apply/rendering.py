"""Markdown-to-HTML and one-page PDF rendering orchestration."""

import re
from dataclasses import dataclass
from pathlib import Path

import markdown as md
from weasyprint import HTML

PLACEHOLDER_MARKERS = (
    "<headline_variant from master-profile.yaml>",
    "<3-5 line summary assembled from summary_atoms matching this role's angle>",
    "- **Backend:** ...",
    "- **Frontend:** ...",
    "- **Architecture:** ...",
    "- **Quality & Delivery:** ...",
)


def find_placeholders(text: str) -> list[str]:
    found = [marker for marker in PLACEHOLDER_MARKERS if marker in text]
    if re.search(r"^\s*-\s+\.\.\.\s*$", text, flags=re.MULTILINE):
        found.append("- ...")
    return found


def md_to_body(text: str) -> str:
    lines = text.splitlines()
    headline = contact = ""
    kept = []
    for line in lines:
        if line.startswith("%%headline%%"):
            headline = line[len("%%headline%%") :].strip()
        elif line.startswith("%%contact%%"):
            contact = line[len("%%contact%%") :].strip()
        else:
            kept.append(line)
    fixed = []
    for line in kept:
        if (
            line.lstrip().startswith("- ")
            and fixed
            and fixed[-1].strip()
            and not fixed[-1].lstrip().startswith("- ")
        ):
            fixed.append("")
        fixed.append(line)
    body_html = md.markdown("\n".join(fixed), extensions=["extra", "sane_lists"])
    inject = ""
    if headline:
        inject += f'<p class="headline">{headline}</p>'
    if contact:
        inject += f'<p class="contact">{contact}</p>'
    if inject:
        body_html = re.sub(r"(</h1>)", r"\1" + inject, body_html, count=1)
    return body_html.replace("<ul>", '<ul class="tight">')


def build_html(body_html: str, css_text: str, scale: float) -> str:
    css = css_text.replace("--scale: 1.0;", f"--scale: {scale};")
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"{css}</style></head><body>{body_html}</body></html>"
    )


def page_count(html_text: str) -> int:
    return len(HTML(string=html_text).render().pages)


@dataclass(frozen=True)
class RenderResult:
    html: str
    scale: float
    fits_one_page: bool

    @property
    def fit_message(self) -> str:
        if self.fits_one_page:
            return f"fits 1 page at scale {self.scale}"
        return f"WARNING: still > 1 page at min scale {self.scale} — trim content"


def render_document(text: str, css_text: str, min_scale: float = 0.82) -> RenderResult:
    body = md_to_body(text)
    scale = 1.0
    while scale >= min_scale - 1e-9:
        html_text = build_html(body, css_text, round(scale, 3))
        if page_count(html_text) <= 1:
            return RenderResult(html_text, round(scale, 3), True)
        scale -= 0.03
    return RenderResult(build_html(body, css_text, min_scale), min_scale, False)


def write_pdf(result: RenderResult, output_path: str | Path) -> None:
    HTML(string=result.html).write_pdf(str(output_path))
