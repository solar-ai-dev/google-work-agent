"""Canonical Google provider operation for gmail search threads."""

from concurrent.futures import ThreadPoolExecutor

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as workspace_support,
)


def _gmail_search_threads(
    state: workspace_support.GoogleWorkspaceCredentialProvider, arguments: dict[str, object]
) -> dict[str, object]:
    query = workspace_support._text_argument(arguments, "query", maximum=2048, allow_empty=True)
    include_thread_metadata = arguments.get("include_thread_metadata", True)
    if not isinstance(include_thread_metadata, bool):
        raise workspace_support._WorkspaceToolError("INVALID_ARGUMENT")
    params = workspace_support._page_params(arguments)
    if query:
        params["q"] = query
    if not include_thread_metadata:
        params["fields"] = "threads/id,nextPageToken"
    payload = workspace_support._google_api(
        state, "https://gmail.googleapis.com/gmail/v1/users/me/threads", params
    )
    threads = workspace_support._object_list(payload.get("threads"))
    thread_entries = [
        (
            workspace_support._required_response_text(thread, "id"),
            workspace_support._optional_text(thread.get("snippet")),
            thread.get("historyId"),
        )
        for thread in threads
    ]
    if include_thread_metadata:
        with ThreadPoolExecutor(
            max_workers=workspace_support.GMAIL_METADATA_HYDRATION_MAX_WORKERS
        ) as executor:
            metadata_items = list(
                executor.map(
                    lambda entry: workspace_support._gmail_thread_list_metadata(
                        state=state, thread_id=entry[0], list_snippet=entry[1]
                    ),
                    thread_entries,
                )
            )
    else:
        metadata_items = [{} for _ in thread_entries]
    items = []
    for (thread_id, _list_snippet, history_id), metadata in zip(
        thread_entries, metadata_items, strict=True
    ):
        items.append(
            workspace_support._snapshot("gmail_thread", thread_id, None, (), history_id, metadata)
        )
    return {
        "items": items,
        "next_page_token": workspace_support._optional_text(payload.get("nextPageToken")),
    }


class SearchThreadsOperation:
    tool_id = "gmail_search_threads"

    def execute(
        self,
        state: workspace_support.GoogleWorkspaceCredentialProvider,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        return _gmail_search_threads(state, arguments)


__all__ = ["SearchThreadsOperation"]
