"""Cookie helpers for the local API."""

import hashlib


def local_session_cookie_name(service_instance_id: str) -> str:
    """Return a service-instance-bound cookie name without exposing its identity."""

    suffix = hashlib.sha256(service_instance_id.encode("utf-8")).hexdigest()[:12]
    return f"gwa_session_{suffix}"
