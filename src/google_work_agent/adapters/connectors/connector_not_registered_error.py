"""Connector registry lookup failure."""


class ConnectorNotRegisteredError(LookupError):
    """Raised when no backend is registered for an explicit connector id."""
