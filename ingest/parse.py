"""Parse JATS XML into a stable, cleaned paragraph stream.

Output is one JSONL row per paragraph, keyed by a *chunking-independent* id
(``PMC13417500#p14``). Gold-set ground truth anchors to these ids, so the eval set
survives changes to chunk size and strategy — chunking is the experiment variable,
paragraph identity is not.

Cleaning rules (frozen; changing them renumbers paragraph ids and invalidates the
gold set):
  dropped  ref-list, fig, disp-formula, supplementary-material, xref markers
  kept     abstract, body paragraphs, tables (flattened to pipe-delimited text)

Section labels come from <title> text, not the sec-type attribute: 3652 of ~4300
sections in this corpus carry no sec-type, and the ones that do are inconsistent
(intro/introduction, materials|methods). Nested sections inherit their top-level
ancestor's label, so "Statistical analysis" lands under methods.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

import tiktoken
from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "corpus.db"
OUT_PATH = ROOT / "data" / "paragraphs.jsonl"

DROP_TAGS = ("ref-list", "fig", "disp-formula", "supplementary-material", "table-wrap-foot")
ENC = tiktoken.get_encoding("cl100k_base")

SECTION_RULES = [
    ("introduction", ("introduction", "background")),
    ("case", ("case report", "case presentation", "case description")),
    (
        "methods",
        (
            "method",
            "material",
            "patient",
            "subject",
            "study design",
            "statistical",
            "acquisition",
            "protocol",
            "analysis",
            "experimental",
        ),
    ),
    ("results", ("result", "finding", "outcome")),
    ("discussion", ("discussion", "limitation")),
    ("conclusion", ("conclusion", "summary", "key point")),
]

# Back matter: declarations about the paper, not content from it. Dropped outright,
# since a retriever that surfaces "Competing interests" for a dosing question is
# spending its top-k budget on nothing.
DROP_SECTION_TITLES = (
    "author contribution",
    "competing interest",
    "conflict of interest",
    "data availability",
    "acknowledg",
    "funding",
    "ethics approval",
    "consent",
    "abbreviation",
    "supplementary",
    "disclosure",
    "institutional review",
)


def normalize_title(raw: str) -> str:
    """Strip leading numbering: '2. Materials and Methods' -> 'materials and methods'.

    The numeral must be followed by '.' or ')'. An earlier version made that separator
    optional, so a bare roman numeral matched the leading 'i' of 'Introduction' and
    pushed 656 paragraphs into 'other'.
    """
    t = raw.strip().lower()
    return re.sub(r"^(\d+(?:\.\d+)*|[ivxlcdm]+)[.)]\s*", "", t).strip(" .:")


def is_backmatter(title: str | None) -> bool:
    if not title:
        return False
    t = normalize_title(title)
    return any(k in t for k in DROP_SECTION_TITLES)


def classify(title: str | None) -> str:
    if not title:
        return "other"
    t = normalize_title(title)
    for label, keywords in SECTION_RULES:
        if any(k in t for k in keywords):
            return label
    return "other"


def squash(el: etree._Element) -> str:
    return re.sub(r"\s+", " ", " ".join(el.itertext())).strip()


def flatten_table(tw: etree._Element) -> str:
    """Render a table as caption + pipe-delimited rows.

    Dose thresholds and eGFR cut-offs live in tables, and 20% of the gold set is
    numeric, so tables are indexed rather than dropped.
    """
    parts = []
    caption = tw.find(".//caption")
    if caption is not None:
        parts.append(squash(caption))
    for tr in tw.iter("tr"):
        cells = [squash(c) for c in tr if etree.QName(c).localname in ("td", "th")]
        if any(cells):
            parts.append(" | ".join(cells))
    return "\n".join(p for p in parts if p)


def walk(el: etree._Element, label: str, sec_title: str | None, out: list, top: bool):
    for child in el:
        tag = etree.QName(child).localname
        if tag == "sec":
            title_el = child.find("./title")
            title = title_el.text.strip() if title_el is not None and title_el.text else None
            if is_backmatter(title):
                continue
            # An untitled or unclassifiable wrapper must not force its label onto
            # children; 30 articles nest all real sections one level down.
            child_label = classify(title) if (top or label == "other") else label
            walk(child, child_label, title or sec_title, out, top=False)
        elif tag == "p":
            text = squash(child)
            if len(text) >= 40:  # drop stubs like "See Table 1."
                out.append((label, sec_title, "p", text))
        elif tag == "table-wrap":
            text = flatten_table(child)
            if text:
                out.append((label, sec_title, "table", text))


def parse_article(pmcid: str) -> list[dict]:
    tree = etree.parse(str(RAW_DIR / f"{pmcid}.xml"), etree.XMLParser(recover=True))
    etree.strip_elements(tree, *DROP_TAGS, with_tail=False)
    etree.strip_elements(tree, "xref", with_tail=False)  # kills "[12]" citation markers

    collected: list = []
    abstract = tree.find(".//front//abstract")
    if abstract is not None:
        for p in abstract.iter("p"):
            text = squash(p)
            if len(text) >= 40:
                collected.append(("abstract", "Abstract", "p", text))

    body = tree.find(".//body")
    if body is not None:
        walk(body, "other", None, collected, top=True)

    rows = []
    for idx, (label, sec_title, kind, text) in enumerate(collected):
        rows.append(
            {
                "para_id": f"{pmcid}#p{idx}",
                "pmcid": pmcid,
                "idx": idx,
                "section": label,
                "section_title": sec_title,
                "kind": kind,
                "text": text,
                "n_tokens": len(ENC.encode(text)),
            }
        )
    return rows


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    pmcids = [
        r[0]
        for r in conn.execute("SELECT pmcid FROM articles WHERE is_retracted = 0 ORDER BY pmcid")
    ]
    conn.close()

    all_rows, empty = [], []
    for pmcid in pmcids:
        rows = parse_article(pmcid)
        if not rows:
            empty.append(pmcid)
        all_rows.extend(rows)

    with OUT_PATH.open("w") as fh:
        for row in all_rows:
            fh.write(json.dumps(row) + "\n")

    toks = sorted(r["n_tokens"] for r in all_rows)
    sections = Counter(r["section"] for r in all_rows)
    kinds = Counter(r["kind"] for r in all_rows)

    def pct(p: float) -> int:
        return toks[int(len(toks) * p)]

    print(f"articles: {len(pmcids)}  empty: {len(empty)}  paragraphs: {len(all_rows)}")
    print(f"tokens total: {sum(toks):,}  median: {pct(0.5)}  p90: {pct(0.9)}  max: {toks[-1]}")
    print(f"under 512 tokens: {sum(t <= 512 for t in toks) / len(toks):.1%}")
    print(f"\nkinds: {dict(kinds)}")
    print("sections:")
    for k, v in sections.most_common():
        print(f"  {k:14} {v:6}  ({v / len(all_rows):.0%})")
    if empty:
        print(f"\nno paragraphs extracted: {empty[:10]}")


if __name__ == "__main__":
    main()
