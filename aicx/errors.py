class AICXError(Exception):
    """A user-facing error with a stable, named error code."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
