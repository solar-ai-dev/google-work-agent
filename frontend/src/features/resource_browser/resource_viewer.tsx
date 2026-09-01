import { useCallback, useEffect, useState } from "react";
import { ApiClientError } from "../../api/client";
import type {
  CalendarResourceDetailResponse,
  GmailResourceDetailResponse,
  ResourceItem,
  TaskResourceDetailResponse,
} from "../../api/contract";
import { downloadAttachment } from "../attachment";
import {
  getCalendarResourceDetail,
  getGmailResourceDetail,
  getTaskResourceDetail,
} from "./api/get_resource_detail";
import { ResourceDetail } from "./resource_detail";
import type { ResourceBrowserProjection } from "./resource_sidebar";
import { presentResource } from "./resource_sidebar";

type GmailDetailState = {
  resourceId: string | null;
  status: "idle" | "loading" | "ready" | "error";
  detail: GmailResourceDetailResponse | null;
  error: string | null;
};

type TaskDetailState = {
  resourceId: string | null;
  status: "idle" | "loading" | "ready" | "error";
  detail: TaskResourceDetailResponse | null;
  error: string | null;
};

type CalendarDetailState = {
  resourceId: string | null;
  status: "idle" | "loading" | "ready" | "error";
  detail: CalendarResourceDetailResponse | null;
  error: string | null;
};

type Props = { projection: ResourceBrowserProjection };

export function ResourceViewer({ projection }: Props): JSX.Element {
  const [gmailDetail, setGmailDetail] = useState<GmailDetailState>({ resourceId: null, status: "idle", detail: null, error: null });
  const [taskDetail, setTaskDetail] = useState<TaskDetailState>({ resourceId: null, status: "idle", detail: null, error: null });
  const [calendarDetail, setCalendarDetail] = useState<CalendarDetailState>({ resourceId: null, status: "idle", detail: null, error: null });
  const loadGmailDetail = useCallback(async (resourceId: string): Promise<void> => {
    setGmailDetail({ resourceId, status: "loading", detail: null, error: null });
    try {
      const detail = await getGmailResourceDetail(resourceId);
      setGmailDetail((current) => current.resourceId === resourceId ? { resourceId, status: "ready", detail, error: null } : current);
    } catch (error) {
      setGmailDetail((current) => current.resourceId === resourceId ? { resourceId, status: "error", detail: null, error: error instanceof ApiClientError ? error.message : "메일 내용을 불러오지 못했습니다." } : current);
    }
  }, []);
  const loadTaskDetail = useCallback(async (item: ResourceItem): Promise<void> => {
    setTaskDetail({ resourceId: item.resource_id, status: "loading", detail: null, error: null });
    try {
      const detail = await getTaskResourceDetail(item.resource_id, item.selection_handle);
      setTaskDetail((current) => current.resourceId === item.resource_id ? { resourceId: item.resource_id, status: "ready", detail, error: null } : current);
    } catch (error) {
      setTaskDetail((current) => current.resourceId === item.resource_id ? { resourceId: item.resource_id, status: "error", detail: null, error: error instanceof ApiClientError ? error.message : "태스크 상세를 불러오지 못했습니다." } : current);
    }
  }, []);
  const loadCalendarDetail = useCallback(async (item: ResourceItem): Promise<void> => {
    setCalendarDetail({ resourceId: item.resource_id, status: "loading", detail: null, error: null });
    try {
      const detail = await getCalendarResourceDetail(item.resource_id, item.selection_handle);
      setCalendarDetail((current) => current.resourceId === item.resource_id ? { resourceId: item.resource_id, status: "ready", detail, error: null } : current);
    } catch (error) {
      setCalendarDetail((current) => current.resourceId === item.resource_id ? { resourceId: item.resource_id, status: "error", detail: null, error: error instanceof ApiClientError ? error.message : "일정 상세를 불러오지 못했습니다." } : current);
    }
  }, []);

  useEffect(() => {
    const item = projection.focusedItem;
    setGmailDetail({ resourceId: null, status: "idle", detail: null, error: null });
    setTaskDetail({ resourceId: null, status: "idle", detail: null, error: null });
    setCalendarDetail({ resourceId: null, status: "idle", detail: null, error: null });
    if (item?.resource_type === "gmail_thread") void loadGmailDetail(item.resource_id);
    else if (item?.resource_type === "task") void loadTaskDetail(item);
    else if (item?.resource_type === "calendar_event") void loadCalendarDetail(item);
  }, [loadCalendarDetail, loadGmailDetail, loadTaskDetail, projection.focusedItem]);

  return (
    <>
      {projection.focusedItem ? <button className="button-secondary" type="button" aria-pressed={projection.focusedItemSelected} onClick={projection.toggleFocusedSelection}>{projection.focusedItemSelected ? "요청에서 제외" : "요청에 포함"}</button> : null}
      <ResourceDetail
        focusItem={projection.focusedItem}
        gmailDetail={gmailDetail}
        taskDetail={taskDetail}
        calendarDetail={calendarDetail}
        onRetryGmailDetail={() => { if (projection.focusedItem) void loadGmailDetail(projection.focusedItem.resource_id); }}
        onRetryTaskDetail={() => { if (projection.focusedItem) void loadTaskDetail(projection.focusedItem); }}
        onRetryCalendarDetail={() => { if (projection.focusedItem) void loadCalendarDetail(projection.focusedItem); }}
        onDownloadGmailAttachment={(messageId, attachmentId) => { void downloadAttachment(messageId, attachmentId); }}
        onDrillInto={projection.openFocusedContainer}
        presentResource={presentResource}
        metadataEntriesFor={metadataEntries}
        emptyMessage={projection.emptyMessage}
        formatMailboxIdentity={mailbox}
      />
    </>
  );
}

function metadataEntries(item: ResourceItem): Array<[string, string]> {
  if (item.source === "tasks" && item.resource_type === "task") {
    const entries: Array<[string, string]> = [];
    const status = taskStatusLabel(item.metadata.task_status ?? null);
    const scheduledDate = formatTaskDate(item.metadata.scheduled_date ?? null, true);
    if (status) entries.push(["상태", status]);
    if (scheduledDate) entries.push(["예정일", scheduledDate]);
    return entries;
  }
  if (item.source === "calendar" && item.resource_type === "calendar_event") {
    const start = item.metadata.start ?? null;
    const end = item.metadata.end ?? null;
    if (/^\d{4}-\d{2}-\d{2}$/.test(start ?? "")) {
      const date = formatCalendarDate(start);
      return date ? [["날짜", date]] : [];
    }
    const entries: Array<[string, string]> = [];
    const startLabel = formatCalendarDate(start);
    const endLabel = formatCalendarDate(end);
    if (startLabel) entries.push(["시작 시간", startLabel]);
    if (endLabel) entries.push(["종료 시간", endLabel]);
    if (item.metadata.location) entries.push(["장소", item.metadata.location]);
    return entries;
  }
  const entries: Array<[string, string]> = [];
  const senderName = item.sender_name ?? item.metadata.sender_name ?? null;
  const senderEmail = item.sender_email ?? item.metadata.sender_email ?? null;
  const receivedAt = item.received_at ?? item.metadata.received_at ?? null;
  const snippet = item.snippet ?? item.metadata.snippet ?? null;
  if (senderName) entries.push(["보낸사람", senderName]);
  if (senderEmail) entries.push(["이메일", senderEmail]);
  if (receivedAt) entries.push(["받은 시각", receivedAt]);
  if (snippet) entries.push(["내용", snippet]);
  return entries;
}

function taskStatusLabel(value: string | null): string | null {
  return value === "incomplete" ? "미완료" : value === "completed" ? "완료" : null;
}

function formatTaskDate(value: string | null, detailed: boolean): string | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  const dateLabel = date.toLocaleDateString("ko-KR", detailed
    ? { year: "numeric", month: "long", day: "numeric" }
    : { month: "long", day: "numeric" });
  return `${dateLabel} (${date.toLocaleDateString("ko-KR", { weekday: "short" })})`;
}

function formatCalendarDate(value: string | null): string | null {
  if (!value) return null;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return formatTaskDate(value, true);
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function mailbox(name: string | null, email: string | null): string | null {
  if (name && email && name !== email) return `${name} <${email}>`;
  return name ?? (email ? `<${email}>` : null);
}
