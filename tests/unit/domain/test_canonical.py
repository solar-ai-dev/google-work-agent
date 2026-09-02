from google_work_agent.domain.canonical import (
    calculate_canonical_json_hash,
    canonicalize_json_value,
)


def test_canonicalize_json_value__sorts_keys_and__removes_extra_whitespace() -> None:
    payload = {"b": 2, "a": [3, {"z": True, "x": None}]}

    assert canonicalize_json_value(payload) == '{"a":[3,{"x":null,"z":true}],"b":2}'


def test_canonical_json_hash__is_stable_for__equivalent_json_values() -> None:
    left = {"subject": "hello", "recipients": ["a@example.com"], "thread_id": None}
    right = {"thread_id": None, "recipients": ["a@example.com"], "subject": "hello"}

    assert calculate_canonical_json_hash(left) == calculate_canonical_json_hash(right)


def test_canonical_json__hash_changes_when__json_value_changes() -> None:
    original = {"title": "sync", "due": "2026-08-06"}
    changed = {"title": "sync!", "due": "2026-08-06"}

    assert calculate_canonical_json_hash(original) != calculate_canonical_json_hash(changed)
