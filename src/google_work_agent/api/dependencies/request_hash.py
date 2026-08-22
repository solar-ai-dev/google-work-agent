"""Build the server-owned semantic hash for a command request."""

from google_work_agent.domain import calculate_canonical_json_hash


def calculate_server_request_hash(*, operation: str, payload: dict[str, object]) -> str:
    return calculate_canonical_json_hash({"operation": operation, "payload": payload})
