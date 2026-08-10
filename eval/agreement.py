"""Measure how far the automatic judge is from a human on the same passages.

Every recall figure in this project rests on labels produced by a language model. That
makes the judge a measuring instrument, and an unvalidated instrument is a guess with
decimal places. This script draws a sample, asks for human labels on the same passages,
and reports where the two disagree.

The sample is stratified by the judge's own label rather than drawn at random. A random
sample of this pool would be about 95% NOT, agreement would come out near 0.95, and the
number would mean nothing — the interesting question is conditional. When the judge says
RELEVANT, is it? And more importantly, when it says NOT, is it missing something? Those
two errors do opposite things to a recall figure: false RELEVANT inflates the denominator,
false NOT hides relevant material from the measurement entirely.

Labels are saved as they are entered, so the session can be interrupted.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "data" / "pool.jsonl"
CACHE = ROOT / "data" / "judgements.json"
HUMAN = ROOT / "data" / "human_labels.json"

LABELS = {"r": "RELEVANT", "p": "PARTIAL", "n": "NOT"}
GUIDE = """
  RELEVANT - states information that directly answers the question, or a necessary part
  PARTIAL  - right topic, useful background, does not contain the answer
  NOT      - does not help answer this question
"""


def sample_pool(per_label: int, seed: int) -> list[dict]:
    cache = json.loads(CACHE.read_text())
    rows = [json.loads(line) for line in POOL.open()]

    by_label: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        label = cache.get(f"{row['question_id']}|{row['para_id']}")
        if label:
            row["judge"] = label
            by_label[label].append(row)

    rng = random.Random(seed)
    sample = []
    for label in ("RELEVANT", "PARTIAL", "NOT"):
        pool = by_label.get(label, [])
        sample += rng.sample(pool, min(per_label, len(pool)))
    rng.shuffle(sample)  # so the judge's label is not guessable from position
    return sample


def report(human: dict[str, str], sample: list[dict]) -> None:
    labelled = [r for r in sample if f"{r['question_id']}|{r['para_id']}" in human]
    if not labelled:
        print("nothing labelled yet")
        return

    matrix: Counter = Counter()
    for row in labelled:
        mine = human[f"{row['question_id']}|{row['para_id']}"]
        matrix[(row["judge"], mine)] += 1

    print(f"\n{len(labelled)} passages labelled by both\n")
    print("judge \\ human   RELEVANT  PARTIAL   NOT   agreement")
    for judge_label in ("RELEVANT", "PARTIAL", "NOT"):
        row_total = sum(v for (j, _), v in matrix.items() if j == judge_label)
        if not row_total:
            continue
        cells = "".join(f"{matrix[(judge_label, h)]:>9}" for h in ("RELEVANT", "PARTIAL", "NOT"))
        agree = matrix[(judge_label, judge_label)] / row_total
        print(f"{judge_label:14}{cells}      {agree:.2f}")

    exact = sum(v for (j, h), v in matrix.items() if j == h) / len(labelled)
    print(f"\nexact agreement on the stratified sample: {exact:.2f}")

    # The costly direction: material the judge dismissed that a human counts as an answer.
    missed = matrix[("NOT", "RELEVANT")]
    not_total = sum(v for (j, _), v in matrix.items() if j == "NOT")
    if not_total:
        print(
            f"judged NOT but human says RELEVANT: {missed}/{not_total} "
            f"({missed / not_total:.0%}) — these are invisible to recall"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare judge labels with human labels.")
    ap.add_argument("--per-label", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--chars", type=int, default=1200)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    sample = sample_pool(args.per_label, args.seed)
    human = json.loads(HUMAN.read_text()) if HUMAN.exists() else {}

    if args.report_only:
        report(human, sample)
        return

    todo = [r for r in sample if f"{r['question_id']}|{r['para_id']}" not in human]
    print(f"{len(sample)} sampled, {len(todo)} left to label")
    print(GUIDE)
    print("r / p / n to label, s to skip, q to stop\n")

    for i, row in enumerate(todo, start=1):
        print("=" * 78)
        print(f"[{i}/{len(todo)}]  Q: {row['question']}")
        print(f"\n({row['section']}, {row['kind']})  {row['text'][: args.chars].strip()}\n")

        while True:
            choice = input("label [r/p/n/s/q]: ").strip().lower()
            if choice in LABELS:
                human[f"{row['question_id']}|{row['para_id']}"] = LABELS[choice]
                HUMAN.write_text(json.dumps(human, indent=1))
                break
            if choice in ("s", "q"):
                break
            print("  r, p, n, s or q")
        if choice == "q":
            break

    report(human, sample)


if __name__ == "__main__":
    main()
