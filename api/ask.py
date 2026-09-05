"""Answer a question strictly from retrieved passages.

The model is not a knowledge source here; it summarises the passages it is handed and
cites them. Any claim it makes that is not in the context is a failure, and Week 2
measures exactly that. Three properties are enforced by the prompt rather than by code,
because code cannot check them: grounding, citation, and abstention.

Every call appends a row to data/runs.jsonl with token counts and wall-clock latency.
That log is what the README's cost and latency columns are built from, so it starts on
day one rather than being retrofitted in week four.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from groq import BadRequestError, Groq

from api.retrieve import search

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "configs" / "default.yaml"
LOG_PATH = ROOT / "data" / "runs.jsonl"

SYSTEM_PROMPT = """You answer questions about gadolinium-based contrast agents using \
only the passages provided.

Rules:
1. Use only the passages. Do not add facts from your own knowledge, even if you are \
confident they are correct.
2. Cite the source of every factual claim inline as [PMCID], using the identifier shown \
above each passage.
3. If the passages do not contain enough information to answer, reply exactly: \
NOT ANSWERABLE FROM THE PROVIDED PASSAGES. Do not guess, and do not answer partially \
from memory.
4. If the passages disagree with each other, say so and cite both.
5. Numbers, thresholds and doses must be quoted exactly as they appear. Do not round, \
convert, or infer them.

Be concise. Three or four sentences is usually enough."""


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def build_context(hits: list[dict]) -> str:
    blocks = []
    for h in hits:
        header = f"[{h['pmcid']}] section: {h['section']}"
        blocks.append(f"{header}\n{h['text']}")
    return "\n\n---\n\n".join(blocks)


def select_hits(question: str, cfg: dict, section: str | None = None) -> list[dict]:
    """Fill a fixed token budget rather than a fixed k.

    The fixed variant averages ~460 tokens per chunk against ~270 for section, so a
    fixed top-k would hand one variant far more context than the other and confound the
    comparison. Holding the budget constant makes the variants answer the same question
    with the same amount of text.
    """
    r = cfg["retrieval"]
    hits = search(question, r["variant"], r["max_chunks"], section)
    chosen, used = [], 0
    for h in hits:
        if used + h["n_tokens"] > r["context_token_budget"] and chosen:
            break
        chosen.append(h)
        used += h["n_tokens"]
    return chosen


THINK_BLOCK = re.compile(r"<think>.*?(</think>|\Z)", re.S | re.I)


def strip_reasoning(text: str) -> str:
    """Remove the model's scratchpad from the answer.

    Reasoning models emit a <think> block inside the content. Left in, it is treated as
    part of the answer by everything downstream: the faithfulness judge grades the
    model's deliberation rather than its conclusion, the citation check flags half-written
    identifiers the model was still assembling, and a refusal considered and rejected mid
    thought reads as a refusal. The scratchpad is not the answer and does not belong in
    anything measured.
    """
    return THINK_BLOCK.sub("", text).strip()


def ask(question: str, cfg: dict, section: str | None = None) -> dict:
    load_dotenv()
    hits = select_hits(question, cfg, section)
    context = build_context(hits)

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Passages:\n\n{context}\n\nQuestion: {question}"},
    ]
    # Reasoning is switched off rather than hidden. A reasoning model spent its entire
    # 700-token budget deliberating and emitted no answer at all — the completion was all
    # scratchpad, truncated mid-thought. Summarising passages that are already in front of
    # you is not a task that needs deliberation, and paying for it twice (once in tokens,
    # once in a truncated answer) buys nothing here.
    extra = {"reasoning_effort": cfg["llm"].get("reasoning_effort")}
    extra = {k: v for k, v in extra.items() if v}

    started = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=cfg["llm"]["model"],
            temperature=cfg["llm"]["temperature"],
            max_tokens=cfg["llm"]["max_tokens"],
            messages=messages,
            **extra,
        )
    except BadRequestError:
        # Only a rejected parameter is worth retrying without it. Catching everything here
        # meant a rate-limit error triggered a second identical call, spending quota twice
        # to fail twice.
        resp = client.chat.completions.create(
            model=cfg["llm"]["model"],
            temperature=cfg["llm"]["temperature"],
            max_tokens=cfg["llm"]["max_tokens"],
            messages=messages,
        )
    latency = time.perf_counter() - started

    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "question": question,
        "variant": cfg["retrieval"]["variant"],
        "section_filter": section,
        "model": cfg["llm"]["model"],
        "n_chunks": len(hits),
        "context_tokens": sum(h["n_tokens"] for h in hits),
        "chunk_ids": [h["chunk_id"] for h in hits],
        "para_ids": [pid for h in hits for pid in h["para_ids"]],
        "prompt_tokens": resp.usage.prompt_tokens,
        "completion_tokens": resp.usage.completion_tokens,
        "latency_s": round(latency, 3),
        "answer": strip_reasoning(resp.choices[0].message.content or ""),
    }
    with LOG_PATH.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def main() -> None:
    ap = argparse.ArgumentParser(description="Ask a question against the indexed corpus.")
    ap.add_argument("question")
    ap.add_argument("--variant")
    ap.add_argument("--section")
    ap.add_argument("--show-context", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if args.variant:
        cfg["retrieval"]["variant"] = args.variant

    out = ask(args.question, cfg, args.section)

    if args.show_context:
        for h in select_hits(args.question, cfg, args.section):
            print(f"--- [{h['pmcid']}] {h['section']} ({h['n_tokens']} tok, {h['score']:.3f})")
            print(h["text"][:400], "\n")

    print(out["answer"])
    print(
        f"\n{out['n_chunks']} chunks / {out['context_tokens']} ctx tokens | "
        f"{out['prompt_tokens']}+{out['completion_tokens']} tokens | {out['latency_s']}s"
    )


if __name__ == "__main__":
    main()
