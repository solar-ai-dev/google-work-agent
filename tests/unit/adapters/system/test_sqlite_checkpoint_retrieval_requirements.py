from google_work_agent.adapters.system.sqlite_checkpoint import (
    _retrieval_requirements_from_checkpoint,
)


def test_retrieval_cache_requirements_project_only_bounded_bindings() -> None:
    requirements = _retrieval_requirements_from_checkpoint(
        {
            "channel_values": {
                "__context_read_result_handles__": ["read-1", "read-1"],
                "__context_read_bindings__": {
                    "read-1": {
                        "route_id": "route-1",
                        "query_identity_hash": "a" * 64,
                        "raw_result": "must-not-project",
                    }
                },
            }
        }
    )

    assert requirements is not None
    assert len(requirements) == 1
    assert requirements[0].read_result_handle == "read-1"
    assert requirements[0].route_id == "route-1"
    assert requirements[0].query_identity_hash == "a" * 64
