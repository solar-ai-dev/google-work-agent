"""Persistence adapter error hierarchy."""


class PersistenceError(Exception):
    """Base class for persistence adapter failures."""


class MigrationError(PersistenceError):
    """Base class for migration failures."""


class MigrationDiscoveryError(MigrationError):
    """Raised when migration files cannot be discovered or parsed safely."""


class MigrationIntegrityError(MigrationError):
    """Raised when persisted migration metadata is internally inconsistent."""


class MigrationChecksumMismatchError(MigrationIntegrityError):
    """Raised when an applied migration differs from the packaged migration."""


class MigrationApplyError(MigrationError):
    """Raised when a migration fails and is rolled back."""
