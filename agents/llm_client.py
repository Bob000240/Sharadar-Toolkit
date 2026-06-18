from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_openai_client = OpenAI()
_local_client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
REMOTE_MODEL = "gpt-4o"


def call_llm_analyze(system: str, user: str, model: str = REMOTE_MODEL) -> str:
    client = _openai_client if model == REMOTE_MODEL else _local_client

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content
