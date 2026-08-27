import hashlib
import hmac
import json


def sign_claim_context(session_key: str, payload: dict[str, object]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    normalized = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(bytes.fromhex(session_key), normalized, hashlib.sha256).hexdigest()
