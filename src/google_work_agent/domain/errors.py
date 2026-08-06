"""Domain error hierarchy for contract violations."""


class DomainError(Exception):
    """Base class for domain programming errors."""


class InvalidTransitionError(DomainError):
    """Raised when a transition contract is wired incorrectly."""


class VersionConflictError(DomainError):
    """Raised when version conflict handling itself fails."""


class DuplicateCommandError(DomainError):
    """Raised when a duplicate command contract is violated."""


class CommandHashMismatchError(DomainError):
    """Raised when command idempotency hash validation fails."""


class InvariantViolationError(DomainError):
    """Raised when an invariant cannot be represented as a normal result."""
