"""Exceptions raised by the lastwar.farm client."""

from __future__ import annotations

from typing import Any, Optional


class LastWarFarmError(Exception):
    """Base error for anything the client raises."""


class ConfigError(LastWarFarmError):
    """The client is missing configuration, e.g. no API key."""


class ApiError(LastWarFarmError):
    """The API answered with a non-2xx status.

    ``code`` is the stable machine-readable ``error.code`` from the response
    (e.g. ``INVALID_KEY``, ``RATE_LIMITED``, ``TENANT_MISMATCH``). Switch on it,
    not on ``message``.
    """

    def __init__(
        self,
        status: int,
        code: Optional[str],
        message: str,
        details: Any = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(f"HTTP {status} {code or 'UNKNOWN'}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.retry_after = retry_after


class RateLimitedError(ApiError):
    """HTTP 429. ``retry_after`` holds the server's Retry-After in seconds."""
