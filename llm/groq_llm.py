import os
from groq import Groq, omit
from llm.base import BaseLLM


class GroqLLM(BaseLLM):
    def __init__(self, model_name: str = "openai/gpt-oss-120b"):
        self.model_name = model_name
        # Explicit rather than relying on the SDK's own defaults (60s read timeout,
        # 2 retries) — same order of magnitude, but stated here so the choice is
        # visible and deliberate rather than implicit. A bit more retry persistence
        # than the SDK default, since a failed call here falls all the way through
        # to this app's own fallback content (see the callers' except blocks) —
        # worth trying a little harder before giving up on that.
        self.client = Groq(
            api_key=os.environ.get("GROQ_API_KEY"),
            timeout=45.0,
            max_retries=3,
        )

    def generate(self, prompt: str, system: str | None = None, temperature: float | None = None, json_mode: bool = False) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature if temperature is not None else 0.7,
            # omit (not None) matches the SDK's own "omit this field" sentinel —
            # passing None explicitly would send a literal null to the API instead.
            response_format={"type": "json_object"} if json_mode else omit,
        )
        return response.choices[0].message.content or ""