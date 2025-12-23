from llm.ollama_llm import OllamaLLM

llm = OllamaLLM()

prompt = "Ask one intermediate-level Python interview question."
print(llm.generate(prompt))
