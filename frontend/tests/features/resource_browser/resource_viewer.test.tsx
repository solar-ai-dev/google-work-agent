import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ResourceViewer } from "../../../src/features/resource_browser/resource_viewer";
import * as detailApi from "../../../src/features/resource_browser/api/get_resource_detail";

vi.mock("../../../src/features/resource_browser/api/get_resource_detail", () => ({
  getGmailResourceDetail: vi.fn(),
  getTaskResourceDetail: vi.fn(),
  getCalendarResourceDetail: vi.fn(),
}));

test("ResourceViewer invokes and renders the focused task detail contract", async () => {
  vi.mocked(detailApi.getTaskResourceDetail).mockResolvedValue({ schema_version: 1, resource_id: "provider-id", title: "후속 조치", task_status: "incomplete", scheduled_date: "2026-08-31", completed_at: null, tasklist_id: "default", notes: "검토 필요" });
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
  expect(await screen.findByRole("heading", { name: "후속 조치" })).toBeInTheDocument();
  expect(detailApi.getTaskResourceDetail).toHaveBeenCalledWith("provider-id", "opaque");
  expect(screen.getByText("미완료")).toBeInTheDocument();
  expect(screen.queryByText("incomplete")).not.toBeInTheDocument();
});

test("ResourceViewer invokes and renders the focused Calendar detail contract", async () => {
  vi.mocked(detailApi.getCalendarResourceDetail).mockResolvedValue({ schema_version: 1, resource_id: "event-1", title: "프로젝트 검토", start: "2026-08-31T09:00:00+09:00", end: "2026-08-31T10:00:00+09:00", timezone: "Asia/Seoul", calendar_id: "primary", attendees: ["user@example.com"], location: null, description: "주간 검토" });
  render(<ResourceViewer projection={{
    activeSource: "calendar",
    focusedItem: { selection_handle: "calendar-handle", source: "calendar", resource_type: "calendar_event", resource_id: "event-1", title: "프로젝트 검토", link_url: null, version: "v1", related_resource_ids: [], metadata: { start: "2026-08-31T09:00:00+09:00", end: "2026-08-31T10:00:00+09:00", calendar_id: "primary" } },
    selectedContext: { items: [], resourceIds: [], selectionHandles: [], labels: [] },
    composerPrompt: "요청",
    emptyMessage: "없음",
    focusedItemSelected: false,
    toggleFocusedSelection: vi.fn(),
    openFocusedContainer: vi.fn(),
  }} />);
  expect(await screen.findByRole("heading", { name: "프로젝트 검토" })).toBeInTheDocument();
  expect(detailApi.getCalendarResourceDetail).toHaveBeenCalledWith("event-1", "calendar-handle");
  expect(screen.getByText("user@example.com")).toBeInTheDocument();
});
