"""Dense retrieval over a Qdrant chunk collection.

Kept separate from the answering path so that retrieval can be evaluated on its own.
Week 2 splits the blame between the two: if context recall is low the retriever is at
fault, if faithfulness is low the prompt or the model is.
"""

from __future__ import annotations

import argparse
import functools
import os

from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-small-en-v1.5"
# Overridable so the same code runs from a laptop and from inside the compose network,
# where the vector store answers to a service name rather than to localhost.
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")

# bge asks for this on the query side only; passages are embedded bare.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@functools.lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


@functools.lru_cache(maxsize=1)
def _client() -> QdrantClient:
    """Connect, and fail with one readable line rather than a hundred of traceback.

    A stopped container is the most common thing to go wrong here and the least
    interesting to read about, so it is checked once, up front, before any caller has
    spent time embedding a query.
    """
    client = QdrantClient(url=QDRANT_URL)
    try:
        client.get_collections()
    except Exception as exc:
        raise SystemExit(
            f"Qdrant unreachable at {QDRANT_URL} — run `make up` first ({type(exc).__name__})"
        ) from None
    return client


def search(
    query: str, variant: str = "section", k: int = 5, section: str | None = None
) -> list[dict]:
    vec = _model().encode(QUERY_PREFIX + query, normalize_embeddings=True)
    flt = (
        models.Filter(
            must=[models.FieldCondition(key="section", match=models.MatchValue(value=section))]
        )
        if section
        else None
    )
    hits = (
        _client()
        .query_points(
            f"chunks_{variant}", query=vec.tolist(), limit=k, query_filter=flt, with_payload=True
        )
        .points
    )
    return [{"score": h.score, **h.payload} for h in hits]


def main() -> None:
    ap = argparse.ArgumentParser(description="Eyeball retrieval results.")
    ap.add_argument("query")
    ap.add_argument("--variant", default="section")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--section", help="restrict to one section label")
    args = ap.parse_args()

    for i, hit in enumerate(search(args.query, args.variant, args.k, args.section), 1):
        head = f"{i}. [{hit['score']:.3f}] {hit['pmcid']}  {hit['section']}"
        if hit.get("section_title"):
            head += f" / {hit['section_title'][:40]}"
        print(f"\n{head}")
        print(f"   {hit['text'][:300].strip()}...")


if __name__ == "__main__":
    main()
