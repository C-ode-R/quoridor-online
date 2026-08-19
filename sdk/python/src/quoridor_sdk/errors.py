class QuoridorError(Exception):
    """Base exception raised by the SDK."""


class ApiError(QuoridorError):
    """The game server rejected a request."""

    def __init__(self, code: str, status: int | None = None):
        self.code = code
        self.status = status
        super().__init__(code)


class ConnectionError(QuoridorError):
    """The game server could not be reached."""


class InvalidActionError(QuoridorError):
    """choose_action returned an unsupported or currently illegal action."""
