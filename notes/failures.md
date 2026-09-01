cat > notes/failures.md <<'MD'
# Failure log

Things that broke, what caused them, how they were found.

## 2026-08-03 — Roman numeral regex swallowed "Introduction"

`normalize_title` stripped a leading roman numeral with an optional separator:
`^[\dIVXivx]+[.)]?\s*`. Because both the separator and the whitespace were optional,
the pattern matched the bare leading `i` of "introduction", leaving "ntroduction",
which matched no rule. 656 paragraphs — the majority of the corpus introductions —
were labelled `other`.

Nothing raised. Nothing crashed. Found only by printing the section-title
distribution *inside* the `other` bucket instead of trusting the aggregate.
Fix: require an explicit `.` or `)` after the numeral.

Lesson: a classifier with a catch-all bucket hides its own bugs. Audit the bucket.

## 2026-08-03 — Sentence splitter could not split tables

Oversized paragraphs were broken at sentence boundaries, but flattened tables carry
no sentence punctuation, so a 2695-token table stayed as one "sentence" and blew past
the 512-token embedding limit (98 chunks affected).

Naive fix would be a hard token split, but that severs the header row from the numbers
beneath it — and 20% of the planned gold set is numeric. Real fix: split tables at row
boundaries and repeat caption + header in every piece, with a hard split kept only as
a last-resort guard.

## 2026-08-03 — eGFR retrieves EGFR

"What eGFR threshold contraindicates gadolinium administration?" returns four
passages about epidermal growth factor receptor targeting in tumor imaging. The
embedding model treats the renal-function acronym and the receptor as the same
token; lexical search cannot break the tie either, since the strings are identical.

This is the strongest argument in the project for the Week 2 embedding comparison:
a general-purpose model has no reason to know these are different concepts, and a
biomedical one might. Query expansion ("estimated glomerular filtration rate") and a
reranker are the other two candidate fixes.

## 2026-08-03 — dense retrieval cannot reach tables

The dentate-nucleus signal-intensity question returned prose discussing the finding,
never the table holding the numbers. A grid of values embeds nothing like a natural
language question. Keeping tables was still right — the answer is in the corpus — but
reaching them needs lexical or hybrid search.

## 2026-08-03 — similarity scores are not an abstention signal

Best score on a question the corpus answers well: 0.87. Best score on a question it
answers not at all: 0.81. Best score on an out-of-scope question: 0.75. The ranges
overlap, so no threshold separates answerable from unanswerable. Abstention has to be
handled in the prompt, not by cutting off the retriever.

## 2026-08-03 — abbreviation expanded into a hallucination

Asked about pediatric cardiac MRI anesthesia, the model wrote that patients "underwent
cardiac mitral regurgitation (MR) under general anesthesia". The passage said "underwent
cardiac MRI". The model expanded an abbreviation using its own knowledge and produced a
claim the context does not support.

Small, fluent, and cited — the hardest kind of error for a reader to catch, and the
reason faithfulness is scored per claim rather than per answer. Keep this question as a
regression case: an evaluator that scores it faithful is miscalibrated.

## 2026-08-03 — abstention masks retrieval failure

The eGFR question retrieved EGFR passages, and the model correctly refused to answer.
End-to-end accuracy would score this as a success. It is not one: retrieval failed
completely and only the prompt prevented a wrong answer. Retrieval and generation have
to be scored separately or failures like this stay invisible.

## 2026-08-03 — "unanswerable" questions need verifying too

Pediatric anesthesia was assumed to be outside the corpus. It is not: PMC9668776 gives a
propofol dose. Unanswerable gold questions must be checked against the index the same way
answerable ones are, or the 15% unanswerable slice measures nothing.

## 2026-08-03 — the gold set is incomplete by construction

Retrieval fetched a hand-listed gold paragraph for only 3 of 8 answerable questions,
yet the system answered q3, q4 and q7 correctly from articles that were never in the
gold list. The corpus is full of review papers restating the same facts, so any
hand-authored relevance list is a subset of what is actually relevant, and recall
measured against it is biased low.

Fix for week 2, borrowed from TREC: pool the retrieved paragraphs across all three
chunking variants, judge that pool for relevance, and expand relevant_para_ids from it.
Comparing variants against an incomplete ruler measures the ruler, not the variants.

## 2026-08-03 — right article, wrong paragraph

On q2 and q5 the retriever surfaced the correct article but not the paragraph holding
the number, and the model correctly refused or hedged. This is a different failure from
retrieving irrelevant material and needs a different remedy: within-article reranking,
or a larger top-k followed by a reranker, rather than better embeddings.

## 2026-08-03 — measured latency is contaminated by rate limiting

Latency ran 0.43-0.79 s for the first questions and 7.9-13.8 s for the later ones. The
model did not slow down; the free tier's 6000 tokens-per-minute cap throttled the batch.
Any latency figure taken from a back-to-back eval run measures the quota, not the system.
Latency has to be measured separately, with requests spaced out.

## Correction: tables are reachable, just badly ranked

An earlier entry claimed dense retrieval could not reach tables. Pooling at depth 50
shows the opposite: the relaxivity table surfaces, it simply never makes the top 15. The
distinction matters because it changes the fix — reranking rather than hybrid search.

## Ranking failures and representation failures are different problems

Pooling all three variants at depth 15 left five questions with no gold paragraph
retrieved. Raising pool depth to 50 recovered four of them. Only q3 stays unreachable at
any depth: the query "eGFR" and the passages about estimated glomerular filtration rate
never come close, because the embedding treats the acronym as the epidermal growth factor
receptor.

So the failure budget splits: four cases a reranker can fix by reordering what is already
retrieved, one case that needs a different representation entirely — hybrid search, query
expansion, or a biomedical embedding model. Saying "retrieval is weak" would have hidden
that these need opposite remedies.

## One pool judgement run costs one day of quota

Judging 1359 pooled paragraphs consumed the judge model's entire daily token allowance
(200k) in about 70 calls. The pool is inflated by the fixed-window variant, whose chunks
average 3.7 paragraphs each, so a single question can contribute 160 paragraphs to judge.

Consequences worth designing around rather than discovering again: passage snippets sent
to the judge should be as short as the decision allows, pool depth should be justified by
where gold paragraphs actually rank rather than chosen for comfort, and any expansion of
the question set multiplies this cost linearly. A 40-question gold set will need several
days of judging, or a cheaper judge for the bulk with the strong judge held for a sample.

## Eight questions cannot rank three variants

Strict judgements put contextual first on budget recall (0.292); loose judgements put it
last (0.220). MRR prefers fixed under strict labels and section under loose ones. With
eight questions a single item moves any mean by 0.125, so most of these gaps are one
question changing its mind.

What survives both settings is structural rather than statistical: the fixed-window
variant fits 3.1 chunks into the serving token budget against 7.3 for section, and its
success rate drops accordingly (0.444 vs 0.778 under loose labels). The same variant has
the best recall@20 of the three. Holding k constant and holding tokens constant rank
these systems in opposite orders.

Also: with 1-4 relevant paragraphs per question under strict labels, recall is close to
binary and mostly noise. Success@k and MRR are the honest metrics at this scale.

## Pooling nearly doubled the relevant set, and exposed a reporting bug

Judging the pool found 11 relevant paragraphs beyond the 12 written by hand — the
hand-authored lists were missing roughly half of what actually answers these questions,
which is the whole reason the pooling step exists.

The first version of the comparison also reported hand-listed paragraphs as "rejected by
the judge" when several had simply never entered the pool: no variant retrieved them, so
they were never shown to the judge. Absence of a judgement is not a negative judgement,
and conflating the two turns a retrieval failure into an apparent authoring error.

## Truncating passages for the judge costs about 3% of its labels

Passages were cut to 500 characters to fit the judge's daily token budget; 63% of the
pool is longer than that. Re-judging a sample of 100 truncated passages at full length
flipped 3 of them — one to RELEVANT, two to PARTIAL.

Extrapolated across 777 truncated-and-NOT passages, roughly eight relevant paragraphs are
probably missing from a judged set of seventeen. That is small in rate and large in
proportion, so absolute recall here should be read as a lower bound. Variant comparisons
are less affected: the same missing denominator applies to all three.

Not re-judged in full. A complete re-run costs a day of quota to move numbers that are
already bounded by an eight-question sample — the sample size is the larger error term.

## Most of the variant differences are not established at 35 questions

Paired bootstrap and exact McNemar over the same 35 questions:

  fixed vs section      precision p=0.014 (real), recall p=0.094, success p=0.344,
                        MRR p=0.388
  fixed vs contextual   recall p=0.029 and precision p=0.001 (real), success p=0.125
  section vs contextual nothing significant, all differences within +/-0.02

So the earlier claim that section beats fixed "on every metric" was overstated. What
holds up is that fixed wastes context tokens: its token-weighted precision is lower with
a confidence interval clear of zero. Its apparent disadvantage on success and MRR is not
distinguishable from noise.

Success@budget is the most interpretable metric and the least powerful one. Fixed and
section disagreed on only 10 of 35 questions, split 3-7, and a 70/30 split needs roughly
27 disagreements to clear p<0.05 — about 95 questions at the observed disagreement rate.
That is the price of a defensible success comparison, and it is worth knowing before
writing another thirty questions for the wrong reason.

The section-vs-contextual result is the cleanest thing here: four metrics, four
differences near zero, intervals excluding any large effect. The contextual prefix costs
tokens in every chunk and buys nothing measurable, so it goes.

A caveat on the one strong result: token-weighted precision partly measures a structural
property rather than retrieval quality. Larger chunks carry more irrelevant text by
construction, so the most significant finding is also the least surprising.

## Verifying absence with a lexical search only tests the vocabulary you guessed

q39 was written as unanswerable after searching for "sickle cell" together with
"gadolinium" returned nothing. Pooling then surfaced a passage titled "GBCAs and Patients
with Sickle Cell Disease", which answers the question directly. It says GBCA throughout
and never says gadolinium.

This is the fourth question written as unanswerable that the corpus turned out to answer,
and the first where the cause is precisely identifiable rather than carelessness. The
lesson generalises past this project: a lexical search proves that a phrasing is absent,
not that a fact is. Unanswerable items need either a semantic check or several phrasings.

Worth recording that the judgement pool caught it. The apparatus built to measure
retrieval ended up validating the gold set instead, which is the better argument for
having built it.

## Selecting questions on the outcome dropped the hardest ones

Scoring filtered to questions with a non-empty relevant set. Under judged relevance,
three answerable questions (q2, q8, q22) have no relevant paragraph in the pool at all —
no variant surfaced anything the judge accepted. Filtering removed exactly those three,
so every variant was being averaged over the questions it had already half-passed.

Answerability now comes from the gold set's own type field, and a question with nothing
relevant retrieved scores zero for all variants rather than disappearing.

## Two relevance definitions bracket the answer instead of agreeing on one

Scoring the same 36 questions against hand-written relevance lists and against the judged
pool gives different absolute numbers and the same ordering.

  budget recall     hand 0.319 / 0.458 / 0.481   judged 0.358 / 0.638 / 0.595
                    (fixed / section / contextual)

I expected judged recall to come out lower, on the grounds that the pool holds more
relevant paragraphs and so a larger denominator. It came out higher, and the reason is
worth stating: the pool is built from what retrieval returned, so everything in it is by
construction findable. The hand-written lists were written by reading articles, so they
include paragraphs no variant reaches.

That makes them a lower and an upper bound rather than two attempts at one number.
Retrieval-independent relevance is pessimistic; pool-derived relevance is optimistic; the
honest statement is that budget recall for section chunking lies between 0.46 and 0.64.

The ordering survives both: fixed is worse on recall (p=0.001) and precision (p<0.001)
under judged relevance and in the same direction under hand lists, while section and
contextual stay indistinguishable under both — 4-4 on success, p>=0.22 everywhere else.
Success and MRR never reach significance under either definition, which is what the power
calculation predicted and is now confirmed twice.

## The judge is conservative, and conservative in the harmless direction

Thirty passages, stratified ten per judge label, relabelled by hand without seeing the
judge's verdict:

  judge RELEVANT   8 RELEVANT   2 PARTIAL   0 NOT
  judge PARTIAL    2 RELEVANT   8 PARTIAL   0 NOT
  judge NOT        0 RELEVANT   7 PARTIAL   3 NOT

Nothing the judge dismissed was material a human would count as an answer. That is the
error that matters here: a false NOT removes a relevant paragraph from the gold set
entirely, so no variant can be credited for finding it and every recall figure drops
without anything reporting why. Zero of ten.

The disagreement sits almost entirely on the PARTIAL/NOT boundary — the judge calls
things irrelevant that a human calls background. Since PARTIAL never enters the strict
relevant set, this leaves every headline number intact and makes the --include-partial
scoring the unreliable one. It is not reported.

Exact agreement on the stratified sample is 0.63, which is not an accuracy figure: the
sample was deliberately enriched for the rare labels. Reweighted to the pool's real
distribution it falls to about 0.38, driven entirely by that same boundary.

Caveats worth stating: one annotator, no blind re-test, and the annotator wrote the
questions. Agreement measured this way bounds the judge's error, it does not establish
that the human is right.
