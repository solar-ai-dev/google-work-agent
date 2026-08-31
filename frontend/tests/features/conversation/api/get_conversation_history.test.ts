import { afterEach, expect, test, vi } from "vitest";
import { getConversationHistory, listConversations } from "../../../../src/features/conversation/api/get_conversation_history";

afterEach(() => vi.restoreAllMocks());

test("conversation API owner encodes identity and owns bounded list transport", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1, conversation: {}, messages: [], runs: [], truncated: false }), { status: 200, headers: { "content-type": "application/json" } }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1, items: [], next_cursor: null }), { status: 200, headers: { "content-type": "application/json" } }));
  await getConversationHistory("conversation/1");
  await listConversations("opaque-cursor", "budget");
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/conversations/conversation%2F1/history");
  expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/conversations?page_size=50&cursor=opaque-cursor&search=budget");
});
