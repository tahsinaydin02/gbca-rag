"""Check the gold set for mistakes that stay invisible until they corrupt a score.

A typo in a relevant_para_id silently drops that question's recall to zero and nothing
reports it. An unanswerable item that quietly acquires a gold paragraph stops testing
abstention. Both are cheap to catch here and expensive to notice later.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TYPES = {"factual", "multi_hop", "numeric", "unanswerable", "case"}


def main() -> None:
    items = json.loads((ROOT / "eval" / "quick_set.json").read_text())
    known = {json.loads(line)["para_id"] for line in (ROOT / "data" / "paragraphs.jsonl").open()}

    problems = []
    seen_ids, seen_questions = set(), set()

    for item in items:
        qid = item["id"]
        if qid in seen_ids:
            problems.append(f"{qid}: duplicate id")
        seen_ids.add(qid)

        q = item["question"].strip().lower()
        if q in seen_questions:
            problems.append(f"{qid}: duplicate question text")
        seen_questions.add(q)

        if item["type"] not in TYPES:
            problems.append(f"{qid}: unknown type {item['type']!r}")

        for pid in item["relevant_para_ids"]:
            if pid not in known:
                problems.append(f"{qid}: unknown paragraph {pid}")

        if item["type"] == "unanswerable" and item["relevant_para_ids"]:
            problems.append(f"{qid}: unanswerable but has gold paragraphs")
        if item["type"] != "unanswerable" and not item["relevant_para_ids"]:
            problems.append(f"{qid}: answerable but no gold paragraphs")

    counts = Counter(i["type"] for i in items)
    total = len(items)
    print(f"{total} questions")
    for t, n in counts.most_common():
        print(f"  {t:14} {n:3}  ({n / total:.0%})")

    print(f"\n{len(problems)} problems")
    for p in problems:
        print(f"  {p}")


if __name__ == "__main__":
    main()
