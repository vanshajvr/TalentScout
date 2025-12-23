class BaseLLM:
    """
    Abstract base class for all LLM backends.
    """

    def generate(self, prompt: str) -> str:
        """
        Takes a prompt string and returns a text response.
        """
        raise NotImplementedError("LLM must implement generate()")
