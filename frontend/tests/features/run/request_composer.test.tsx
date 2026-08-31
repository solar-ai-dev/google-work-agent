import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { RequestComposer, submitNewRun } from "../../../src/features/run/request_composer";

afterEach(() => vi.restoreAllMocks());

test("submitNewRun creates a conversation and sends only normalized opaque selection handles", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1, conversation_id: "conversation-1", title: "title", latest_message_at_ms: null, open_run_id: null }), { status: 200, headers: { "content-type": "application/json" } }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: "run-1", conversation_id: "conversation-1", langgraph_thread_id: "thread-1", status: "QUEUED", version: 1, event_stream_url: "/events" }), { status: 200, headers: { "content-type": "application/json" } }));

  await submitNewRun({ conversationId: null, requestText: "  summarize  ", selectionHandles: [" opaque ", "opaque"] });
  const runBody = JSON.parse(String((fetchMock.mock.calls[1]?.[1] as RequestInit).body));
  expect(runBody).toMatchObject({ request_text: "summarize", entry_mode: "RESOURCE_SELECTED", selected_resource_handles: ["opaque"], requested_mode: "AUTO" });
  expect(runBody).not.toHaveProperty("history");
});

test("RequestComposer owns typed submission interaction", () => {
  const submit = vi.fn().mockResolvedValue(undefined);
  render(<RequestComposer text="request" error={null} busy={false} prompt="요청" selectedResourceLabels={[]} setText={vi.fn()} setError={vi.fn()} onSubmit={submit} />);
  fireEvent.click(screen.getByRole("button", { name: "보내기" }));
  expect(submit).toHaveBeenCalledOnce();
});
