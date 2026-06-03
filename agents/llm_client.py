import json
from typing import Any
from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
_client = OpenAI()  # reads OPENAI_API_KEY from env

ANALYSIS_MODEL = "gpt-4o"
VERDICT_MODEL = "gpt-4o-mini"

_VERDICT_EXTRACTION_SYSTEM = (
    "You are a structured data extractor. "
    "Read the investment thesis below and return a JSON object with exactly three keys:\n"
    '  "direction": one of "bullish", "neutral", "bearish"\n'
    '  "confidence": float between 0.0 and 1.0\n'
    '  "reasoning": one sentence summary of the thesis\n'
    "Return only valid JSON. No extra keys."
)


def call_llm(system: str, user: str, model: str = VERDICT_MODEL) -> dict[str, Any]:
    """Single-step call. Returns parsed JSON verdict dict."""
    try:
        response = _client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError as e:
        return {"direction": "neutral", "confidence": 0.0, "reasoning": f"JSON parse error: {e}"}
    except Exception as e:
        return {"direction": "neutral", "confidence": 0.0, "reasoning": f"LLM error: {e}"}


def call_llm_analyze(system: str, user: str, model: str = ANALYSIS_MODEL) -> str:
    """Free-text thesis generation — no JSON pressure on the reasoning model."""
    try:
        response = _client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Analysis error: {e}"


def call_llm_verdict(thesis: str, model: str = VERDICT_MODEL) -> dict[str, Any]:
    """Extract structured verdict from a free-text thesis using the verdict model."""
    try:
        response = _client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _VERDICT_EXTRACTION_SYSTEM},
                {"role": "user", "content": thesis},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError as e:
        return {"direction": "neutral", "confidence": 0.0, "reasoning": f"JSON parse error: {e}"}
    except Exception as e:
        return {"direction": "neutral", "confidence": 0.0, "reasoning": f"LLM error: {e}"}
