"""Find corpus paragraphs matching several terms at once, for gold-set authoring.

Reads paragraphs.jsonl rather than any chunk file on purpose. Gold-set ground truth is
anchored to paragraph ids, and questions must be written from what the corpus says, not
from what the retriever happens to surface — authoring from retrieval output would make
context recall measure the retriever against its own preferences.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARA_PATH = ROOT / "data" / "paragraphs.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser(description="Search corpus paragraphs by co-occurring terms.")
    ap.add_argument("terms", nargs="+", help="all terms must appear in the paragraph")
    ap.add_argument("--section", help="restrict to one section label")
    ap.add_argument("-n", type=int, default=6, help="how many to print")
    ap.add_argument("--chars", type=int, default=600)
    args = ap.parse_args()

    pats = [re.compile(t, re.I) for t in args.terms]
    rows = (json.loads(line) for line in PARA_PATH.open())

    shown = 0
    for r in rows:
        if args.section and r["section"] != args.section:
            continue
        if not all(p.search(r["text"]) for p in pats):
            continue
        print(f"\n--- {r['para_id']}  [{r['section']} / {r['section_title']}]  {r['kind']}")
        print(r["text"][: args.chars].strip())
        shown += 1
        if shown >= args.n:
            break
    print(f"\n{shown} shown")


if __name__ == "__main__":
    main()
