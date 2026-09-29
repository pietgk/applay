"""Pure ATS evaluation used by the lint command and future interfaces."""

import collections
import re
from dataclasses import dataclass

STOP = set(
    """a an the and or of to in for with on at by from as is are be this that
your you we our their they it its role will have has can not you'll we're including
across both while when where which who what how within into over under out about
also more most other new using use used work working experience team teams strong
high quality solutions solution development develop developing developer engineer
engineers technical technology technologies modern responsible responsibilities
ensure identify drive driving lead leading make making maintain maintaining provide
years year plus etc via per e g i e regarding pm job description candidate ideal must should
requirements required nice good great able ability day days end""".split()
    + """och att vi med som en till av det de kommer ett du på för från är i vår
vårt denna den där hur också över under mellan hos samt eller redan både hela genom
inom andra nästa nu idag står inför sin sitt sina sig sigs arbete arbetar utveckling
utveckla utvecklar bygg bygga plattform parkering kunder roll rollen teamet oss för att
enligt vilka vad när där har hade kan ska bör mer mycket mot från hela alla något några
som en tjänst tjänster system systemen digital nästa generationens sverige stockholm""".split()
)
TECH_HINT = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ0-9+#./-]*")
TECHNICAL_TERMS = {
    "api",
    "architecture",
    "arkitektur",
    "aws",
    "azure",
    "backend",
    "ci/cd",
    "cloud",
    "database",
    "databasdesign",
    "design",
    "developer",
    "development",
    "distributed",
    "end-to-end",
    "frontend",
    "fullstack",
    "graphql",
    "golang",
    "hårdvara",
    "infrastructure",
    "java",
    "mobile",
    "molninfrastruktur",
    "native",
    "node.js",
    "pipeline",
    "pipelines",
    "platform",
    "plattform",
    "postgres",
    "postgresql",
    "product",
    "react",
    "relationsdatabaser",
    "scalable",
    "services",
    "systemdesign",
    "system",
    "typescript",
    "webb",
}


def _clean(token: str) -> str:
    token = token.lower().strip(".,;:!?()[]{}\"'`")
    if "@" in token or token.endswith(".com") or token.endswith(".io"):
        return ""
    return token


def tokens(text: str) -> list[str]:
    return [cleaned for cleaned in (_clean(token) for token in TECH_HINT.findall(text)) if cleaned]


def phrases(text: str) -> tuple[list[str], list[str]]:
    """Return stopword-filtered unigrams and bigrams."""
    words = tokens(text)
    unigrams = [word for word in words if word not in STOP and len(word) > 1]
    bigrams = [
        f"{a} {b}"
        for a, b in zip(words, words[1:], strict=False)
        if a not in STOP and b not in STOP
    ]
    return unigrams, bigrams


def _is_technical_signal(term: str) -> bool:
    return (
        term in TECHNICAL_TERMS
        or any(character in term for character in ".+#/")
        or term.count("-") >= 1
    )


def section_map(cv_text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current, buffer = "TOP", []
    for line in cv_text.splitlines():
        if line.startswith("#"):
            sections[current] = "\n".join(buffer).lower()
            current = line.strip("# ").strip().upper() or current
            buffer = []
        else:
            buffer.append(line)
    sections[current] = "\n".join(buffer).lower()
    return sections


def _variants(term: str) -> set[str]:
    variants = {term, term[:-1] if term.endswith("s") else term + "s"}
    for separator in ("/", "-"):
        if separator in term:
            parts = term.split(separator)
            variants.update(part for part in parts if len(part) > 1)
            variants.add(term.replace(separator, ""))
    if " " in term:
        variants.update(part for part in term.split() if len(part) > 1)
    translation = {
        "arkitektur": "architecture",
        "databasdesign": "database design",
        "fullstack": "full-stack",
        "hårdvara": "hardware",
        "molninfrastruktur": "cloud infrastructure",
        "relationsdatabaser": "relational databases",
        "systemdesign": "system design",
        "utveckling": "development",
        "webb": "web",
    }.get(term)
    if translation:
        variants.add(translation)
    return variants


@dataclass(frozen=True)
class AtsResult:
    top_terms: tuple[str, ...]
    present: tuple[str, ...]
    missing: tuple[str, ...]
    single_section: tuple[str, ...]
    coverage: int
    metrics: int
    words: int

    @property
    def verdict(self) -> str:
        return (
            "STRONG"
            if self.coverage >= 75 and self.metrics >= 6
            else ("OK" if self.coverage >= 60 else "WEAK")
        )


def evaluate(job_text: str, cv_text: str) -> AtsResult:
    # Imported job snapshots carry provenance comments. They are useful for
    # humans but must not become ATS keywords (URLs, source names, IDs).
    job_text = re.sub(r"<!--.*?-->", " ", job_text, flags=re.DOTALL)
    unigrams, bigrams = phrases(job_text)
    frequency = collections.Counter(unigrams) + collections.Counter(bigrams)
    ranked = [
        term
        for term, _count in sorted(
            frequency.items(),
            key=lambda item: (not _is_technical_signal(item[0]), -item[1], item[0]),
        )[:60]
    ]
    top: list[str] = []
    seen: set[str] = set()
    for term in ranked:
        if len(top) >= 22:
            break
        if term in seen:
            continue
        top.append(term)
        seen.add(term)
    sections = section_map(cv_text)
    present, missing_terms, single_section = [], [], []
    for term in top:
        hits = sum(
            1
            for section in sections.values()
            if any(variant in section for variant in _variants(term))
        )
        if hits >= 1:
            present.append(term)
            if hits < 2:
                single_section.append(term)
        else:
            missing_terms.append(term)
    coverage = round(100 * len(present) / max(1, len(top)))
    metrics = len(re.findall(r"\b\d+%|\b\d+x\b|[$€£]\s?\d|\b\d[\d,\.]*\b", cv_text))
    words = len(re.findall(r"\w+", cv_text))
    return AtsResult(
        tuple(top),
        tuple(present),
        tuple(missing_terms),
        tuple(single_section),
        coverage,
        metrics,
        words,
    )


def format_report(result: AtsResult) -> str:
    missing_terms = ", ".join(result.missing) or "none"
    single_section = ", ".join(result.single_section) or "none"
    return (
        "\n=== ATS LINT ===\n"
        f"Keyword coverage : {result.coverage}%  ({len(result.present)}/{len(result.top_terms)} top JD terms)   target >=75%\n"
        f"Quantified hits  : {result.metrics}   (aim for >=6 metrics/numbers)\n"
        f"CV word count    : {result.words}   (1-page target ~430-560)\n\n"
        f"MISSING (add if truthful): {missing_terms}\n"
        "ONLY IN ONE SECTION (mirror a few of these into summary/skills): "
        f"{single_section}\n\nVERDICT: {result.verdict}\n"
    )
