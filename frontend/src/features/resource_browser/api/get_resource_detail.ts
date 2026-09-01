import { requestJson } from "../../../api/client";
import type {
  CalendarResourceDetailResponse,
  GmailResourceDetailResponse,
  TaskResourceDetailResponse,
} from "../../../api/contract";

export function getGmailResourceDetail(resourceId: string): Promise<GmailResourceDetailResponse> {
  return requestJson(`/api/v1/resources/gmail/${encodeURIComponent(resourceId)}`);
}

export function getTaskResourceDetail(
  resourceId: string,
  selectionHandle: string,
): Promise<TaskResourceDetailResponse> {
  const search = new URLSearchParams({ selection_handle: selectionHandle });
  return requestJson(`/api/v1/resources/tasks/${encodeURIComponent(resourceId)}?${search}`);
}

export function getCalendarResourceDetail(
  resourceId: string,
  selectionHandle: string,
): Promise<CalendarResourceDetailResponse> {
  const search = new URLSearchParams({ selection_handle: selectionHandle });
  return requestJson(`/api/v1/resources/calendar/${encodeURIComponent(resourceId)}?${search}`);
}
