"""Build a judgement pool from every retrieval variant.

Hand-authored relevance lists are incomplete: this corpus restates the same facts across
review papers, so a paragraph absent from the list can still answer the question, and
recall measured against that list is biased low. The fix is the one TREC has used for
decades — retrieve deeply with every system under comparison, take the union, judge that
pool, and treat the judged pool as ground truth.

Retrieval depth here is larger than serving depth on purpose. A pool built at the depth
the system actually serves would only ever confirm what the system already returns.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from api.retrieve import search

ROOT = Path(__file__).resolve().parent.parent
QUICK_SET = ROOT / "eval" / "quick_set.json"
PARA_PATH = ROOT / "data" / "paragraphs.jsonl"
OUT = ROOT / "data" / "pool.jsonl"

VARIANTS = ("fixed", "section", "contextual")


def load_paragraphs() -> dict[str, dict]:
    return {r["para_id"]: r for r in (json.loads(line) for line in PARA_PATH.open())}


def main() -> None:
    ap = argparse.ArgumentParser(description="Pool retrieval results for judging.")
    ap.add_argument("--depth", type=int, default=40, help="paragraphs contributed per variant")
    args = ap.parse_args()

    paragraphs = load_paragraphs()
    items = json.loads(QUICK_SET.read_text())

    rows = []
    for item in items:
        # found_by maps a paragraph to the variants that surfaced it, which is the
        # per-variant recall signal once the pool is judged.
        found_by: dict[str, set[str]] = defaultdict(set)
        best_rank: dict[str, int] = {}

        for variant in VARIANTS:
            # Depth counted in paragraphs, not chunks. The fixed variant carries 3.7
            # paragraphs per chunk against 1.5 for section, so an equal chunk depth lets
            # it flood the pool with its own candidates and inflates its measured recall.
            hits = search(item["question"], variant, args.depth * 4)
            seen_here: set[str] = set()
            for rank, hit in enumerate(hits, start=1):
                for pid in hit["para_ids"]:
                    if pid not in seen_here:
                        seen_here.add(pid)
                        found_by[pid].add(variant)
                        best_rank[pid] = min(best_rank.get(pid, 999), rank)
                if len(seen_here) >= args.depth:
                    break

        gold = set(item["relevant_para_ids"])
        for pid in sorted(found_by, key=lambda p: best_rank[p]):
            para = paragraphs.get(pid)
            if para is None:
                continue
            rows.append(
                {
                    "question_id": item["id"],
                    "question": item["question"],
                    "para_id": pid,
                    "section": para["section"],
                    "kind": para["kind"],
                    "text": para["text"],
                    "found_by": sorted(found_by[pid]),
                    "best_rank": best_rank[pid],
                    "known_gold": pid in gold,
                    "label": None,  # filled by judging
                }
            )

        missed = gold - set(found_by)
        if missed:
            print(f"{item['id']}: gold paragraphs no variant reached: {sorted(missed)}")

    with OUT.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    per_q = defaultdict(int)
    for r in rows:
        per_q[r["question_id"]] += 1
    print(
        f"\npooled {len(rows)} paragraphs across {len(per_q)} questions "
        f"(mean {len(rows) / len(per_q):.0f} per question)"
    )


if __name__ == "__main__":
    main()
