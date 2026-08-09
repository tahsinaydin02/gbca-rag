"""Measure how much truncating passages changed the judgements.

Passages were cut to 500 characters to fit the judge's daily token budget. 63% of the
pool is longer than that, and one hand-verified relevant paragraph was labelled NOT with
the answering sentence cut mid-way. If truncation flips labels at any meaningful rate,
every recall figure in this repo is measured with a corrupted ruler.

Sampling rather than re-judging everything: the question is the flip rate, and a hundred
passages estimate it well enough to decide whether a full re-run is worth a day of quota.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from groq import Groq

from eval.judge_pool import INSTRUCTIONS, parse_labels

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "judgements.json"
POOL = ROOT / "data" / "pool.jsonl"
OUT = ROOT / "data" / "truncation_recheck.json"


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-judge truncated passages at full length.")
    ap.add_argument("--sample", type=int, default=100)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--sleep", type=float, default=25)
    ap.add_argument("--chars", type=int, default=2000)
    args = ap.parse_args()

    load_dotenv()
    cfg = yaml.safe_load((ROOT / "configs" / "default.yaml").read_text())
    model = cfg["eval_llm"]["model"]
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    cache = json.loads(CACHE.read_text())
    rows = [json.loads(line) for line in POOL.open()]
    candidates = [
        r
        for r in rows
        if len(r["text"]) > 500 and cache.get(f"{r['question_id']}|{r['para_id']}") == "NOT"
    ]
    random.seed(0)
    sample = random.sample(candidates, min(args.sample, len(candidates)))
    sample.sort(key=lambda r: r["question_id"])
    print(f"{len(candidates)} truncated-and-NOT passages, re-judging {len(sample)}")

    flips, results = [], []
    for start in range(0, len(sample), args.batch_size):
        batch = sample[start : start + args.batch_size]
        passages = "\n\n".join(
            f"[{i}] (section: {p['section']}, {p['kind']})\n{p['text'][: args.chars]}"
            for i, p in enumerate(batch)
        )
        prompt = f"{INSTRUCTIONS}\n\nQuestion: {batch[0]['question']}\n\nPassages:\n\n{passages}"

        resp = client.chat.completions.create(
            model=model,
            temperature=0.0,
            max_tokens=2048,
            reasoning_effort="low",
            messages=[{"role": "user", "content": prompt}],
        )
        msg = resp.choices[0].message
        labels = parse_labels(msg.content or getattr(msg, "reasoning", None), len(batch))

        for i, p in enumerate(batch):
            new = labels[i]
            results.append(
                {
                    "question_id": p["question_id"],
                    "para_id": p["para_id"],
                    "old": "NOT",
                    "new": new,
                    "chars": len(p["text"]),
                }
            )
            if new != "NOT":
                flips.append((p["question_id"], p["para_id"], new))
        print(f"  {start + len(batch)}/{len(sample)}")
        time.sleep(args.sleep)

    OUT.write_text(json.dumps(results, indent=1))
    rate = len(flips) / len(sample)
    print(f"\nflipped: {len(flips)}/{len(sample)} = {rate:.1%}")
    for qid, pid, new in flips:
        print(f"  {qid} {pid} -> {new}")


if __name__ == "__main__":
    main()
