"""Score the three retrieval variants against the judged pool.

Reads judgements straight from the cache rather than a finished pool file, so a run
interrupted by quota still produces numbers for everything judged so far.

Recall is computed over paragraphs, precision over chunks. That asymmetry is deliberate:
recall asks whether the information reached the model, which is a property of paragraphs;
precision asks how much of the context window was earned, which is a property of the
chunks actually pasted into the prompt.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from api.retrieve import search

ROOT = Path(__file__).resolve().parent.parent
QUICK_SET = ROOT / "eval" / "quick_set.json"
CACHE = ROOT / "data" / "judgements.json"

VARIANTS = ("fixed", "section", "contextual")


def main() -> None:
    ap = argparse.ArgumentParser(description="Score retrieval variants.")
    ap.add_argument("--ks", type=int, nargs="+", default=[5, 10, 20])
    ap.add_argument(
        "--include-partial", action="store_true", help="count PARTIAL passages as relevant"
    )
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "configs" / "default.yaml").read_text())
    budget = cfg["retrieval"]["context_token_budget"]
    cache = json.loads(CACHE.read_text())
    items = json.loads(QUICK_SET.read_text())

    accept = {"RELEVANT", "PARTIAL"} if args.include_partial else {"RELEVANT"}
    relevant: dict[str, set[str]] = {}
    for item in items:
        qid = item["id"]
        rel = {
            k.split("|", 1)[1] for k, v in cache.items() if k.startswith(f"{qid}|") and v in accept
        }
        relevant[qid] = rel

    answerable = [i for i in items if relevant[i["id"]]]
    print(
        f"scoring {len(answerable)} questions with judged relevant paragraphs "
        f"(accepting {sorted(accept)})\n"
    )
    for i in answerable:
        print(f"  {i['id']}: {len(relevant[i['id']])} relevant paragraphs")

    header = (
        "variant      "
        + "".join(f"  R@{k:<5}" for k in args.ks)
        + "  R@budget  P@budget  S@budget   MRR  chunks"
    )
    print(f"\n{header}")

    for variant in VARIANTS:
        recalls = {k: [] for k in args.ks}
        success, mrr = [], []
        budget_recall, budget_prec, budget_chunks = [], [], []

        for item in answerable:
            qid, rel = item["id"], relevant[item["id"]]
            hits = search(item["question"], variant, max(args.ks))

            for k in args.ks:
                got = {p for h in hits[:k] for p in h["para_ids"]}
                recalls[k].append(len(rel & got) / len(rel))

            # Operational setting: fill the same token budget the service uses.
            chosen, used = [], 0
            for hit in hits:
                if used + hit["n_tokens"] > budget and chosen:
                    break
                chosen.append(hit)
                used += hit["n_tokens"]
            got = {p for h in chosen for p in h["para_ids"]}
            budget_recall.append(len(rel & got) / len(rel))
            budget_prec.append(sum(1 for h in chosen if rel & set(h["para_ids"])) / len(chosen))
            budget_chunks.append(len(chosen))
            success.append(1.0 if rel & got else 0.0)
            rr = 0.0
            for rank, hit in enumerate(hits, start=1):
                if rel & set(hit["para_ids"]):
                    rr = 1 / rank
                    break
            mrr.append(rr)

        def mean(xs):
            return sum(xs) / len(xs)

        cells = "".join(f"  {mean(recalls[k]):.3f} " for k in args.ks)
        print(
            f"{variant:12}{cells}   {mean(budget_recall):.3f}     "
            f"{mean(budget_prec):.3f}     {mean(success):.3f}   {mean(mrr):.3f}  "
            f"{mean(budget_chunks):.1f}"
        )


if __name__ == "__main__":
    main()
