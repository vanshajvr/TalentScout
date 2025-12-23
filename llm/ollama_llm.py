import ollama
from llm.base import BaseLLM


class OllamaLLM(BaseLLM):
    def __init__(self, model_name: str = "llama3"):
        self.model_name = model_name

    def generate(self, prompt: str) -> str:
        response = ollama.chat(
            model=self.model_name,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response["message"]["content"]
