"""Score the three retrieval variants against the judged pool or the hand-written lists.

Reads judgements straight from the cache rather than a finished pool file, so a run
interrupted by quota still produces numbers for everything judged so far.

Recall is computed over paragraphs, precision over context tokens. That asymmetry is
deliberate: recall asks whether the information reached the model, which is a property of
paragraphs; precision asks how much of the context window was earned, which is a property
of tokens. Counting precision per chunk instead would flatter large chunks, since a chunk
holding several paragraphs is likelier to contain a relevant one by size alone.

With one to four relevant paragraphs per question, recall is close to binary and mostly
noise. Success@budget and MRR are the honest metrics at this scale, and are reported
alongside.

Per-question scores are exposed through score_variant() rather than being averaged away
inside main(), because significance.py needs the paired vectors: the question of whether
two variants differ is not answerable from two means.
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
CONFIG = ROOT / "configs" / "default.yaml"

VARIANTS = ("fixed", "section", "contextual")
METRICS = ("recall", "precision", "success", "mrr")


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def load_relevance(source: str, include_partial: bool = False) -> tuple[list[dict], dict[str, set]]:
    """Return the gold set and, per question, the set of paragraphs counted as relevant."""
    items = json.loads(QUICK_SET.read_text())
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    accept = {"RELEVANT", "PARTIAL"} if include_partial else {"RELEVANT"}

    relevant: dict[str, set[str]] = {}
    for item in items:
        qid = item["id"]
        if source == "hand":
            # Incomplete by construction, but incomplete in the same way for every
            # variant, so it still ranks them while the pool is being judged.
            relevant[qid] = set(item["relevant_para_ids"])
        else:
            relevant[qid] = {
                key.split("|", 1)[1]
                for key, label in cache.items()
                if key.startswith(f"{qid}|") and label in accept
            }
    return items, relevant


def score_question(
    question: str, rel: set[str], variant: str, budget: int, depth: int
) -> dict[str, float]:
    """Score one question under one variant, in the operational token budget.

    A question with an empty relevant set scores zero rather than being skipped. Under
    judged relevance that case means no variant surfaced anything the judge accepted, so
    it is a failure all three share — dropping it would quietly remove the hardest
    questions from the average and flatter every variant equally.
    """
    if not rel:
        return {"recall": 0.0, "precision": 0.0, "success": 0.0, "mrr": 0.0, "chunks": 0.0}

    hits = search(question, variant, depth)

    chosen, used = [], 0
    for hit in hits:
        if used + hit["n_tokens"] > budget and chosen:
            break
        chosen.append(hit)
        used += hit["n_tokens"]

    got = {pid for hit in chosen for pid in hit["para_ids"]}

    rel_tokens = sum(
        hit["n_tokens"] * len(rel & set(hit["para_ids"])) / len(hit["para_ids"]) for hit in chosen
    )

    rr = 0.0
    for rank, hit in enumerate(hits, start=1):
        if rel & set(hit["para_ids"]):
            rr = 1 / rank
            break

    return {
        "recall": len(rel & got) / len(rel),
        "precision": rel_tokens / sum(hit["n_tokens"] for hit in chosen),
        "success": 1.0 if rel & got else 0.0,
        "mrr": rr,
        "chunks": float(len(chosen)),
    }


def score_variant(
    items: list[dict], relevant: dict[str, set], variant: str, budget: int, depth: int = 20
) -> dict[str, list[float]]:
    """Per-question scores for one variant, keyed by metric."""
    out: dict[str, list[float]] = {m: [] for m in (*METRICS, "chunks")}
    for item in items:
        scores = score_question(item["question"], relevant[item["id"]], variant, budget, depth)
        for metric, value in scores.items():
            out[metric].append(value)
    return out


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def main() -> None:
    ap = argparse.ArgumentParser(description="Score retrieval variants.")
    ap.add_argument(
        "--include-partial", action="store_true", help="count PARTIAL passages as relevant"
    )
    ap.add_argument(
        "--source",
        choices=["judged", "hand"],
        default="judged",
        help="relevance from the judged pool, or from hand-written lists",
    )
    ap.add_argument("--depth", type=int, default=20, help="chunks retrieved before budgeting")
    args = ap.parse_args()

    budget = load_config()["retrieval"]["context_token_budget"]
    items, relevant = load_relevance(args.source, args.include_partial)
    # Answerability comes from the gold set, not from whether retrieval happened to find
    # something. Selecting on the outcome would drop exactly the questions that failed.
    answerable = [i for i in items if i["type"] != "unanswerable"]

    label = (
        "hand-written lists"
        if args.source == "hand"
        else ("judged, RELEVANT+PARTIAL" if args.include_partial else "judged, RELEVANT only")
    )
    print(f"scoring {len(answerable)} of {len(items)} questions ({label})\n")
    print("variant       R@budget  P@budget  S@budget    MRR  chunks")

    for variant in VARIANTS:
        s = score_variant(answerable, relevant, variant, budget, args.depth)
        print(
            f"{variant:12}    {mean(s['recall']):.3f}     {mean(s['precision']):.3f}     "
            f"{mean(s['success']):.3f}  {mean(s['mrr']):.3f}    {mean(s['chunks']):.1f}"
        )


if __name__ == "__main__":
    main()
