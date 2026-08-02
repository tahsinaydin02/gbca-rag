VARIANT ?= section
Q ?= What eGFR threshold has been used to exclude patients from receiving gadolinium-based contrast?

.PHONY: up down fetch parse chunk ingest embed index ask quick lint

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

lint:
	uv run ruff check . && uv run ruff format --check .
