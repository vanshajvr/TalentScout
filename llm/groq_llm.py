import os
from groq import Groq
from llm.base import BaseLLM


class GroqLLM(BaseLLM):
    def __init__(self, model_name: str = "openai/gpt-oss-120b"):
        self.model_name = model_name
        self.client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

    def generate(self, prompt: str, system: str | None = None, temperature: float | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature if temperature is not None else 0.7,
        )
        return response.choices[0].message.content or ""