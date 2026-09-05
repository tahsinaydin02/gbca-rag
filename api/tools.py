"""Tools the model may call, and the arithmetic it should not be doing in its head.

Two tools, deliberately not more. Each one is a place where the model would otherwise
guess: dose arithmetic, which it does plausibly and sometimes wrongly, and filtered
retrieval, which it cannot do at all without being handed the index.

Both are pure functions with validated inputs. A tool that can fail silently is worse than
no tool, because the model presents its output with the same confidence either way.
"""

from __future__ import annotations

from api.retrieve import search

SECTIONS = ("abstract", "introduction", "methods", "results", "discussion", "conclusion", "case")


def compute_dose(
    weight_kg: float,
    dose_mmol_per_kg: float,
    concentration_mmol_per_ml: float | None = None,
) -> dict:
    """Convert a weight-based dose into millimoles, and into millilitres if concentration
    is known.

    The corpus states doses per kilogram (0.1 mmol/kg is the standard) and concentrations
    per millilitre (gadobutrol is formulated at 1.0 mmol/mL). Turning those into a volume
    is a multiplication the model can do, and occasionally does wrong — and a wrong number
    here reads exactly like a right one.
    """
    if weight_kg <= 0 or weight_kg > 400:
        raise ValueError("weight_kg must be between 0 and 400")
    if dose_mmol_per_kg <= 0 or dose_mmol_per_kg > 1:
        raise ValueError("dose_mmol_per_kg must be between 0 and 1")

    total_mmol = weight_kg * dose_mmol_per_kg
    result = {
        "total_mmol": round(total_mmol, 4),
        "basis": f"{weight_kg} kg x {dose_mmol_per_kg} mmol/kg",
    }
    if concentration_mmol_per_ml:
        if concentration_mmol_per_ml <= 0:
            raise ValueError("concentration_mmol_per_ml must be positive")
        result["volume_ml"] = round(total_mmol / concentration_mmol_per_ml, 3)
        result["concentration_mmol_per_ml"] = concentration_mmol_per_ml
    return result


def search_corpus(query: str, section: str | None = None, k: int = 5) -> dict:
    """Retrieve passages, optionally restricted to one section of the papers.

    Section filtering is the reason the parser bothered to classify sections at all. A
    question about how something was measured wants Methods; a question about what was
    found wants Results. Without the filter the model gets whichever passage embeds
    closest and has no way to ask for the right kind.
    """
    if section and section not in SECTIONS:
        raise ValueError(f"section must be one of {SECTIONS}")
    hits = search(query, "section", min(k, 10), section)
    return {
        "passages": [
            {
                "pmcid": h["pmcid"],
                "section": h["section"],
                "score": round(h["score"], 4),
                "text": h["text"][:600],
            }
            for h in hits
        ]
    }


# Schemas as the provider expects them. Descriptions are written for the model, not for a
# human reader: they say when to reach for the tool, which is the part it gets wrong.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "compute_dose",
            "description": (
                "Convert a weight-based gadolinium dose into total millimoles, and into "
                "millilitres when the formulation concentration is known. Use this "
                "whenever a question involves a dose for a specific body weight, instead "
                "of multiplying it yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "weight_kg": {"type": "number", "description": "Patient weight in kg"},
                    "dose_mmol_per_kg": {
                        "type": "number",
                        "description": "Dose in mmol per kg, e.g. 0.1 for a standard dose",
                    },
                    "concentration_mmol_per_ml": {
                        "type": "number",
                        "description": "Formulation concentration, e.g. 1.0 for gadobutrol",
                    },
                },
                "required": ["weight_kg", "dose_mmol_per_kg"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_corpus",
            "description": (
                "Search the indexed literature for more passages, optionally restricted to "
                "one section of the papers. Use this when the passages already provided do "
                "not contain the answer and a different part of the papers might — for "
                "example restricting to methods for how something was measured."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "section": {"type": "string", "enum": list(SECTIONS)},
                    "k": {"type": "integer", "description": "How many passages, at most 10"},
                },
                "required": ["query"],
            },
        },
    },
]

DISPATCH = {"compute_dose": compute_dose, "search_corpus": search_corpus}


def run_tool(name: str, arguments: dict) -> dict:
    """Execute a tool call, returning the error to the model rather than raising.

    A tool that raises kills the request; a tool that returns its complaint gives the model
    a chance to correct the call, which is usually a malformed argument rather than a
    genuine impossibility.
    """
    fn = DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(**arguments)
    except (TypeError, ValueError) as exc:
        return {"error": str(exc)}
