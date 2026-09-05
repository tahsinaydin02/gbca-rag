"""HTTP service around the answering path.

The CLI reloaded the embedding model on every invocation, about two seconds each time, and
the eval runs paid it forty times over. Here the model and the vector store are opened once
at startup and reused, which is most of what turning a script into a service actually buys.

Endpoints are defined with `def` rather than `async def` on purpose. The work behind them —
embedding a query, a synchronous HTTP call to the model provider — is blocking, and FastAPI
runs sync handlers in a threadpool. Declaring them async would put blocking calls on the
event loop and stall every other request in flight; the keyword would look more modern and
serve fewer people at once.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from api.ask import ask, load_config
from api.retrieve import _client, _model, search
from api.tools import SECTIONS, compute_dose, search_corpus


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    variant: Literal["fixed", "section", "contextual"] = "section"
    section: str | None = Field(default=None, description="restrict retrieval to one section")


class Passage(BaseModel):
    pmcid: str
    section: str | None
    score: float
    text: str


class AskResponse(BaseModel):
    answer: str
    abstained: bool
    sources: list[str]
    passages: list[Passage]
    context_tokens: int
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    model: str
    request_id: str


class DoseRequest(BaseModel):
    weight_kg: float = Field(gt=0, le=400)
    dose_mmol_per_kg: float = Field(gt=0, le=1)
    concentration_mmol_per_ml: float | None = Field(default=None, gt=0)


REFUSAL = "NOT ANSWERABLE FROM THE PROVIDED PASSAGES"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Touch both dependencies before accepting traffic. A service that starts happily and
    # fails on its first real request is harder to diagnose than one that refuses to start.
    app.state.config = load_config()
    _model()
    _client()
    yield


app = FastAPI(
    title="gbca-rag",
    summary="Grounded question answering over open-access gadolinium contrast agent literature.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    """Report on dependencies, not just on the process being alive.

    A health check that only proves the web server booted is the kind that stays green
    while every request fails.
    """
    try:
        collections = [c.name for c in _client().get_collections().collections]
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"vector store unreachable: {exc}") from None
    return {"status": "ok", "collections": collections}


@app.post("/ask", response_model=AskResponse)
def ask_endpoint(req: AskRequest) -> AskResponse:
    request_id = uuid.uuid4().hex[:12]
    cfg = dict(app.state.config)
    cfg["retrieval"] = {**cfg["retrieval"], "variant": req.variant}

    if req.section and req.section not in SECTIONS:
        raise HTTPException(status_code=422, detail=f"section must be one of {SECTIONS}")

    started = time.perf_counter()
    try:
        out = ask(req.question, cfg, req.section)
    except Exception as exc:
        # The provider's failures are not this service's failures; 502 says so.
        raise HTTPException(status_code=502, detail=f"model provider error: {exc}") from None

    hits = search(req.question, req.variant, cfg["retrieval"]["max_chunks"], req.section)
    answer = out["answer"]

    return AskResponse(
        answer=answer,
        abstained=REFUSAL in answer.upper(),
        sources=sorted({h["pmcid"] for h in hits}),
        passages=[
            Passage(
                pmcid=h["pmcid"],
                section=h["section"],
                score=round(h["score"], 4),
                text=h["text"][:500],
            )
            for h in hits[: out["n_chunks"]]
        ],
        context_tokens=out["context_tokens"],
        prompt_tokens=out["prompt_tokens"],
        completion_tokens=out["completion_tokens"],
        latency_s=round(time.perf_counter() - started, 3),
        model=out["model"],
        request_id=request_id,
    )


@app.get("/search")
def search_endpoint(q: str, section: str | None = None, k: int = 5) -> dict:
    try:
        return search_corpus(q, section, k)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/tools/dose")
def dose_endpoint(req: DoseRequest) -> dict:
    """The dose tool, exposed directly as well as to the model.

    Same function either way. A tool the model can call but a caller cannot inspect is a
    tool nobody can check.
    """
    return compute_dose(req.weight_kg, req.dose_mmol_per_kg, req.concentration_mmol_per_ml)
