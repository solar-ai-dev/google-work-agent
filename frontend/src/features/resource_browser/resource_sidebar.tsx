import { useCallback, useEffect, useMemo, useState } from "react";
import type { ResourceItem } from "../../api/contract";
import { CalendarPanel } from "./calendar_panel";
import { GmailPanel } from "./gmail_panel";
import { TasksPanel } from "./tasks_panel";
import { useCalendar } from "./calendar_controller";
import { useGmail } from "./gmail_controller";
import { useTasks } from "./tasks_controller";
import { buildSelectedResourceContext, type SelectedResourceContext } from "./selected_resource_context";

export type ResourceSource = "gmail" | "tasks" | "calendar";

export type ResourceBrowserProjection = {
  activeSource: ResourceSource;
  focusedItem: ResourceItem | null;
  selectedContext: SelectedResourceContext;
  composerPrompt: string;
  emptyMessage: string;
  focusedItemSelected: boolean;
  toggleFocusedSelection: () => void;
  openFocusedContainer: () => void;
};

type Props = {
  scopeKey: string;
  accountId: string | null | undefined;
  connected: boolean;
  timezone: string;
  onProjectionChange: (projection: ResourceBrowserProjection) => void;
};

const PAGE_SIZE = 20;

export function ResourceSidebar({ scopeKey, accountId, connected, timezone, onProjectionChange }: Props): JSX.Element {
  const [source, setSource] = useState<ResourceSource>("gmail");
  const [filter, setFilter] = useState("");
  const [focusedItem, setFocusedItem] = useState<ResourceItem | null>(null);
  const [selectedItems, setSelectedItems] = useState<ResourceItem[]>([]);
  const [parentId, setParentId] = useState<string | null>(null);
  const gmail = useGmail({ accountId, active: source === "gmail" });
  const tasks = useTasks({ accountId, parentId, active: source === "tasks", filter });
  const calendar = useCalendar({ accountId, calendarId: parentId, active: connected && source === "calendar", timezone });
  const { reset: resetGmail, loadCount: loadGmailCount, loadPage: loadGmailPage } = gmail;
  const { reset: resetTasks, preload: preloadTasks, loadCompleted: loadCompletedTasks, loadPage: loadTasksPage } = tasks;
  const { reset: resetCalendar } = calendar;
  const selectedContext = useMemo(
    () => buildSelectedResourceContext(selectedItems, (item) => presentResource(item).title ?? "제목 없음"),
    [selectedItems],
  );
  const focusedItemSelected = focusedItem !== null && selectedContext.selectionHandles.includes(focusedItem.selection_handle);

  const toggleItem = useCallback((item: ResourceItem): void => {
    setSelectedItems((current) => current.some((selected) => selected.selection_handle === item.selection_handle)
      ? current.filter((selected) => selected.selection_handle !== item.selection_handle)
      : [...current, item]);
  }, []);
  const toggleByResourceId = useCallback((resourceId: string, items: ResourceItem[]): void => {
    const item = items.find((candidate) => candidate.resource_id === resourceId);
    if (item) toggleItem(item);
  }, [toggleItem]);
  const toggleFocusedSelection = useCallback((): void => {
    if (focusedItem) toggleItem(focusedItem);
  }, [focusedItem, toggleItem]);
  const openFocusedContainer = useCallback((): void => {
    if (focusedItem?.parent_id) setParentId(focusedItem.parent_id);
  }, [focusedItem]);

  useEffect(() => {
    resetGmail();
    resetTasks();
    resetCalendar();
    setSelectedItems([]);
    setFocusedItem(null);
    setParentId(null);
  }, [resetCalendar, resetGmail, resetTasks, scopeKey]);

  useEffect(() => {
    if (!connected) return;
    void loadGmailCount();
    void preloadTasks();
    void loadCompletedTasks();
  }, [connected, loadCompletedTasks, loadGmailCount, preloadTasks]);

  useEffect(() => {
    if (!connected || source !== "gmail") return;
    if (!gmail.loaded && !gmail.loading && gmail.error === null) void loadGmailPage(gmail.pageIndex);
    else if (gmail.loaded && !gmail.countLoading) void loadGmailCount();
  }, [connected, gmail.countLoading, gmail.error, gmail.loaded, gmail.loading, gmail.pageIndex, loadGmailCount, loadGmailPage, source]);

  useEffect(() => {
    if (!connected || source !== "tasks") return;
    if (!tasks.loaded && !tasks.loading && tasks.error === null) void loadTasksPage(tasks.pageIndex);
  }, [connected, loadTasksPage, source, tasks.error, tasks.loaded, tasks.loading, tasks.pageIndex]);

  useEffect(() => {
    if (source === "gmail" && !gmail.loaded) return;
    onProjectionChange({
      activeSource: source,
      focusedItem,
      selectedContext,
      composerPrompt: composerPrompt(source),
      emptyMessage: emptyMessage(source),
      focusedItemSelected,
      toggleFocusedSelection,
      openFocusedContainer,
    });
  }, [focusedItem, focusedItemSelected, gmail.loaded, onProjectionChange, openFocusedContainer, selectedContext, source, toggleFocusedSelection]);

  const visibleTaskItems = useMemo(() => {
    if (source !== "tasks") return [];
    const items = filter.trim()
      ? tasks.items.filter((item) => Object.values(presentResource(item)).filter(Boolean).some((value) => value!.toLocaleLowerCase("ko-KR").includes(filter.trim().toLocaleLowerCase("ko-KR"))))
      : tasks.items;
    return items.slice(tasks.pageIndex * PAGE_SIZE, (tasks.pageIndex + 1) * PAGE_SIZE);
  }, [filter, source, tasks.items, tasks.pageIndex]);
  const taskSections = useMemo(() => source === "tasks" && tasks.sort === "scheduled_date" ? groupTasksByScheduledDate(visibleTaskItems) : null, [source, tasks.sort, visibleTaskItems]);

  return (
    <aside className="panel resource-panel">
      <div className="panel-body">
        <div className="resource-tabbar">
          <div className="resource-tabs" role="tablist" aria-label="자료 종류">
            {(["gmail", "tasks", "calendar"] as ResourceSource[]).map((tab) => <button key={tab} className={`resource-tab ${source === tab ? "selected" : ""}`} type="button" role="tab" aria-selected={source === tab} onClick={() => { setFilter(""); setSource(tab); setParentId(null); setFocusedItem(null); }}><span className="resource-tab-icon" aria-hidden="true">{tabIcon(tab)}</span><span className="resource-tab-label">{tabLabel(tab)}</span>{tab !== "calendar" ? <span className="resource-tab-count">{formatCount(tab === "gmail" ? gmail.count : tasks.count)}</span> : null}</button>)}
          </div>
          <button className="icon-button" type="button" aria-label="현재 목록 새로고침" title="새로고침" onClick={() => { if (source === "gmail") void gmail.refresh(); else if (source === "tasks") void tasks.refresh(); else void calendar.refresh(); }}>↻</button>
        </div>
        {source === "gmail" ? <GmailPanel gmail={gmail} selection={{ selectedResourceIds: selectedContext.resourceIds, focusedResourceId: focusedItem?.resource_id ?? null, onToggleResource: (resourceId) => toggleByResourceId(resourceId, gmail.items), onFocusResource: setFocusedItem }} pagination={{ pageIndexes: pageIndexes(gmail.pageIndex, gmail.totalCount, gmail.items.length), hasNextPage: gmail.pageIndex + 1 < pageCount(gmail.totalCount, gmail.items.length) || (gmail.totalCount === null && gmail.nextPageToken !== null), onGoToPage: (pageIndex) => void gmail.loadPage(pageIndex) }} presentResource={presentResource} /> : null}
        {source === "tasks" ? <TasksPanel tasks={tasks} filter={filter} onFilterChange={setFilter} selection={{ selectedResourceIds: selectedContext.resourceIds, focusedResourceId: focusedItem?.resource_id ?? null, onToggleResource: (resourceId) => toggleByResourceId(resourceId, tasks.items), onFocusResource: setFocusedItem }} visibleItems={visibleTaskItems} sections={taskSections} pageIndexes={pageIndexes(tasks.pageIndex, tasks.totalCount, tasks.items.length)} hasNextPage={tasks.pageIndex + 1 < pageCount(tasks.totalCount, tasks.items.length) || (tasks.totalCount === null && tasks.nextPageToken !== null)} presentResource={presentResource} pastDays={pastScheduledDays} formatCompletedAt={(item) => formatCompletedTaskDate(item.metadata.completed_at ?? null, timezone)} /> : null}
        {source === "calendar" ? <CalendarPanel calendar={calendar} timezone={timezone} filter={filter} onFilterChange={setFilter} onFocusEvent={setFocusedItem} /> : null}
      </div>
    </aside>
  );
}

export function presentResource(item: ResourceItem): { title: string | null; secondary: string | null; snippet: string | null; time: string | null } {
  const metadata = item.metadata;
  const title = item.title.trim() || null;
  if (item.source === "calendar") return { title, secondary: calendarRange(metadata.start ?? null, metadata.end ?? null), snippet: null, time: null };
  if (item.source === "tasks") return { title, secondary: null, snippet: null, time: formatTaskDate(metadata.scheduled_date ?? null) };
  const sender = text(item.sender_name) ?? text(metadata.sender_name);
  const email = text(item.sender_email) ?? text(metadata.sender_email);
  return { title, secondary: mailbox(sender, email), snippet: text(item.snippet) ?? text(metadata.snippet), time: sidebarDate(text(item.received_at) ?? text(metadata.received_at)) };
}

function pageCount(total: number | null, loaded: number): number { return Math.ceil((total ?? loaded) / PAGE_SIZE); }
function pageIndexes(current: number, total: number | null, loaded: number): number[] { const count = pageCount(total, loaded); const first = Math.max(0, Math.min(current - 2, count - 5)); return Array.from({ length: Math.min(5, count) }, (_, index) => first + index); }
function formatCount(count: { value: number; exact: boolean } | null): string { return count === null ? "" : `${count.value}${count.exact ? "" : "+"}`; }
function tabLabel(source: ResourceSource): string { return { gmail: "메일", tasks: "태스크", calendar: "캘린더" }[source]; }
function tabIcon(source: ResourceSource): string { return { gmail: "✉", tasks: "✓", calendar: "▦" }[source]; }
function composerPrompt(source: ResourceSource): string { return source === "tasks" ? "선택한 태스크에 대해 질문하거나 업무를 요청하세요..." : source === "calendar" ? "선택한 일정에 대해 질문하거나 업무를 요청하세요..." : "선택한 메일에 대해 질문하거나 업무를 요청하세요..."; }
function emptyMessage(source: ResourceSource): string { return source === "tasks" ? "왼쪽 목록에서 태스크를 선택하면 상세 내용을 확인할 수 있습니다." : source === "calendar" ? "왼쪽 목록에서 일정을 선택하면 상세 내용을 확인할 수 있습니다." : "왼쪽 목록에서 메일을 선택하면 상세 내용을 확인할 수 있습니다."; }
function text(value: unknown): string | null { if (typeof value !== "string" && typeof value !== "number") return null; return String(value).trim() || null; }
function mailbox(name: string | null, email: string | null): string | null { return name && email && name !== email ? `${name} <${email}>` : name ?? (email ? `<${email}>` : null); }
function parsedDate(value: string | null): Date | null { if (!value) return null; const milliseconds = /^\d{12,}$/.test(value) ? Number(value) : Date.parse(value); if (!Number.isFinite(milliseconds)) return null; const date = new Date(milliseconds); return Number.isNaN(date.getTime()) ? null : date; }
function sidebarDate(value: string | null, now = new Date()): string | null { const date = parsedDate(value); if (!date) return null; const days = Math.round((new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() - new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()) / 86_400_000); if (days === 0) return date.toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit", hour12: true }); if (days === 1) return "어제"; return date.toLocaleDateString("ko-KR", date.getFullYear() === now.getFullYear() ? { month: "long", day: "numeric" } : { year: "numeric", month: "2-digit", day: "2-digit" }); }
function calendarRange(start: string | null, end: string | null): string | null { const startDate = parsedDate(start); const endDate = parsedDate(end); if (/^\d{4}-\d{2}-\d{2}$/.test(start ?? "")) return start ? `${formatTaskDate(start)} · 하루 종일` : null; if (startDate && endDate) return `${startDate.toLocaleString("ko-KR")} - ${endDate.toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit", hour12: true })}`; return startDate?.toLocaleString("ko-KR") ?? endDate?.toLocaleString("ko-KR") ?? null; }
function formatTaskDate(value: string | null): string | null { if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null; const [year, month, day] = value.split("-").map(Number); const date = new Date(year, month - 1, day); return `${date.toLocaleDateString("ko-KR", { month: "long", day: "numeric" })} (${date.toLocaleDateString("ko-KR", { weekday: "short" })})`; }
function formatCompletedTaskDate(value: string | null, timezone: string): string | null { const date = value ? new Date(value) : null; return date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString("ko-KR", { timeZone: timezone, month: "long", day: "numeric", weekday: "short" }) : null; }
function localDate(value: Date): string { return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`; }
function scheduledDate(item: ResourceItem): string | null { const value = item.metadata.scheduled_date; return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null; }
function pastScheduledDays(item: ResourceItem, now = new Date()): number | null { const scheduled = scheduledDate(item); if (!scheduled || item.metadata.task_status === "completed") return null; const [year, month, day] = scheduled.split("-").map(Number); const scheduledDay = Date.UTC(year, month - 1, day); const [todayYear, todayMonth, todayDay] = localDate(now).split("-").map(Number); const difference = (Date.UTC(todayYear, todayMonth - 1, todayDay) - scheduledDay) / 86_400_000; return difference > 0 ? difference : null; }
function groupTasksByScheduledDate(items: ResourceItem[], now = new Date()): Array<{ key: string; label: string; items: ResourceItem[] }> { const today = localDate(now); const tomorrow = localDate(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)); return items.reduce<Array<{ key: string; label: string; items: ResourceItem[] }>>((sections, item) => { const date = scheduledDate(item); const status = item.metadata.task_status; const key = !date ? "no-date" : date < today && status !== "completed" ? "past" : date === today ? "today" : date === tomorrow ? "tomorrow" : `date:${date}`; const label = key === "past" ? "지난 날짜" : key === "today" ? "오늘" : key === "tomorrow" ? "내일" : key === "no-date" ? "날짜 없음" : formatTaskDate(date) ?? "날짜 없음"; const previous = sections.at(-1); if (previous?.key === key) previous.items.push(item); else sections.push({ key, label, items: [item] }); return sections; }, []); }
