"""Check that the faithfulness judge can still tell a hallucination from a clean answer.

The judge scored 95 of 95 claims as supported. A perfect score is the point at which a
measurement stops distinguishing anything, and it is worth knowing which of the two
explanations applies: the answers were faithful, or the judge cannot see unfaithfulness.

Two fixtures, in opposite directions. One is a recorded hallucination — an answer that
expanded "cardiac MRI" into "cardiac mitral regurgitation" and cited the passage it had
just contradicted. The other is an answer known to stay inside its sources. A judge that
flags everything would pass the first test for the wrong reason, so both are needed.

This is the eval gate in miniature: cheap enough to run on every change, and it fails
loudly when the instrument drifts rather than when the system does.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from groq import Groq

from eval.score_generation import judge_faithfulness

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "eval" / "regression_cases.json"
PARAGRAPHS = ROOT / "data" / "paragraphs.jsonl"


def load_paragraphs() -> dict[str, dict]:
    return {r["para_id"]: r for r in (json.loads(line) for line in PARAGRAPHS.open())}


def main() -> None:
    load_dotenv()
    model = yaml.safe_load((ROOT / "configs" / "default.yaml").read_text())["eval_llm"]["model"]
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    paragraphs = load_paragraphs()
    cases = json.loads(CASES.read_text())
    failures = []

    for case in cases:
        blocks = []
        for pid in case["context_para_ids"]:
            para = paragraphs.get(pid)
            if para:
                blocks.append(f"[{para['pmcid']}] section: {para['section']}\n{para['text']}")
        context = "\n\n---\n\n".join(blocks)

        total, unsupported, detail = judge_faithfulness(client, model, context, case["answer"])

        floor = case.get("expect_unsupported_at_least")
        ceiling = case.get("expect_unsupported_at_most")
        ok = True
        if floor is not None and unsupported < floor:
            ok = False
        if ceiling is not None and unsupported > ceiling:
            ok = False

        print(f"{'PASS' if ok else 'FAIL'}  {case['id']:22} {unsupported}/{total} unsupported")
        if not ok:
            failures.append(case["id"])
            print(f"      expected at least {floor}, at most {ceiling}")
            print(f"      judge said: {detail[:200]}")

    if failures:
        print(f"\n{len(failures)} regression case(s) failed: {failures}")
        print("The faithfulness numbers in the README were produced by this judge.")
        sys.exit(1)
    print("\njudge still separates the two directions")


if __name__ == "__main__":
    main()
