import { requestJson } from "../../../api/client";
import type {
  CalendarListItemWire,
  GmailListItemWire,
  ResourceCountResponse,
  ResourceItem,
  ResourceListResponse,
  ResourceListWireResponse,
  TaskListItemWire,
} from "../../../api/contract";

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
  return requestJson<ResourceListWireResponse>(`/api/v1/resources/${request.source}?${search.toString()}`).then((response) => ({
    ...response,
    items: response.items.map((item) => projectResourceItem(request.source, item, response.projection_version)),
  }));
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

function projectResourceItem(
  source: ListResourcesRequest["source"],
  value: ResourceListWireResponse["items"][number],
  projectionVersion: string,
): ResourceItem {
  if (source === "gmail") {
    const item = value as GmailListItemWire;
    return {
      ...item,
      source,
      resource_type: "gmail_thread",
      title: item.subject,
      subtitle: null,
      link_url: null,
      version: projectionVersion,
      related_resource_ids: [],
      metadata: {
        subject: item.subject,
        sender_name: item.sender_name,
        sender_email: item.sender_email,
        received_at: item.received_at,
        snippet: item.snippet,
        has_attachments: item.has_attachments,
      },
    };
  }
  if (source === "tasks") {
    const item = value as TaskListItemWire;
    return {
      ...item,
      source,
      resource_type: "task",
      parent_id: item.tasklist_id,
      subtitle: null,
      link_url: null,
      version: projectionVersion,
      related_resource_ids: [item.tasklist_id],
      metadata: {
        task_status: item.task_status,
        scheduled_date: item.scheduled_date,
        completed_at: item.completed_at,
        tasklist_id: item.tasklist_id,
      },
    };
  }
  const item = value as CalendarListItemWire;
  return {
    ...item,
    source,
    resource_type: "calendar_event",
    parent_id: item.calendar_id,
    subtitle: null,
    link_url: null,
    version: projectionVersion,
    related_resource_ids: [item.calendar_id],
    metadata: {
      start: item.start,
      end: item.end,
      timezone: item.timezone,
      calendar_id: item.calendar_id,
      location: item.location,
    },
  };
}
