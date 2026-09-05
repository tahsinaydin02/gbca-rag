# The embedding model is baked into the image rather than downloaded on boot. It is 130 MB
# and never changes for a given config, so fetching it at startup would make every restart
# depend on a third-party host being up — and would make a cold container's first request
# several seconds slower than its second.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/opt/hf

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, in their own layer: source changes far more often than the lockfile,
# and this way editing a script does not reinstall torch.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY configs/ configs/
RUN uv run python -c "\
from sentence_transformers import SentenceTransformer; \
import yaml; \
SentenceTransformer(yaml.safe_load(open('configs/default.yaml'))['embedding']['model'])"

COPY api/ api/
COPY ingest/ ingest/
COPY eval/ eval/

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "api.service:app", "--host", "0.0.0.0", "--port", "8000"]
