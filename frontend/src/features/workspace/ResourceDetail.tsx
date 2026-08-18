import type { GmailResourceDetailResponse, ResourceItem } from "../../api/contract";

export type GmailDetailState = {
  resourceId: string | null;
  status: "idle" | "loading" | "ready" | "error";
  detail: GmailResourceDetailResponse | null;
  error: string | null;
};

export type ResourceDetailProps = {
  focusItem: ResourceItem | null;
  gmailDetail: GmailDetailState;
  onRetryGmailDetail: () => void;
  onDrillInto: () => void;
  presentResource: (item: ResourceItem) => {
    title: string | null;
    secondary: string | null;
    snippet: string | null;
    time: string | null;
  };
  metadataEntriesFor: (item: ResourceItem) => Array<[string, string]>;
  emptyMessage: string;
  formatMailboxIdentity: (name: string | null, email: string | null) => string | null;
};

export function ResourceDetail({
  focusItem,
  gmailDetail,
  onRetryGmailDetail,
  onDrillInto,
  presentResource,
  metadataEntriesFor,
  emptyMessage,
  formatMailboxIdentity,
}: ResourceDetailProps): JSX.Element {
  const canonicalUrl = focusItem
    ? gmailDetail.detail?.resource_id === focusItem.resource_id
      ? gmailDetail.detail.canonical_url
      : focusItem.link_url
    : null;

  return (
    <section
      className={`resource-viewer${focusItem ? "" : " resource-viewer--empty"}`}
      aria-label="선택 자료 상세"
    >
      {focusItem ? (
        <div className="viewer-actions viewer-actions-floating">
          {canonicalUrl && hasCanonicalGoogleUrl(canonicalUrl) ? (
            <button
              className="icon-button"
              type="button"
              aria-label="원본 열기"
              title="원본 열기"
              onClick={() => window.open(safeGoogleLink(canonicalUrl), "_blank", "noopener,noreferrer")}
            >
              ↗
            </button>
          ) : null}
          {focusItem.resource_type === "task_list" || focusItem.resource_type === "calendar" ? (
            <button
              className="icon-button"
              type="button"
              aria-label="하위 자료 보기"
              title="하위 자료 보기"
              onClick={onDrillInto}
            >
              →
            </button>
          ) : null}
        </div>
      ) : (
        <div className="section-heading">
          <strong>자료 상세</strong>
        </div>
      )}
      {focusItem ? (
        focusItem.resource_type === "gmail_thread" ? (
          <GmailDetailViewer
            state={gmailDetail}
            onRetry={onRetryGmailDetail}
            formatMailboxIdentity={formatMailboxIdentity}
          />
        ) : (
          <>
            <h2>{presentResource(focusItem).title ?? "제목 없음"}</h2>
            {presentResource(focusItem).secondary ? <p>{presentResource(focusItem).secondary}</p> : null}
            {metadataEntriesFor(focusItem).length > 0 ? (
              <dl className="metadata-list">
                {metadataEntriesFor(focusItem).map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="muted">현재 목록에서 제공된 상세 정보가 없습니다.</p>
            )}
          </>
        )
      ) : (
        <p className="muted">{emptyMessage}</p>
      )}
    </section>
  );
}

function GmailDetailViewer({
  state,
  onRetry,
  formatMailboxIdentity,
}: {
  state: GmailDetailState;
  onRetry: () => void;
  formatMailboxIdentity: (name: string | null, email: string | null) => string | null;
}): JSX.Element {
  if (state.status === "loading") {
    return (
      <div className="viewer-state" role="status">
        메일 내용을 불러오는 중입니다.
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="viewer-state" role="alert">
        <p>{state.error ?? "메일 내용을 불러오지 못했습니다."}</p>
        <button className="button-secondary" type="button" onClick={onRetry}>
          다시 시도
        </button>
      </div>
    );
  }
  if (state.status !== "ready" || !state.detail) {
    return <div className="viewer-state">메일 내용을 선택해 주세요.</div>;
  }

  const detail = state.detail;
  const sender = formatMailboxIdentity(detail.sender_name, detail.sender_email);
  const receivedAt = formatDetailDate(detail.received_at);
  return (
    <article className="gmail-detail">
      <header className="gmail-detail-header">
        <div className="gmail-detail-sender">
          {sender ? <strong>{sender}</strong> : <strong className="muted">보낸 사람 정보가 없습니다.</strong>}
          <div className="gmail-detail-meta">
            {detail.recipients.length > 0 ? <span>받는 사람 {detail.recipients.join(", ")}</span> : null}
            {detail.cc.length > 0 ? <span>참조 {detail.cc.join(", ")}</span> : null}
            {receivedAt ? <time>{receivedAt}</time> : null}
          </div>
        </div>
        {detail.subject ? <h2>{detail.subject}</h2> : null}
      </header>
      {detail.body ? (
        <div className="gmail-detail-body">{detail.body}</div>
      ) : (
        <p className="viewer-empty">표시할 메일 내용이 없습니다.</p>
      )}
      {detail.attachments.length > 0 ? (
        <section className="gmail-attachments" aria-label="첨부파일">
          <strong>첨부파일</strong>
          <ul>
            {detail.attachments.map((attachment) => (
              <li key={`${attachment.message_id}:${attachment.attachment_id}`}>
                <span>{attachment.filename}</span>
                <small>
                  {attachment.mime_type}
                  {attachment.size_bytes !== null ? ` · ${formatFileSize(attachment.size_bytes)}` : ""}
                </small>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
}

function formatDetailDate(value: string | null): string | null {
  const date = parsedResourceDate(value);
  return (
    date?.toLocaleString("ko-KR", {
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "short",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    }) ?? null
  );
}

function parsedResourceDate(value: string | null): Date | null {
  if (!value) return null;
  const milliseconds = /^\d{12,}$/.test(value) ? Number(value) : Date.parse(value);
  if (!Number.isFinite(milliseconds)) return null;
  const date = new Date(milliseconds);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatFileSize(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${Math.round(sizeBytes / 1024)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

function safeGoogleLink(url: string): string {
  if (!hasCanonicalGoogleUrl(url)) {
    return "https://calendar.google.com/";
  }
  return new URL(url).toString();
}

function hasCanonicalGoogleUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    const allowedHosts = new Set(["mail.google.com", "tasks.google.com", "calendar.google.com"]);
    return parsed.protocol === "https:" && allowedHosts.has(parsed.host);
  } catch {
    return false;
  }
}
