"""Test whether the differences between retrieval variants are real or sampling noise.

Every variant is run on the same questions, so the comparison is paired: what matters is
the per-question difference, not the gap between two averages. Pairing removes the
variance that comes from some questions simply being harder than others, which is the
dominant source of spread in a set this small.

Two tests, chosen to match the measurement:

  paired bootstrap  for continuous metrics (recall, precision, MRR). Resamples questions
                    with replacement and reports where the mean difference lands. Makes
                    no assumption about the shape of the distribution, which matters when
                    recall is near-binary and nothing like a normal.

  McNemar exact     for success, which is binary per question. Only the questions where
                    the two variants disagree carry information; the ones both get right
                    or both get wrong say nothing about which is better.

A confidence interval spanning zero does not mean the variants are equivalent. It means
this many questions cannot tell them apart, which is a statement about the gold set.
"""

from __future__ import annotations

import argparse
import random
from itertools import combinations
from math import comb

from eval.score_retrieval import (
    METRICS,
    VARIANTS,
    load_config,
    load_relevance,
    mean,
    score_variant,
)


def paired_bootstrap(
    a: list[float], b: list[float], iterations: int, rng: random.Random
) -> tuple[float, float, float, float]:
    """Return observed difference, 95% interval, and a two-sided p-value."""
    n = len(a)
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    observed = mean(diffs)

    resampled = []
    for _ in range(iterations):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        resampled.append(mean(sample))
    resampled.sort()

    lo = resampled[int(0.025 * iterations)]
    hi = resampled[int(0.975 * iterations)]

    # Two-sided: how often does the resampled difference land on the far side of zero?
    below = sum(1 for d in resampled if d <= 0) / iterations
    above = sum(1 for d in resampled if d >= 0) / iterations
    p = min(1.0, 2 * min(below, above))
    return observed, lo, hi, p


def mcnemar_exact(a: list[float], b: list[float]) -> tuple[int, int, float]:
    """Exact binomial test over the questions where the two variants disagree."""
    a_only = sum(1 for x, y in zip(a, b, strict=True) if x > y)
    b_only = sum(1 for x, y in zip(a, b, strict=True) if y > x)
    n = a_only + b_only
    if n == 0:
        return 0, 0, 1.0

    k = min(a_only, b_only)
    tail = sum(comb(n, i) for i in range(k + 1)) / 2**n
    return a_only, b_only, min(1.0, 2 * tail)


def main() -> None:
    ap = argparse.ArgumentParser(description="Paired significance tests between variants.")
    ap.add_argument("--source", choices=["judged", "hand"], default="hand")
    ap.add_argument("--include-partial", action="store_true")
    ap.add_argument("--iterations", type=int, default=10000)
    ap.add_argument("--depth", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    budget = load_config()["retrieval"]["context_token_budget"]
    items, relevant = load_relevance(args.source, args.include_partial)
    answerable = [i for i in items if i["type"] != "unanswerable"]

    print(f"{len(answerable)} paired questions, {args.iterations} bootstrap resamples\n")

    scores = {v: score_variant(answerable, relevant, v, budget, args.depth) for v in VARIANTS}

    for left, right in combinations(VARIANTS, 2):
        print(f"{left} vs {right}")
        for metric in METRICS:
            a, b = scores[left][metric], scores[right][metric]
            if metric == "success":
                a_only, b_only, p = mcnemar_exact(a, b)
                verdict = "yes" if p < 0.05 else "no"
                print(
                    f"  {metric:10} {mean(a):.3f} vs {mean(b):.3f}  "
                    f"disagreements {a_only}-{b_only}  p={p:.3f}  significant: {verdict}"
                )
            else:
                obs, lo, hi, p = paired_bootstrap(a, b, args.iterations, rng)
                verdict = "yes" if lo > 0 or hi < 0 else "no"
                print(
                    f"  {metric:10} {mean(a):.3f} vs {mean(b):.3f}  "
                    f"diff {obs:+.3f} [{lo:+.3f}, {hi:+.3f}]  p={p:.3f}  "
                    f"significant: {verdict}"
                )
        print()


if __name__ == "__main__":
    main()
