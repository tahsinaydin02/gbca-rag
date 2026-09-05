"""Measure the answering side: does the model stay inside the passages it was given.

Retrieval scoring says whether the information reached the model. This says what the model
did with it. Three things are measured, and only one of them needs a language model:

  citation validity  free, computed in code. Every [PMCID] in the answer either appears in
                     the context that was actually sent or it does not. A citation to an
                     article the model never saw is the cheapest possible hallucination to
                     detect, and detecting it costs nothing.

  abstention         free. Unanswerable questions should be refused; answerable ones with
                     usable context should not. Both directions are errors and they are
                     reported separately, because a system that refuses everything scores
                     perfectly on hallucination and is useless.

  faithfulness       judged. Claims in the answer are checked against the passages the
                     answer was built from. Scored per claim rather than per answer: a
                     four-sentence reply with one invented number is not half right.

The judge is the same model family used for relevance judging, and a different family from
the generator, so it is not grading its own homework.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from functools import partial
from pathlib import Path

import yaml
from dotenv import load_dotenv
from groq import Groq, RateLimitError

from api.ask import ask, build_context, load_config, select_hits

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "eval" / "quick_set.json"
OUT = ROOT / "data" / "generation_scores.json"

REFUSAL = "NOT ANSWERABLE FROM THE PROVIDED PASSAGES"
PMCID = re.compile(r"PMC\d+")

JUDGE_PROMPT = """You are checking whether an answer stays within its sources.

Read the passages, then the answer. Break the answer into its individual factual claims —
a claim is one assertion that could be true or false on its own. Ignore hedging, framing
and restatements of the question.

For each claim decide whether the passages support it. A number that does not appear in
the passages is unsupported. An abbreviation expanded into something the passages never
say is unsupported. A claim that is true in the world but absent from the passages is
still unsupported.

Answer in exactly this format and nothing else:

TOTAL: <number of claims>
UNSUPPORTED: <number of claims the passages do not support>
DETAIL: <one short line per unsupported claim, or "none">"""


def with_backoff(call, attempts: int = 6):
    """Retry through rate limits instead of losing the run to them.

    The free tier's daily token cap is a rolling window, so waiting is usually enough.
    Without this, one 429 partway through discards nothing already saved but does stop the
    run, and restarting costs another round of quota to reach the same point.
    """
    for attempt in range(attempts):
        try:
            return call()
        except RateLimitError:
            wait = 60 * (attempt + 1)
            print(f"    rate limited, waiting {wait}s")
            time.sleep(wait)
    raise RuntimeError("still rate limited after several waits")


def judge_faithfulness(client, model: str, context: str, answer: str) -> tuple[int, int, str]:
    prompt = f"{JUDGE_PROMPT}\n\nPassages:\n\n{context}\n\nAnswer:\n\n{answer}"
    for attempt in range(4):
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0.0,
                max_tokens=800,
                reasoning_effort="low",
                messages=[{"role": "user", "content": prompt}],
            )
            msg = resp.choices[0].message
            text = msg.content or getattr(msg, "reasoning", "") or ""
            total = int(re.search(r"TOTAL:\s*(\d+)", text).group(1))
            unsupported = int(re.search(r"UNSUPPORTED:\s*(\d+)", text).group(1))
            detail = re.search(r"DETAIL:\s*(.*)", text, re.S)
            return total, unsupported, (detail.group(1).strip() if detail else "")
        except RateLimitError:
            raise  # handled by with_backoff, which waits in minutes rather than seconds
        except Exception as exc:
            wait = 15 * (attempt + 1)
            print(f"    retry in {wait}s ({type(exc).__name__})")
            time.sleep(wait)
    raise RuntimeError("faithfulness judge failed")


def main() -> None:
    ap = argparse.ArgumentParser(description="Score the answering side.")
    ap.add_argument("--variant", default="section")
    ap.add_argument("--sleep", type=float, default=12, help="seconds between judge calls")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    load_dotenv()
    cfg = load_config()
    cfg["retrieval"]["variant"] = args.variant
    judge_model = yaml.safe_load((ROOT / "configs" / "default.yaml").read_text())["eval_llm"][
        "model"
    ]
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    items = json.loads(GOLD.read_text())[: args.limit]
    saved = json.loads(OUT.read_text()) if OUT.exists() else {}

    for item in items:
        qid = item["id"]
        if qid in saved:
            continue

        hits = select_hits(item["question"], cfg)
        context = build_context(hits)
        out = with_backoff(partial(ask, item["question"], cfg))
        answer = out["answer"].strip()
        abstained = REFUSAL in answer.upper()

        # Free check: did it cite anything it was not shown?
        shown = {h["pmcid"] for h in hits}
        cited = set(PMCID.findall(answer))
        invented = sorted(cited - shown)

        record = {
            "type": item["type"],
            "question": item["question"],
            "answer": answer,
            "abstained": abstained,
            "cited": sorted(cited),
            "invented_citations": invented,
            "context_pmcids": sorted(shown),
            "latency_s": out["latency_s"],
            "prompt_tokens": out["prompt_tokens"],
            "completion_tokens": out["completion_tokens"],
        }

        if not abstained:
            total, unsupported, detail = with_backoff(
                partial(judge_faithfulness, client, judge_model, context, answer)
            )
            record |= {"claims": total, "unsupported": unsupported, "detail": detail}
            time.sleep(args.sleep)

        saved[qid] = record
        OUT.write_text(json.dumps(saved, indent=1))
        flag = "REFUSED" if abstained else f"{record['unsupported']}/{record['claims']} unsupported"
        print(
            f"  {qid:4} {item['type']:13} {flag}" + (f"  invented {invented}" if invented else "")
        )

    report(saved)


def report(saved: dict) -> None:
    answerable = {k: v for k, v in saved.items() if v["type"] != "unanswerable"}
    unanswerable = {k: v for k, v in saved.items() if v["type"] == "unanswerable"}

    print(f"\n{len(saved)} questions scored\n")

    if unanswerable:
        refused = sum(1 for v in unanswerable.values() if v["abstained"])
        print(f"unanswerable refused:        {refused}/{len(unanswerable)}")
    if answerable:
        wrongly = sum(1 for v in answerable.values() if v["abstained"])
        print(
            f"answerable refused:          {wrongly}/{len(answerable)}  "
            f"(a system that refuses everything is not faithful, it is silent)"
        )

    answered = [v for v in answerable.values() if not v["abstained"]]
    if answered:
        claims = sum(v["claims"] for v in answered)
        bad = sum(v["unsupported"] for v in answered)
        clean = sum(1 for v in answered if v["unsupported"] == 0)
        print(f"claim-level faithfulness:    {1 - bad / claims:.3f}  ({bad} of {claims} claims)")
        print(f"answers with zero unsupported: {clean}/{len(answered)}")

    invented = [k for k, v in saved.items() if v["invented_citations"]]
    print(
        f"answers citing an unseen PMCID: {len(invented)}" + (f"  {invented}" if invented else "")
    )

    by_type = Counter(v["type"] for v in saved.values() if v.get("unsupported"))
    if by_type:
        print(f"\nunsupported claims by question type: {dict(by_type)}")


if __name__ == "__main__":
    main()
