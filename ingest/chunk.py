"""Build chunk sets from the frozen paragraph stream.

Chunking is the experiment variable of this project, so all three variants are
produced by the same code path and differ only in how paragraphs are grouped:

  fixed       512-token sliding window with 10% overlap over the whole article.
              Ignores structure. The failure mode this project is built to show:
              "eGFR < 30" and "risk of NSF" land in different windows, and neither
              window scores high enough on a question that spans both.
  section     Consecutive paragraphs packed within one section, never across.
              Section boundaries are semantic boundaries; a chunk that stops at one
              is a chunk whose sentences are actually about the same thing.
  contextual  Section packing plus an article-title + section-name prefix, so an
              isolated "The incidence was 4.3%" carries what study it came from.

Every chunk records the para_ids it covers. Gold-set ground truth is anchored to
paragraphs, so recall is computed as overlap between retrieved chunks' para_ids and
the gold paragraphs — which keeps one gold set valid across all three variants.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from itertools import groupby
from pathlib import Path

import tiktoken

ROOT = Path(__file__).resolve().parent.parent
PARA_PATH = ROOT / "data" / "paragraphs.jsonl"
DB_PATH = ROOT / "data" / "corpus.db"

ENC = tiktoken.get_encoding("cl100k_base")

# bge-small-en-v1.5 truncates at 512 tokens. TARGET leaves headroom so that the
# contextual prefix does not silently push text past the cut-off.
TARGET = 400
HARD_LIMIT = 512
OVERLAP = 0.10


def n_tok(text: str) -> int:
    return len(ENC.encode(text))


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s]


def hard_split(text: str, budget: int) -> list[str]:
    ids = ENC.encode(text)
    return [ENC.decode(ids[i : i + budget]) for i in range(0, len(ids), budget)]


def split_table(text: str, budget: int) -> list[str]:
    """Split a flattened table at row boundaries, repeating caption and header.

    A table fragment without its header row is a grid of numbers with no referents;
    duplicating two lines per piece costs little and keeps every number readable.
    """
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) <= 2:
        return ["\n".join(lines)]
    header, body = lines[:2], lines[2:]
    head_n = n_tok("\n".join(header))

    out, buf, size = [], [], 0
    for line in body:
        s = n_tok(line)
        if buf and head_n + size + s > budget:
            out.append("\n".join(header + buf))
            buf, size = [], 0
        buf.append(line)
        size += s
    if buf:
        out.append("\n".join(header + buf))
    return out


def split_sentences_pack(text: str, budget: int) -> list[str]:
    out, buf, size = [], [], 0
    for sent in split_sentences(text):
        s = n_tok(sent)
        if buf and size + s > budget:
            out.append(" ".join(buf))
            buf, size = [], 0
        buf.append(sent)
        size += s
    if buf:
        out.append(" ".join(buf))
    return out


def split_long(text: str, budget: int, kind: str = "p") -> list[str]:
    """Break an oversized paragraph, then guarantee no piece exceeds the budget."""
    pieces = split_table(text, budget) if kind == "table" else split_sentences_pack(text, budget)
    out = []
    for piece in pieces:
        out.extend([piece] if n_tok(piece) <= budget else hard_split(piece, budget))
    return out


def build_fixed(paras: list[dict]) -> list[dict]:
    tokens: list[int] = []
    owners: list[str] = []
    for p in paras:
        ids = ENC.encode(p["text"] + "\n")
        tokens.extend(ids)
        owners.extend([p["para_id"]] * len(ids))

    step = int(HARD_LIMIT * (1 - OVERLAP))
    chunks = []
    for start in range(0, max(len(tokens), 1), step):
        window = tokens[start : start + HARD_LIMIT]
        if not window:
            break
        chunks.append(
            {
                "text": ENC.decode(window),
                "para_ids": list(dict.fromkeys(owners[start : start + HARD_LIMIT])),
                "section": None,  # deliberately unavailable: no structure, no filter
                "section_title": None,
            }
        )
        if start + HARD_LIMIT >= len(tokens):
            break
    return chunks


def _make_chunk(buf: list[dict], prefix: str, section: str | None, sec_title: str | None) -> dict:
    return {
        "text": prefix + " ".join(b["text"] for b in buf),
        "para_ids": [b["para_id"] for b in buf],
        "section": section,
        "section_title": sec_title,
    }


def build_section(paras: list[dict], prefix_fn=None) -> list[dict]:
    chunks = []
    key = lambda p: (p["section"], p["section_title"])  # noqa: E731
    for (section, sec_title), group in groupby(paras, key=key):
        group = list(group)
        prefix = prefix_fn(section, sec_title) if prefix_fn else ""
        budget = TARGET - n_tok(prefix)

        buf: list[dict] = []
        size = 0
        for p in group:
            # Oversized paragraph: flush what we have, then split it on its own.
            if p["n_tokens"] > budget:
                if buf:
                    chunks.append(_make_chunk(buf, prefix, section, sec_title))
                    buf, size = [], 0
                for piece in split_long(p["text"], budget, p["kind"]):
                    chunks.append(
                        {
                            "text": prefix + piece,
                            "para_ids": [p["para_id"]],
                            "section": section,
                            "section_title": sec_title,
                        }
                    )
                continue
            if size + p["n_tokens"] > budget:
                chunks.append(_make_chunk(buf, prefix, section, sec_title))
                buf, size = [], 0
            buf.append(p)
            size += p["n_tokens"]
        if buf:
            chunks.append(_make_chunk(buf, prefix, section, sec_title))
    return chunks


def main() -> None:
    ap = argparse.ArgumentParser(description="Build chunk sets.")
    ap.add_argument("--variant", choices=["fixed", "section", "contextual", "all"], default="all")
    args = ap.parse_args()

    paras = [json.loads(line) for line in PARA_PATH.open()]
    by_article: dict[str, list[dict]] = defaultdict(list)
    for p in paras:
        by_article[p["pmcid"]].append(p)

    conn = sqlite3.connect(DB_PATH)
    titles = dict(conn.execute("SELECT pmcid, title FROM articles"))
    conn.close()

    variants = ["fixed", "section", "contextual"] if args.variant == "all" else [args.variant]

    for variant in variants:
        rows = []
        for pmcid, article_paras in by_article.items():
            article_paras.sort(key=lambda p: p["idx"])
            if variant == "fixed":
                built = build_fixed(article_paras)
            elif variant == "section":
                built = build_section(article_paras)
            else:
                title = titles.get(pmcid) or ""
                built = build_section(
                    article_paras,
                    prefix_fn=lambda s, st, t=title: f"{t} — {st or s}\n\n",
                )
            for i, c in enumerate(built):
                rows.append(
                    {
                        "chunk_id": f"{pmcid}#{variant}-{i}",
                        "pmcid": pmcid,
                        "n_tokens": n_tok(c["text"]),
                        **c,
                    }
                )

        out = ROOT / "data" / f"chunks_{variant}.jsonl"
        with out.open("w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

        toks = sorted(r["n_tokens"] for r in rows)
        over = sum(t > HARD_LIMIT for t in toks)
        paras_per = sum(len(r["para_ids"]) for r in rows) / len(rows)
        print(
            f"{variant:11} chunks: {len(rows):6}  median: {toks[len(toks) // 2]:4}  "
            f"p90: {toks[int(len(toks) * 0.9)]:4}  over {HARD_LIMIT}: {over:3}  "
            f"paras/chunk: {paras_per:.1f}"
        )


if __name__ == "__main__":
    main()
