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
    cp .env.example .env     # Groq key for generation, a judge key for evaluation
    make ingest              # fetch, parse, chunk  (~30 MB, a few minutes)
    make index               # start Qdrant, embed, load
    make ask Q="Which GBCAs did the ACR classify as Group I agents?"
    make score SOURCE=judged # variant comparison
    make sig SOURCE=judged   # paired significance tests

## Evaluation

40 questions written from corpus paragraphs — 15 factual, 11 numeric, 9 multi-hop, 4
unanswerable, plus a deliberately easy control item, an item whose sources contradict each
other, and an item whose question embeds a premise the passage denies. Ground truth is
anchored to paragraph ids, so the same set stays valid as chunking changes.

Relevance is defined two ways, and reported both ways because they bound the answer from
opposite sides. Hand-written lists are independent of retrieval and therefore include
paragraphs no variant reaches, which makes them pessimistic. The judged pool — every
variant's retrievals at equal paragraph depth, labelled by a model from a different family
than the generator — contains only paragraphs something already found, which makes it
optimistic.

The judge itself was checked against a human on thirty passages, stratified by its own
label. It confirmed 8 of 10 of its own RELEVANT calls, and — the error that would matter —
none of the passages it dismissed were material a human counted as an answer. Its
disagreement sits on the PARTIAL/NOT boundary, which never enters the strict relevant set,
so the numbers below stand and the lenient PARTIAL-inclusive variant is not reported.

### Results, 36 answerable questions, fixed 2000-token context budget

| Variant | Recall (hand / judged) | Precision (hand / judged) | Success (judged) | Chunks |
|---|---|---|---|---|
| `fixed` | 0.319 / 0.358 | 0.044 / 0.091 | 0.639 | 2.9 |
| `section` | 0.458 / **0.638** | 0.074 / 0.178 | **0.806** | 6.8 |
| `contextual` | 0.481 / 0.595 | 0.077 / 0.180 | 0.806 | 6.6 |

Paired bootstrap and exact McNemar over the same questions:

- **`fixed` is worse**, and this holds up: recall p=0.001, token-weighted precision
  p<0.001 under judged relevance, same direction under hand lists. It fits 2.9 chunks into
  the budget against 6.8, so most of its context window goes to text nobody asked for.
- **`section` and `contextual` cannot be told apart** under either definition — 4-4 on
  success, p≥0.22 on everything else. The contextual prefix costs tokens in every chunk
  and buys nothing measurable, so it is dropped.
- **Success and MRR never reach significance.** Fixed and section disagree on 12 of 36
  questions; separating them at this effect size needs roughly 95 questions. That number
  is reported rather than worked around.

Measured against a fixed *k* instead of a fixed token budget, the ordering reverses and
`fixed` wins on recall@20. Both numbers are true; only one of them describes a service.

### Answering, all 40 questions, `section` chunks

Generator `qwen/qwen3.8-27b`, judge `openai/gpt-oss-120b` — different families, so the
judge is not grading its own homework. Model ids are part of the result: two generators
were retired by the provider during the four weeks this took.

| | |
|---|---|
| Claim-level faithfulness | **1.000** (0 unsupported of 95 claims) |
| Answers citing an article never retrieved | 0 |
| Unanswerable questions refused | 4 / 4 |
| Answerable questions refused | 7 / 36 |
| — of those, context held nothing relevant | 6 (refusing was correct) |
| — of those, context held the answer | **1** (the one real generation failure) |
| Median latency / tokens per question | 0.86 s · 2168 in, 108 out |

A faithfulness of 1.000 is where a measurement usually stops distinguishing things, so the
judge is checked against two recorded fixtures — a hallucination from an earlier run that
expanded "cardiac MRI" into "cardiac mitral regurgitation", and an answer known to stay
inside its sources. It flags the first and clears the second (`make judgetest`). The score
is a result, not a blind instrument.

The decomposition is the finding. Nineteen percent of answerable questions were refused,
which sounds like a cautious system — but six of the seven refusals happened because
retrieval handed the model nothing to work with. The prompt is converting retrieval
failure into silence rather than into invention, which is what it was written to do. The
answering layer itself failed once in thirty-six.

Which also means the headline number is not really about the generator: with a perfect
retriever the same prompt would have had thirty-five chances to hallucinate instead of
twenty-nine. Faithfulness measured downstream of a weak retriever is measured on easy mode,
and that caveat belongs next to the 1.000.

## Where it stands

Both halves are measured. Retrieval is the bottleneck and the numbers say so from two
directions: it is where the variant comparison finds real differences, and it is the cause
of six of the seven times the system declined to answer.

What is not built: the FastAPI service, tool calling, request tracing and a CI eval gate.
`make judgetest` is that gate in miniature. The rest is scoped out rather than pending —
see the roadmap.

## What broke

The interesting part. Full log in [`notes/failures.md`](notes/failures.md); the ones
worth knowing about:

- **"eGFR" retrieves EGFR.** The renal-function acronym and epidermal growth factor
  receptor are the same string. Lexical search cannot break the tie either. This is the
  strongest argument for the week-2 biomedical-embedding comparison.
- **Tables are reachable, just badly ranked.** First recorded as unreachable, which was
  wrong: pooling deeper surfaces them. The distinction changes the fix from hybrid search
  to reranking.
- **The judgement pool rewarded the system that filled it.** Pool depth counted in chunks
  let the fixed variant, which carries 3.7 paragraphs per chunk against 1.5, contribute
  two and a half times more candidates — and it duly looked better. Counting depth in
  paragraphs reversed the result.
- **Verifying absence by keyword only tests the phrasing you guessed.** A question written
  as unanswerable, after searching for "sickle cell" and "gadolinium" together, is answered
  by a passage that says GBCA throughout and never says gadolinium.
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

- **Week 2, remaining** — faithfulness and abstention over the 40 questions; measure how
  far the automatic judge sits from a human on a stratified sample
- **Week 2, done** — pool and expand the gold set to 40-50 questions, score with RAGAS,
  compare the three chunking variants and a second embedding model
- **Week 3** — tool calling, FastAPI service, Docker Compose, prompt-injection check
- **Week 4** — tracing, per-request token and cost logging, eval in CI

## Licence

MIT. Corpus articles remain under their own CC0 / CC BY terms; PMCIDs and licence codes
are recorded per article.
