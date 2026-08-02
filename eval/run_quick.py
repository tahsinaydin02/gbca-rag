"""Run the quick set and write a readable review file.

No scoring here on purpose. Week 2 introduces RAGAS; today the point is to read ten
answers next to their sources and build the judgement that writing the full gold set
will need. The one automatic signal is whether retrieval fetched any gold paragraph —
cheap to compute, and it separates "the retriever never found it" from "the retriever
found it and the model still got it wrong", which are different problems.
"""

from __future__ import annotations

import json
from pathlib import Path

from api.ask import ask, load_config, select_hits

ROOT = Path(__file__).resolve().parent.parent
QUICK_SET = ROOT / "eval" / "quick_set.json"
OUT = ROOT / "notes" / "quick_review.md"


def main() -> None:
    cfg = load_config()
    items = json.loads(QUICK_SET.read_text())
    lines = [f"# Quick set review — {cfg['retrieval']['variant']} chunks, {cfg['llm']['model']}\n"]

    hits_found = 0
    for item in items:
        hits = select_hits(item["question"], cfg)
        got = {pid for h in hits for pid in h["para_ids"]}
        gold = set(item["relevant_para_ids"])
        overlap = sorted(gold & got)
        if gold:
            hits_found += bool(overlap)

        out = ask(item["question"], cfg)

        lines += [
            f"\n## {item['id']} ({item['type']})",
            f"\n**Q:** {item['question']}",
            f"\n**Expected:** {item['ground_truth']}",
            f"\n**Gold paragraphs:** {sorted(gold) or '— none, should abstain'}",
            f"\n**Retrieved gold:** {overlap or 'NONE'}",
            f"\n**Retrieved from:** {sorted({h['pmcid'] for h in hits})}",
            f"\n**Answer:**\n\n{out['answer']}",
            f"\n`{out['n_chunks']} chunks, {out['context_tokens']} ctx tokens, "
            f"{out['latency_s']}s`\n",
        ]

    answerable = [i for i in items if i["relevant_para_ids"]]
    lines.insert(
        1, f"\nGold paragraph retrieved for {hits_found}/{len(answerable)} answerable questions.\n"
    )
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}  ({hits_found}/{len(answerable)} gold-hit)")


if __name__ == "__main__":
    main()
