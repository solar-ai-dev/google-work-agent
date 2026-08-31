import { expect, test } from "vitest";
import type { ResourceItem } from "../../../src/api/contract";
import { buildSelectedResourceContext } from "../../../src/features/resource_browser/selected_resource_context";

const item = (resourceId: string, handle: string): ResourceItem => ({
  resource_id: resourceId,
  selection_handle: handle,
  source: "gmail",
  resource_type: "gmail_thread",
  title: resourceId,
  link_url: "https://mail.google.com/",
  version: "v1",
  related_resource_ids: [],
  metadata: {},
});

test("buildSelectedResourceContext keeps only ordered opaque handles and presentation labels", () => {
  const result = buildSelectedResourceContext([
    item("provider-id-a", " opaque-a "),
    item("provider-id-b", "opaque-a"),
    item("provider-id-c", "opaque-c"),
  ], (resource) => `label:${resource.resource_id}`);

  expect(result.selectionHandles).toEqual(["opaque-a", "opaque-c"]);
  expect(result.resourceIds).toEqual(["provider-id-a", "provider-id-c"]);
  expect(result.labels).toEqual(["label:provider-id-a", "label:provider-id-c"]);
});
