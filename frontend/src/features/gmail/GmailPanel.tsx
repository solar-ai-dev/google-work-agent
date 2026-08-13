import type { ResourceItem } from "../../api/contract";
import type { GmailController } from "./useGmail";

type ResourcePresentation = {
  title: string | null;
  secondary: string | null;
  snippet: string | null;
  time: string | null;
};

type GmailPanelProps = {
  gmail: GmailController;
  selection: {
    selectedResourceIds: string[];
    focusedResourceId: string | null;
    onToggleResource: (resourceId: string) => void;
    onFocusResource: (item: ResourceItem) => void;
  };
  pagination: {
    pageIndexes: number[];
    hasNextPage: boolean;
    onGoToPage: (pageIndex: number) => void;
  };
  presentResource: (item: ResourceItem) => ResourcePresentation;
};

export function GmailPanel({ gmail, selection, pagination, presentResource }: GmailPanelProps): JSX.Element {
  const visiblePageIndex = gmail.loading ? gmail.lastLoadedPageIndex : gmail.pageIndex;
  const items = gmail.pages[visiblePageIndex]?.items ?? [];
  const loadingMessage = gmail.loading && gmail.pageIndex !== gmail.lastLoadedPageIndex
    ? `${gmail.pageIndex + 1}페이지를 불러오는 중입니다.`
    : "자료를 불러오는 중입니다.";

  return (
    <>
      <div className="resource-search-row">
        <label className="resource-search">
          <svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <circle cx="10.5" cy="10.5" r="5.75" />
            <path d="m15 15 4.25 4.25" />
          </svg>
          <input
            aria-label="메일 검색"
            placeholder="검색 (제목, 보낸사람, 내용)"
            value={gmail.searchInput}
            onChange={(event) => gmail.setSearchInput(event.target.value)}
          />
        </label>
      </div>
      {gmail.loading ? (
        <div className="resource-load-status" aria-live="polite">
          <p className="muted">{loadingMessage}</p>
        </div>
      ) : null}
      {gmail.error ? <p className="status-bad">{gmail.error}</p> : null}
      {!gmail.loading && !gmail.error && items.length === 0 ? <p className="muted">표시할 자료가 없습니다.</p> : null}
      <div className="resource-content">
        <ul className="resource-list" aria-label="Google 업무 자료">
          {items.map((item) => {
            const selected = selection.selectedResourceIds.includes(item.resource_id);
            const focused = selection.focusedResourceId === item.resource_id;
            const presentation = presentResource(item);
            return (
              <li key={item.resource_id} className={`resource-item ${selected ? "selected" : ""} ${focused ? "focused" : ""}`}>
                <label className="resource-select-control" title="선택 요청에 포함">
                  <input
                    type="checkbox"
                    aria-label={`${presentation.title ?? "제목 없음"} 선택`}
                    checked={selected}
                    onChange={() => selection.onToggleResource(item.resource_id)}
                  />
                </label>
                <button className="resource-summary" type="button" aria-pressed={focused} onClick={() => selection.onFocusResource(item)}>
                  {(presentation.secondary || presentation.time) ? (
                    <span className="row-mail-meta">
                      {presentation.secondary ? <span className="row-sender">{presentation.secondary}</span> : null}
                      {presentation.time ? <span className="row-meta">{presentation.time}</span> : null}
                    </span>
                  ) : null}
                  <strong className="row-title">{presentation.title ?? "제목 없음"}</strong>
                  {presentation.snippet ? <span className="row-snippet">{presentation.snippet}</span> : null}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
      <nav className="pagination" aria-label="자료 페이지">
        <button className="button-secondary" type="button" disabled={gmail.pageIndex === 0} onClick={() => pagination.onGoToPage(gmail.pageIndex - 1)}>
          이전
        </button>
        {pagination.pageIndexes.map((index) => (
          <button key={index} className={index === gmail.pageIndex ? "button-primary" : "button-secondary"} type="button" onClick={() => pagination.onGoToPage(index)}>
            {index + 1}
          </button>
        ))}
        {pagination.hasNextPage ? (
          <button className="button-secondary" type="button" onClick={() => pagination.onGoToPage(gmail.pageIndex + 1)}>
            다음
          </button>
        ) : null}
      </nav>
    </>
  );
}
