import { requestJson } from "../../../api/client";
import type { ResourceCountResponse, ResourceListResponse } from "../../../api/contract";

export type ListResourcesRequest =
  | { source: "gmail"; query: string; continuation?: string | null; pageSize?: number; includeThreadMetadata?: boolean }
  | { source: "tasks"; taskListId?: string | null; continuation?: string | null; pageSize?: number; statusScope?: "incomplete" | "completed" }
  | { source: "calendar"; calendarId?: string | null; continuation?: string | null; pageSize?: number; timeMin: string; timeMax: string };

export function listResources(request: ListResourcesRequest): Promise<ResourceListResponse> {
  const search = new URLSearchParams();
  if (request.source === "gmail") {
    search.set("query", request.query.trim());
    search.set("page_size", String(boundedPageSize(request.pageSize, 20)));
    if (request.continuation) search.set("page_token", request.continuation);
    if (request.includeThreadMetadata === false) search.set("include_thread_metadata", "false");
  } else if (request.source === "tasks") {
    search.set("page_size", String(boundedPageSize(request.pageSize, 100)));
    if (request.taskListId) search.set("task_list_id", request.taskListId);
    if (request.continuation) search.set("page_token", request.continuation);
    if (request.statusScope === "completed") search.set("status_scope", "completed");
  } else {
    search.set("page_size", String(boundedPageSize(request.pageSize, 100)));
    if (request.calendarId) search.set("calendar_id", request.calendarId);
    if (request.continuation) search.set("page_token", request.continuation);
    search.set("time_min", request.timeMin);
    search.set("time_max", request.timeMax);
  }
  return requestJson(`/api/v1/resources/${request.source}?${search.toString()}`);
}

export function getResourceCount(
  source: "gmail" | "tasks" | "calendar",
  options: {
    query?: string | null;
    taskListId?: string | null;
    calendarId?: string | null;
    timeMin?: string | null;
    timeMax?: string | null;
  } = {},
): Promise<ResourceCountResponse> {
  const search = new URLSearchParams();
  if (options.query) search.set("query", options.query);
  if (options.taskListId) search.set("task_list_id", options.taskListId);
  if (options.calendarId) search.set("calendar_id", options.calendarId);
  if (options.timeMin) search.set("time_min", options.timeMin);
  if (options.timeMax) search.set("time_max", options.timeMax);
  const suffix = search.size > 0 ? `?${search.toString()}` : "";
  return requestJson(`/api/v1/resources/${source}/count${suffix}`);
}

function boundedPageSize(value: number | undefined, fallback: number): number {
  if (value === undefined) return fallback;
  return Math.max(1, Math.min(100, Math.trunc(value)));
}
