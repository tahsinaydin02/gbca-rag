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
