import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { RequestComposer, submitNewRun } from "../../../src/features/run/request_composer";
import { createConversation } from "../../../src/features/conversation";

afterEach(() => vi.restoreAllMocks());

test("submitNewRun creates a conversation and sends only normalized opaque selection handles", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1, conversation_id: "conversation-1", title: "title", latest_message_at_ms: null, open_run_id: null }), { status: 200, headers: { "content-type": "application/json" } }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: "run-1", conversation_id: "conversation-1", langgraph_thread_id: "thread-1", status: "QUEUED", version: 1, event_stream_url: "/events" }), { status: 200, headers: { "content-type": "application/json" } }));

  await submitNewRun({
    conversationId: null,
    requestText: "  summarize  ",
    selectionHandles: [" opaque ", "opaque"],
    conversationCommandId: "conversation-command",
    runCommandId: "run-command",
    requestedMode: "API_LLM",
    createConversation,
  });
  const conversationBody = JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit).body));
  const runBody = JSON.parse(String((fetchMock.mock.calls[1]?.[1] as RequestInit).body));
  expect(conversationBody.command_id).toBe("conversation-command");
  expect(runBody.command_id).toBe("run-command");
  expect(runBody).toMatchObject({ request_text: "summarize", entry_mode: "RESOURCE_SELECTED", selected_resource_handles: ["opaque"], requested_mode: "API_LLM" });
  expect(runBody).not.toHaveProperty("history");
});

test("RequestComposer owns typed submission interaction", () => {
  const submit = vi.fn().mockResolvedValue(undefined);
  render(<RequestComposer text="request" error={null} busy={false} workflowExecuting={false} cancelAllowed={false} cancelling={false} prompt="요청" selectedResourceLabels={[]} setText={vi.fn()} setError={vi.fn()} onSubmit={submit} onCancel={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "보내기" }));
  expect(submit).toHaveBeenCalledOnce();
});

test("RequestComposer replaces send with the current Run stop command", () => {
  const submit = vi.fn().mockResolvedValue(undefined);
  const cancel = vi.fn().mockResolvedValue(undefined);
  render(<RequestComposer text="next request" error={null} busy={false} workflowExecuting cancelAllowed cancelling={false} prompt="요청" selectedResourceLabels={[]} setText={vi.fn()} setError={vi.fn()} onSubmit={submit} onCancel={cancel} />);

  expect(screen.queryByRole("button", { name: "보내기" })).not.toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole("textbox", { name: "요청" }), { key: "Enter" });
  fireEvent.click(screen.getByRole("button", { name: "중지" }));

  expect(submit).not.toHaveBeenCalled();
  expect(cancel).toHaveBeenCalledOnce();
});
