"""Project business text without changing the provider's recovery evidence."""


def strip_resource_recovery_marker(value: str | None) -> str | None:
    if value is None:
        return None
    marker_index = value.find("\u200bgwa-recovery-fingerprint:")
    if marker_index < 0:
        return value
    visible = value[:marker_index]
    return visible[:-2] if visible.endswith("\n\n") else visible
