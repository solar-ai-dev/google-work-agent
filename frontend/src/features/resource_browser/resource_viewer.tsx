import { useCallback, useEffect, useState } from "react";
import { ApiClientError, requestJson } from "../../api/client";
import type { GmailResourceDetailResponse, ResourceItem } from "../../api/contract";
import { downloadAttachment } from "../attachment/api/download_attachment";
import { ResourceDetail } from "../workspace/ResourceDetail";
import type { ResourceBrowserProjection } from "./resource_sidebar";
import { presentResource } from "./resource_sidebar";

type GmailDetailState = {
  resourceId: string | null;
  status: "idle" | "loading" | "ready" | "error";
  detail: GmailResourceDetailResponse | null;
  error: string | null;
};

type Props = { projection: ResourceBrowserProjection };

export function ResourceViewer({ projection }: Props): JSX.Element {
  const [gmailDetail, setGmailDetail] = useState<GmailDetailState>({ resourceId: null, status: "idle", detail: null, error: null });
  const loadGmailDetail = useCallback(async (resourceId: string): Promise<void> => {
    setGmailDetail({ resourceId, status: "loading", detail: null, error: null });
    try {
      const detail = await requestJson<GmailResourceDetailResponse>(`/api/v1/resources/gmail/${encodeURIComponent(resourceId)}`);
      setGmailDetail((current) => current.resourceId === resourceId ? { resourceId, status: "ready", detail, error: null } : current);
    } catch (error) {
      setGmailDetail((current) => current.resourceId === resourceId ? { resourceId, status: "error", detail: null, error: error instanceof ApiClientError ? error.message : "메일 내용을 불러오지 못했습니다." } : current);
    }
  }, []);

  useEffect(() => {
    const item = projection.focusedItem;
    if (item?.resource_type === "gmail_thread") void loadGmailDetail(item.resource_id);
    else setGmailDetail({ resourceId: null, status: "idle", detail: null, error: null });
  }, [loadGmailDetail, projection.focusedItem]);

  return (
    <>
      {projection.focusedItem ? <button className="button-secondary" type="button" aria-pressed={projection.focusedItemSelected} onClick={projection.toggleFocusedSelection}>{projection.focusedItemSelected ? "요청에서 제외" : "요청에 포함"}</button> : null}
      <ResourceDetail
        focusItem={projection.focusedItem}
        gmailDetail={gmailDetail}
        onRetryGmailDetail={() => { if (projection.focusedItem) void loadGmailDetail(projection.focusedItem.resource_id); }}
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
    const status = taskStatusLabel(displayValue(item.metadata.task_status));
    const scheduledDate = formatTaskDate(displayValue(item.metadata.scheduled_date), true);
    const notes = displayValue(item.metadata.notes);
    if (status) entries.push(["상태", status]);
    if (scheduledDate) entries.push(["예정일", scheduledDate]);
    if (notes) entries.push(["내용", notes]);
    return entries;
  }
  if (item.source === "calendar" && item.resource_type === "calendar_event") {
    const start = displayValue(item.metadata.start);
    const end = displayValue(item.metadata.end);
    if (/^\d{4}-\d{2}-\d{2}$/.test(start ?? "")) {
      const date = formatCalendarDate(start);
      return date ? [["날짜", date]] : [];
    }
    const entries: Array<[string, string]> = [];
    const startLabel = formatCalendarDate(start);
    const endLabel = formatCalendarDate(end);
    if (startLabel) entries.push(["시작 시간", startLabel]);
    if (endLabel) entries.push(["종료 시간", endLabel]);
    const calendarName = displayValue(item.metadata.calendar_name) ?? displayValue(item.metadata.calendar_display_name);
    const description = displayValue(item.metadata.description) ?? displayValue(item.metadata.notes);
    if (calendarName) entries.push(["캘린더", calendarName]);
    if (description) entries.push(["내용", description]);
    return entries;
  }
  const fields = item.source === "gmail"
    ? [["보낸사람", ["sender", "from", "sender_name"]], ["이메일", ["sender_email", "from_email"]], ["받은 시각", ["received_at", "received_at_ms", "date"]], ["내용", ["body", "snippet", "preview"]]] as const
    : item.source === "tasks"
      ? [["상태", ["task_status", "status"]], ["예정일", ["scheduled_date", "due"]], ["내용", ["notes", "description"]]] as const
      : [["시작", ["start"]], ["종료", ["end"]], ["내용", ["description", "notes"]]] as const;
  return fields.flatMap(([label, keys]) => {
    for (const key of keys) {
      const value = displayValue(item.metadata[key]);
      if (value) return [[label, value] as [string, string]];
    }
    return [];
  });
}

function displayValue(value: unknown): string | null {
  if (typeof value === "string" || typeof value === "number") {
    const result = String(value).trim();
    return result && !(/^[a-z0-9_-]{12,}$/i.test(result) && !result.includes("@")) ? result : null;
  }
  if (Array.isArray(value)) return value.filter((entry): entry is string => typeof entry === "string" && entry.trim().length > 0).join(", ") || null;
  return null;
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
