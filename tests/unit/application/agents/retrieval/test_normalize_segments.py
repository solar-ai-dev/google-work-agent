from typing import cast

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.normalize_segments import normalize_segments


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
