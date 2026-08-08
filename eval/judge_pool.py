"""Label the retrieval pool for relevance, so recall has a complete ruler.

The pool holds every paragraph any variant surfaced at depth 50. Judging it turns a
hand-written relevance list — which this corpus makes incomplete, since review papers
restate the same facts — into something closer to full coverage.

The judge is a different model family from the generator. Its labels are cached by
question and paragraph, because quota is the binding constraint on the free tier and
nothing here should be paid for twice.

An LLM judge has its own biases, so this is not treated as ground truth on faith:
sample_agreement.py draws a sample for manual labelling and reports how often the two
agree. A recall number is only as trustworthy as the judgements under it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from dotenv import load_dotenv
from groq import Groq

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "data" / "pool.jsonl"
CACHE = ROOT / "data" / "judgements.json"
OUT = ROOT / "data" / "pool_judged.jsonl"

INSTRUCTIONS = """You are judging whether passages help answer a question.

For each passage assign exactly one label:

RELEVANT - the passage states information that directly answers the question, or a
           necessary part of it. A passage giving one of two facts a multi-part question
           needs is RELEVANT.
PARTIAL  - the passage is about the right topic and gives useful background, but does
           not contain the answer.
NOT      - the passage does not help answer this question.

Judge only what the passage says. Do not use your own knowledge of the subject, and do
not reward a passage for merely repeating words from the question.

Return one line per passage, in the form:
0 NOT
1 RELEVANT
2 PARTIAL

Nothing else — no JSON, no explanation, one line for every passage you were given."""


def load_cache() -> dict[str, str]:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


LABEL_LINE = re.compile(r"^\s*(\d+)\s*[:.\-]?\s*(RELEVANT|PARTIAL|NOT)\s*$", re.M)


def parse_labels(text: str | None, expected: int) -> dict[int, str]:
    """Parse one 'id label' line per passage.

    Line-oriented output rather than JSON: the judge kept truncating JSON mid-array while
    reporting a normal stop, and a half-written array is unparseable. Half-written lines
    are not — every complete line is still usable, and a short count is detectable rather
    than silently becoming a wrong label.
    """
    if not text:
        raise ValueError("empty response")
    labels = {int(i): lab for i, lab in LABEL_LINE.findall(text)}
    if len(labels) < expected:
        raise ValueError(f"got {len(labels)} labels for {expected} passages: {text[:200]!r}")
    return labels


def judge_batch(client, model: str, question: str, batch: list[dict]) -> dict[int, str]:
    passages = "\n\n".join(
        f"[{i}] (section: {p['section']}, {p['kind']})\n{p['text'][:600]}"
        for i, p in enumerate(batch)
    )
    prompt = f"{INSTRUCTIONS}\n\nQuestion: {question}\n\nPassages:\n\n{passages}"

    for attempt in range(5):
        resp = None
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0.0,
                max_tokens=2048,
                reasoning_effort="low",
                messages=[{"role": "user", "content": prompt}],
            )
            msg = resp.choices[0].message
            return parse_labels(msg.content or getattr(msg, "reasoning", None), len(batch))
        except Exception as exc:
            detail = f" raw={str(resp.choices[0].message.content)[:160]!r}" if resp else ""
            wait = 10 * (attempt + 1)
            print(f"    retry in {wait}s ({type(exc).__name__}: {exc}){detail}")
            time.sleep(wait)
    raise RuntimeError("judge failed after 5 attempts")


def main() -> None:
    ap = argparse.ArgumentParser(description="Judge the retrieval pool.")
    ap.add_argument("--batch-size", type=int, default=12)
    ap.add_argument("--sleep", type=float, default=6.5, help="seconds between calls")
    ap.add_argument("--limit-questions", type=int, help="judge only the first N questions")
    args = ap.parse_args()

    load_dotenv()
    cfg = yaml.safe_load((ROOT / "configs" / "default.yaml").read_text())
    model = cfg["eval_llm"]["model"]
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    rows = [json.loads(line) for line in POOL.open()]
    by_q: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_q[r["question_id"]].append(r)

    cache = load_cache()
    questions = list(by_q)[: args.limit_questions] if args.limit_questions else list(by_q)
    todo = sum(1 for q in questions for r in by_q[q] if f"{q}|{r['para_id']}" not in cache)
    print(f"{len(rows)} pooled, {todo} unjudged, model={model}")

    calls = 0
    for qid in questions:
        pending = [r for r in by_q[qid] if f"{qid}|{r['para_id']}" not in cache]
        if not pending:
            continue
        question = by_q[qid][0]["question"]
        for start in range(0, len(pending), args.batch_size):
            batch = pending[start : start + args.batch_size]
            labels = judge_batch(client, model, question, batch)
            for i, p in enumerate(batch):
                cache[f"{qid}|{p['para_id']}"] = labels.get(i, "NOT")
            calls += 1
            CACHE.write_text(json.dumps(cache, indent=0))
            print(f"  {qid}: {start + len(batch)}/{len(pending)}  (call {calls})")
            time.sleep(args.sleep)

    with OUT.open("w") as fh:
        for r in rows:
            r["label"] = cache.get(f"{r['question_id']}|{r['para_id']}")
            fh.write(json.dumps(r) + "\n")

    counts = Counter(r["label"] for r in rows)
    print(f"\nlabels: {dict(counts)}")
    for qid in by_q:
        rel = sum(1 for r in by_q[qid] if cache.get(f"{qid}|{r['para_id']}") == "RELEVANT")
        print(f"  {qid}: {rel} relevant of {len(by_q[qid])} pooled")


if __name__ == "__main__":
    main()
