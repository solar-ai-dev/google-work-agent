import { afterEach, expect, test, vi } from "vitest";
import { getResourceCount, listResources } from "../../../../src/features/resource_browser/api/list_resources";

afterEach(() => vi.restoreAllMocks());

test("listResources uses bounded source-specific Local API filters and opaque continuation", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    schema_version: 1, items: [], next_page_token: null, total_count: null, projection_version: "1",
  }), { status: 200, headers: { "content-type": "application/json" } }));

  await listResources({ source: "gmail", query: " follow up ", continuation: "opaque-next", pageSize: 999, includeThreadMetadata: false });
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/resources/gmail?query=follow+up&page_size=100&page_token=opaque-next&include_thread_metadata=false");
});

test("listResources projects the exact #159 Gmail wire contract without stale aliases", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    schema_version: 1,
    items: [{
      schema_version: 1,
      selection_handle: "opaque-handle",
      resource_id: "resource-1",
      subject: "Current subject",
      sender_name: "Sender",
      sender_email: "sender@example.com",
      received_at: "2026-08-31T00:00:00Z",
      snippet: "Current snippet",
      has_attachments: true,
    }],
    next_page_token: "opaque-next",
    total_count: null,
    projection_version: "7",
  }), { status: 200, headers: { "content-type": "application/json" } }));

  const response = await listResources({ source: "gmail", query: "" });

  expect(response.items).toEqual([expect.objectContaining({
    schema_version: 1,
    selection_handle: "opaque-handle",
    resource_id: "resource-1",
    source: "gmail",
    resource_type: "gmail_thread",
    title: "Current subject",
    version: "7",
    metadata: expect.objectContaining({
      sender_email: "sender@example.com",
      has_attachments: true,
    }),
  })]);
  expect(response.next_page_token).toBe("opaque-next");
  expect(response).not.toHaveProperty("api_contract_version");
});

test("resource count remains in the resource-browser API owner", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    schema_version: 1, source: "gmail", exact_count: 3, as_of_ms: 1,
  }), { status: 200, headers: { "content-type": "application/json" } }));
  const response = await getResourceCount("gmail", { query: "in:inbox" });
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/resources/gmail/count?query=in%3Ainbox");
  expect(response.exact_count).toBe(3);
  expect(response).not.toHaveProperty("total_count");
});
