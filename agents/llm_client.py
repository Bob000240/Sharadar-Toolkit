from dotenv import load_dotenv
load_dotenv()

import os
from openai import OpenAI

_backend = os.getenv("LLM_BACKEND", "openai").lower()

if _backend == "local":
    _client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    ANALYSIS_MODEL = os.getenv("LOCAL_MODEL", "gemma4:26b")
else:
    _client = OpenAI()  # reads OPENAI_API_KEY from env
    ANALYSIS_MODEL = "gpt-4o"


def call_llm_analyze(system: str, user: str, model: str = ANALYSIS_MODEL) -> str:
    """Free-text response — used by analysts and the PM."""
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

