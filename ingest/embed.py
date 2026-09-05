"""Embed a chunk set and load it into Qdrant.

Vectors are cached on disk by content hash. Chunking is the experiment variable of
this project, so the same paragraph text gets re-chunked and re-embedded many times
over the next two weeks; the cache means only genuinely new text pays the GPU cost.

Note on bge-small: the query side wants the instruction prefix
"Represent this sentence for searching relevant passages: ", the passage side does
not. Adding it here would quietly degrade retrieval. It belongs in the search path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path

import numpy as np
import torch
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "emb_cache.npz"

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIM = 384
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")


def text_key(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def load_cache() -> dict[str, np.ndarray]:
    if not CACHE_PATH.exists():
        return {}
    z = np.load(CACHE_PATH)
    return {k: v for k, v in zip(z["keys"], z["vecs"], strict=True)}


def save_cache(cache: dict[str, np.ndarray]) -> None:
    np.savez(
        CACHE_PATH,
        keys=np.array(list(cache.keys())),
        vecs=np.stack(list(cache.values())),
    )


def pick_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


def main() -> None:
    ap = argparse.ArgumentParser(description="Embed chunks and load them into Qdrant.")
    ap.add_argument("--variant", default="section", choices=["fixed", "section", "contextual"])
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--recreate", action="store_true", help="drop the collection first")
    args = ap.parse_args()

    chunks = [json.loads(line) for line in (ROOT / "data" / f"chunks_{args.variant}.jsonl").open()]
    print(f"{args.variant}: {len(chunks)} chunks")

    cache = load_cache()
    missing = [c for c in chunks if text_key(c["text"]) not in cache]
    print(f"cached: {len(chunks) - len(missing)}  to embed: {len(missing)}")

    if missing:
        device = pick_device()
        print(f"loading {MODEL_NAME} on {device}")
        model = SentenceTransformer(MODEL_NAME, device=device)
        vecs = model.encode(
            [c["text"] for c in missing],
            batch_size=args.batch_size,
            normalize_embeddings=True,  # cosine distance assumes unit vectors
            show_progress_bar=True,
        )
        for c, v in zip(missing, vecs, strict=True):
            cache[text_key(c["text"])] = v.astype(np.float32)
        save_cache(cache)

    client = QdrantClient(url=QDRANT_URL)
    name = f"chunks_{args.variant}"
    if args.recreate and client.collection_exists(name):
        client.delete_collection(name)
    if not client.collection_exists(name):
        client.create_collection(
            name,
            vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE),
        )
        # Indexed so that section- and article-filtered retrieval stays fast; the
        # section filter is the whole point of parsing structure out of the XML.
        for field in ("section", "pmcid"):
            client.create_payload_index(
                name, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD
            )

    batch = []
    for c in chunks:
        batch.append(
            models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, c["chunk_id"])),
                vector=cache[text_key(c["text"])].tolist(),
                payload={
                    k: c[k]
                    for k in (
                        "chunk_id",
                        "pmcid",
                        "section",
                        "section_title",
                        "para_ids",
                        "text",
                        "n_tokens",
                    )
                },
            )
        )
        if len(batch) >= 256:
            client.upsert(name, points=batch)
            batch = []
    if batch:
        client.upsert(name, points=batch)

    info = client.get_collection(name)
    print(f"collection '{name}': {info.points_count} points")


if __name__ == "__main__":
    main()
