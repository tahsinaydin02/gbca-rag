VARIANT ?= section
SOURCE ?= hand
Q ?= What eGFR threshold has been used to exclude patients from receiving gadolinium-based contrast?

.PHONY: up down fetch parse chunk ingest embed index ask quick score sig agree lint save

up:
	docker compose up -d
down:
	docker compose down

fetch:
	uv run python ingest/fetch.py
parse:
	uv run python ingest/parse.py
chunk:
	uv run python ingest/chunk.py
ingest: fetch parse chunk

embed:
	uv run python ingest/embed.py --variant $(VARIANT)
index: up embed

ask:
	uv run python -m api.ask "$(Q)"
quick:
	uv run python -m eval.run_quick

score:
	uv run python -m eval.score_retrieval --source $(SOURCE)
sig:
	uv run python -m eval.significance --source $(SOURCE)
agree:
	uv run python -m eval.agreement

lint:
	uv run ruff check . && uv run ruff format --check .

# Formatting hooks rewrite files during commit, which aborts the commit and leaves the
# fixes unstaged. Staging twice around a single commit attempt makes that a non-event.
save:
	@test -n "$(m)" || (echo 'usage: make save m="feat: ..."' && exit 1)
	-uv run pre-commit run --all-files
	git add -A
	-git commit -m "$(m)"
	git add -A
	git commit -m "$(m)" || echo "nothing further to commit"
	@git log --oneline -1
