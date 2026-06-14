from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
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
