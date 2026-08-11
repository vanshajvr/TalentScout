import ollama
from llm.base import BaseLLM


class OllamaLLM(BaseLLM):
    def __init__(self, model_name: str = "llama3"):
        self.model_name = model_name

    def generate(self, prompt: str, system: str | None = None, temperature: float | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        options = {}
        if temperature is not None:
            options["temperature"] = temperature

        response = ollama.chat(model=self.model_name, messages=messages, options=options or None)
        return response["message"]["content"]