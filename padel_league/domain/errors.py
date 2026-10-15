"""Domain errors. Each carries a stable `code` and a Portuguese message for the player.

The API maps InvalidInput to 400, Conflict to 409 and NotFound to 404.
"""


class DomainError(ValueError):
    code = "domain_error"

    def __init__(self, message, code=None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class InvalidInput(DomainError):
    code = "invalid_input"


class Conflict(DomainError):
    code = "conflict"


class NotFound(DomainError):
    code = "not_found"
