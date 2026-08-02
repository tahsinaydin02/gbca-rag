# gbca-rag

Retrieval-augmented question answering over open-access literature on gadolinium-based
contrast agents. The point of the project is not that it answers questions — it is to
measure *where* grounded answering breaks, and to say so with numbers.

## What this is, and what it isn't

This is an HTTP-service-shaped system: a question goes in, an answer comes out with the
PMCIDs it rests on. The language model is not the knowledge source. It summarises
passages it was handed and cites them; any claim it makes that is not in those passages
counts as a failure, and measuring that rate is the actual deliverable.

It does not solve a clinical problem and should not be read as clinical guidance.

## Corpus

308 articles from the PMC Open Access Subset, restricted to CC0 and CC BY licences
(commercial use permitted), pulled from the `pmc-oa-opendata` S3 bucket.

The query is deliberately narrow. A plain full-text search for *gadolinium* returns
about 23,500 loosely related papers; the corpus is instead the union of five topic-scoped
queries (frozen in [`configs/corpus.yaml`](configs/corpus.yaml), with the resulting PMCID
list committed alongside it). Coherence matters more than size here: multi-hop and
unanswerable questions can only be written against a corpus whose boundaries are known.

After dropping 2 retracted articles and 2 with no full text, 304 articles yield 10,580
paragraphs — 10,361 prose, 219 tables.

## Pipeline

    eSearch -> S3 -> JATS XML -> paragraphs -> chunks -> Qdrant -> retrieve -> answer

**Parsing.** Section labels come from `<title>` text rather than the `sec-type`
attribute: 3,652 of roughly 4,300 sections carry no `sec-type`, and those that do are
inconsistent (`intro` vs `introduction`, `materials|methods`). Nested sections inherit
their top-level ancestor's label, so "Statistical analysis" is filterable as methods.
Back matter — competing interests, funding, data availability — is dropped outright.

Tables are kept and flattened rather than discarded. Dose and eGFR thresholds live in
them, and numeric questions are the ones most exposed to hallucination.

**Paragraph identity is independent of chunking.** Gold-set ground truth anchors to
paragraph ids, not chunk ids, because chunking is the experiment variable — one gold set
has to stay valid while chunk size and strategy change underneath it.

**Chunking**, three variants built by the same code path:

| Variant | Chunks | Median tokens | Grouping |
|---|---|---|---|
| `fixed` | 4,220 | 512 | 512-token sliding window, 10% overlap, ignores structure |
| `section` | 7,708 | 257 | consecutive paragraphs packed within one section |
| `contextual` | 8,265 | 273 | section packing plus article-title and section-name prefix |

**Embedding and retrieval.** `BAAI/bge-small-en-v1.5`, 384 dimensions, cosine over
normalised vectors, in Qdrant with payload indexes on section and article. Vectors are
cached by content hash, since re-chunking re-embeds most of the corpus.

Context selection fills a **fixed token budget** rather than a fixed *k*. The `fixed`
variant averages ~460 tokens per chunk against ~270 for `section`; a fixed top-k would
hand one variant nearly twice the context and confound the comparison.

## Running it

    uv sync
    cp .env.example .env     # Groq key for generation, Gemini key for evaluation
    make ingest              # fetch, parse, chunk  (~30 MB, a few minutes)
    make index               # start Qdrant, embed, load
    make ask Q="Which GBCAs did the ACR classify as Group I agents?"
    make quick               # ten-question set into notes/quick_review.md

## Where it stands

Week 1 of four. The pipeline runs end to end and answers questions with citations. A
ten-question dry run (`eval/quick_set.json`, written from corpus text rather than from
retriever output) puts the bottleneck squarely in retrieval: a hand-listed gold paragraph
was retrieved for 3 of 8 answerable questions.

That 3/8 also understates the system, which is its own finding. Three further questions
were answered correctly from articles that were never in the gold list, because review
papers restate the same facts. Hand-authored relevance lists are incomplete by
construction, so week 2 opens with TREC-style pooling before any variant is compared.

Abstention holds so far: four refusals across the set, all defensible, and no fabricated
answer in the dry run — though one earlier hallucination is on record below.

## What broke

The interesting part. Full log in [`notes/failures.md`](notes/failures.md); the ones
worth knowing about:

- **"eGFR" retrieves EGFR.** The renal-function acronym and epidermal growth factor
  receptor are the same string. Lexical search cannot break the tie either. This is the
  strongest argument for the week-2 biomedical-embedding comparison.
- **Dense retrieval cannot reach tables.** A grid of numbers embeds nothing like a
  natural-language question, so the answer sits in the index and stays unreachable.
- **Similarity scores are not an abstention signal.** Best score on a well-answered
  question: 0.87. On an unanswered one: 0.81. On an out-of-scope one: 0.75. The ranges
  overlap; refusal has to come from the prompt.
- **A citation that was wrong anyway.** The model expanded "cardiac MRI" into "cardiac
  mitral regurgitation (MR)" and cited the passage it had just contradicted.
- **A regex that ate a word.** An optional separator in the section-title cleaner let a
  bare roman numeral match the leading `i` of "Introduction", pushing 656 paragraphs into
  the catch-all bucket. Nothing crashed; it was found by auditing the bucket.
- **Measured latency was measuring the rate limit**, not the system.

## Roadmap

- **Week 2** — pool and expand the gold set to 40-50 questions, score with RAGAS,
  compare the three chunking variants and a second embedding model
- **Week 3** — tool calling, FastAPI service, Docker Compose, prompt-injection check
- **Week 4** — tracing, per-request token and cost logging, eval in CI

## Licence

MIT. Corpus articles remain under their own CC0 / CC BY terms; PMCIDs and licence codes
are recorded per article.
