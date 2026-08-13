import { Fragment, useEffect, useRef, useState } from "react";
import type { ResourceItem } from "../../api/contract";
import type { TasksController } from "./useTasks";

type ResourcePresentation = { title: string | null; secondary: string | null; snippet: string | null; time: string | null };
type TaskSection = { key: string; label: string; items: ResourceItem[] };

type TasksPanelProps = {
  tasks: TasksController;
  filter: string;
  onFilterChange: (value: string) => void;
  selection: {
    selectedResourceIds: string[];
    focusedResourceId: string | null;
    onToggleResource: (resourceId: string) => void;
    onFocusResource: (item: ResourceItem) => void;
  };
  visibleItems: ResourceItem[];
  sections: TaskSection[] | null;
  pageIndexes: number[];
  hasNextPage: boolean;
  presentResource: (item: ResourceItem) => ResourcePresentation;
  pastDays: (item: ResourceItem) => number | null;
  formatCompletedAt: (item: ResourceItem) => string | null;
};

export function TasksPanel({ tasks, filter, onFilterChange, selection, visibleItems, sections, pageIndexes, hasNextPage, presentResource, pastDays, formatCompletedAt }: TasksPanelProps): JSX.Element {
  const [sortMenuOpen, setSortMenuOpen] = useState(false);
  const sortMenuRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!sortMenuOpen) return;
    const closeOnOutsidePointer = (event: MouseEvent): void => {
      if (!sortMenuRef.current?.contains(event.target as Node)) setSortMenuOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsidePointer);
    return () => document.removeEventListener("mousedown", closeOnOutsidePointer);
  }, [sortMenuOpen]);

  const renderItem = (item: ResourceItem): JSX.Element => {
    const selected = selection.selectedResourceIds.includes(item.resource_id);
    const focused = selection.focusedResourceId === item.resource_id;
    const presentation = presentResource(item);
    const overdueDays = tasks.sort === "scheduled_date" ? pastDays(item) : null;
    return (
      <li key={item.resource_id} className={`resource-item task-resource-item ${selected ? "selected" : ""} ${focused ? "focused" : ""}`}>
        <label className="resource-select-control" title="선택 항목에 포함">
          <input type="checkbox" aria-label={`${presentation.title ?? "제목 정보 없음"} 선택`} checked={selected} onChange={() => selection.onToggleResource(item.resource_id)} />
        </label>
        <button className="resource-summary" type="button" aria-pressed={focused} onClick={() => selection.onFocusResource(item)}>
          <span className="task-row-main">
            <strong className="row-title">{presentation.title ?? "제목 정보 없음"}</strong>
            {(tasks.sort !== "scheduled_date" && presentation.time) || overdueDays !== null ? <span className="row-meta task-row-date">{overdueDays !== null ? `${overdueDays}일 지남` : presentation.time}</span> : null}
          </span>
          {presentation.secondary ? <span className="row-secondary">{presentation.secondary}</span> : null}
          {presentation.snippet ? <span className="row-snippet">{presentation.snippet}</span> : null}
        </button>
      </li>
    );
  };

  return (
    <>
      <div className="resource-search-row">
        <label className="resource-search">
          <svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <circle cx="10.5" cy="10.5" r="5.75" />
            <path d="m15 15 4.25 4.25" />
          </svg>
          <input aria-label="작업 검색" placeholder="작업 검색" value={filter} onChange={(event) => onFilterChange(event.target.value)} />
        </label>
        <div className="task-sort-menu" ref={sortMenuRef}>
          <button aria-label="태스크 정렬 메뉴" aria-expanded={sortMenuOpen} aria-haspopup="menu" className="icon-button" type="button" onClick={() => setSortMenuOpen((current) => !current)}>⋮</button>
          {sortMenuOpen ? <div className="task-sort-popover" role="menu" aria-label="정렬 기준">
            <p>정렬 기준</p>
            {(["provider", "scheduled_date"] as const).map((sort) => <button key={sort} className="task-sort-option" role="menuitemradio" aria-checked={tasks.sort === sort} type="button" onClick={() => { setSortMenuOpen(false); tasks.setSort(sort); }}>
              <span aria-hidden="true">{tasks.sort === sort ? "✓" : ""}</span>{sort === "provider" ? "기본 순서" : "날짜순"}
            </button>)}
          </div> : null}
        </div>
      </div>
      {tasks.loading ? <div className="resource-load-status" aria-live="polite"><p className="muted">자료를 불러오는 중입니다.</p></div> : null}
      {tasks.error ? <p className="status-bad">{tasks.error}</p> : null}
      {!tasks.loading && !tasks.error && visibleItems.length === 0 ? <p className="muted">표시할 자료가 없습니다.</p> : null}
      <div className="task-content-scroll"><ul className={`resource-list ${sections ? "task-date-sorted" : ""}`} aria-label="Google 업무 자료">
        {sections ? sections.map((section, index) => <Fragment key={`${section.key}-${index}`}><li className={`task-date-section ${index > 0 ? "task-date-section-divider" : ""}`} aria-label={section.label}>{section.label}</li>{section.items.map(renderItem)}</Fragment>) : visibleItems.map(renderItem)}
      </ul>
      <section className="completed-tasks" aria-label="완료됨">
        <button className="completed-tasks-toggle" type="button" aria-expanded={tasks.completed.expanded} onClick={tasks.toggleCompleted}>완료됨{tasks.completed.initialized ? `(${tasks.completed.items.length})` : ""} {tasks.completed.expanded ? "▾" : "▸"}</button>
        {tasks.completed.expanded ? <div className="completed-tasks-content">
          {tasks.completed.loading ? <p className="muted">완료됨 로딩 중</p> : null}
          {tasks.completed.error ? <p className="status-bad">{tasks.completed.error}</p> : null}
          {!tasks.completed.loading && !tasks.completed.error && tasks.completed.initialized && tasks.completed.items.length === 0 ? <p className="muted">완료된 할 일이 없습니다.</p> : null}
          {tasks.completed.items.slice(0, (tasks.completed.pageIndex + 1) * 20).map((item) => <button key={item.resource_id} className="completed-task-row" type="button" onClick={() => selection.onFocusResource(item)}><span className="completed-task-title">✓ {presentResource(item).title ?? "제목 정보 없음"}</span>{formatCompletedAt(item) ? <span className="completed-task-date">완료일: {formatCompletedAt(item)}</span> : null}</button>)}
          {!tasks.completed.loading && !tasks.completed.error && tasks.completed.items.length > (tasks.completed.pageIndex + 1) * 20 ? <button className="button-secondary" type="button" onClick={tasks.showMoreCompleted}>더 보기</button> : null}
        </div> : null}
      </section>
      </div>
      <nav className="pagination" aria-label="자료 페이지">
        <button className="button-secondary" type="button" disabled={tasks.loading || tasks.pageIndex === 0} onClick={() => void tasks.loadPage(tasks.pageIndex - 1)}>이전</button>
        {pageIndexes.map((index) => <button key={index} className={index === tasks.pageIndex ? "button-primary" : "button-secondary"} type="button" disabled={tasks.loading} onClick={() => void tasks.loadPage(index)}>{index + 1}</button>)}
        {hasNextPage ? <button className="button-secondary" type="button" disabled={tasks.loading} onClick={() => void tasks.loadPage(tasks.pageIndex + 1)}>다음</button> : null}
      </nav>
    </>
  );
}
