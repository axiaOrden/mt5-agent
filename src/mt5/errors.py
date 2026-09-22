"""Shared provider-layer exceptions."""


class ProviderError(RuntimeError):
    """Raised for any provider-level failure (connection, API, data)."""
