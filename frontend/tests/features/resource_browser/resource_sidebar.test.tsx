import { expect, test } from "vitest";
import { presentResource } from "../../../src/features/resource_browser/resource_sidebar";

test("resource sidebar presents exact server-projected provider titles", () => {
  expect(presentResource({ schema_version: 1, selection_handle: "a", source: "tasks", resource_type: "task", resource_id: "a", title: "GWA-DEADLINE-ONLY-TEST", link_url: null, version: "1", related_resource_ids: [], metadata: {} }).title).toBe("GWA-DEADLINE-ONLY-TEST");
  expect(presentResource({ schema_version: 1, selection_handle: "b", source: "gmail", resource_type: "gmail_thread", resource_id: "b", title: "예산 검토 요청", subject: "예산 검토 요청", link_url: null, version: "1", related_resource_ids: [], metadata: {} }).title).toBe("예산 검토 요청");
});
