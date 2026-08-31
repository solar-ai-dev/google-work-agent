import { afterEach, expect, test, vi } from "vitest";
import { getResourceCount, listResources } from "../../../../src/features/resource_browser/api/list_resources";

afterEach(() => vi.restoreAllMocks());

test("listResources uses bounded source-specific Local API filters and opaque continuation", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    source: "gmail", items: [], next_page_token: null, api_contract_version: "1",
  }), { status: 200, headers: { "content-type": "application/json" } }));

  await listResources({ source: "gmail", query: " follow up ", continuation: "opaque-next", pageSize: 999, includeThreadMetadata: false });
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/resources/gmail?query=follow+up&page_size=100&page_token=opaque-next&include_thread_metadata=false");
});

test("resource count remains in the resource-browser API owner", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    source: "gmail", total_count: 3, api_contract_version: "1",
  }), { status: 200, headers: { "content-type": "application/json" } }));
  await getResourceCount("gmail", { query: "in:inbox" });
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/resources/gmail/count?query=in%3Ainbox");
});
