from typing import cast

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.normalize_segments import (
    ContextBudget,
    normalize_segments,
)


def _result(text: str) -> AcquisitionResultV1:
    return cast(
        AcquisitionResultV1,
        {
            "schema_version": 1,
            "source_summaries": [
                {
                    "connector_id": "google_workspace",
                    "source": "GMAIL",
                    "resources": [
                        {
                            "resource_handle": "ephemeral-handle",
                            "resource_type": "gmail_message",
                            "resource_id": "m1",
                            "version": "v1",
                            "payload": {"body": text},
                        }
                    ],
                }
            ],
            "resource_handles": ["ephemeral-handle"],
            "availability_results": [],
        },
    )


def test_segment_id__is_stable__and_content_sensitive() -> None:
    first = normalize_segments(_result("same content"))[0].segment_id
    repeated = normalize_segments(_result("same content"))[0].segment_id
    changed = normalize_segments(_result("changed content"))[0].segment_id

    assert first == repeated
    assert first.startswith("seg_") and len(first) == 68
    assert changed != first


def test_normalize_segments__shares_bounded_context_across_resources() -> None:
    acquisition = _result("unused")
    acquisition["source_summaries"][0]["resources"] = [
        {
            "resource_handle": handle,
            "resource_type": "gmail_thread",
            "resource_id": handle,
            "version": "v1",
            "payload": {"body": " ".join(f"{handle}-{index}" for index in range(20))},
        }
        for handle in ("gmail_thread:first", "gmail_thread:second")
    ]

    segments = normalize_segments(
        acquisition,
        context_budget=ContextBudget(
            max_segments=4,
            chunk_target_tokens=12,
            chunk_max_tokens=16,
            chunk_overlap_tokens=0,
        ),
    )

    assert [segment.resource_handle for segment in segments] == [
        "gmail_thread:first",
        "gmail_thread:second",
        "gmail_thread:first",
        "gmail_thread:second",
    ]
