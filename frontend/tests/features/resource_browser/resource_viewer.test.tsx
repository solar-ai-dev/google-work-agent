import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ResourceViewer } from "../../../src/features/resource_browser/resource_viewer";

test("ResourceViewer renders normalized task detail without treating it as execution context", () => {
  render(<ResourceViewer projection={{
    activeSource: "tasks",
    focusedItem: { selection_handle: "opaque", source: "tasks", resource_type: "task", resource_id: "provider-id", title: "후속 조치", link_url: "https://tasks.google.com/", version: "v1", related_resource_ids: [], metadata: { task_status: "incomplete", scheduled_date: "2026-08-31" } },
    selectedContext: { items: [], resourceIds: [], selectionHandles: [], labels: [] },
    composerPrompt: "요청",
    emptyMessage: "없음",
    focusedItemSelected: false,
    toggleFocusedSelection: vi.fn(),
    openFocusedContainer: vi.fn(),
  }} />);
  expect(screen.getByRole("heading", { name: "후속 조치" })).toBeInTheDocument();
  expect(screen.getByText("미완료")).toBeInTheDocument();
  expect(screen.queryByText("incomplete")).not.toBeInTheDocument();
});
