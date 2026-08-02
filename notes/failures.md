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
