import { expect, test } from "vitest";
import { presentResource } from "../../../src/features/resource_browser/resource_sidebar";

test("resource sidebar presentation preserves provider task titles and prefers Gmail subject over a generic title", () => {
  expect(presentResource({ selection_handle: "a", source: "tasks", resource_type: "task", resource_id: "a", title: "GWA-DEADLINE-ONLY-TEST", link_url: "", version: "1", related_resource_ids: [], metadata: {} }).title).toBe("GWA-DEADLINE-ONLY-TEST");
  expect(presentResource({ selection_handle: "b", source: "gmail", resource_type: "gmail_thread", resource_id: "b", title: "메일 자료", subject: "예산 검토 요청", link_url: "", version: "1", related_resource_ids: [], metadata: {} }).title).toBe("예산 검토 요청");
});
