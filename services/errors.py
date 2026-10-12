"""Typed service-layer errors.

The API layer turns these into HTTP status codes; the Dash layerc renders the
message inline at the field. Nothing internal ever reaches the browser.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for expected, user-facing service failures."""

    status = 400

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field

    def to_dict(self) -> dict:
        payload = {"error": self.message}
        if self.field:
            payload["field"] = self.field
        return payload


class ValidationError(ServiceError):
    """Input failed validation at the boundary."""

    status = 400


class ConflictError(ServiceError):
    """The requested transition conflicts with current state."""

    status = 409


class NotFoundError(ServiceError):
    """The requested row does not exist."""

    status = 404
