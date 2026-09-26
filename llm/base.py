class BaseLLM:
    """
    Abstract base class for all LLM backends.
    """

    def generate(self, prompt: str, system: str | None = None, temperature: float | None = None, json_mode: bool = False) -> str:
        """
        Takes a prompt string and returns a text response. json_mode=True asks the
        backend to constrain its output to valid JSON syntax, for callers that are
        about to parse the result — reduces reliance on post-hoc repair of malformed
        JSON, though callers should still handle parse failures defensively.
        """
        raise NotImplementedError("LLM must implement generate()")