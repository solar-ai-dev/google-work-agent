import { useEffect, useState } from "react";
import type { ContextPreview } from "../../api/contract";

type Props = {
  preview: ContextPreview;
  busy: boolean;
  onAdjust: (
    kind: "EXCLUDE_EVIDENCE" | "RETRIEVE_MORE",
    value: string[] | string,
  ) => Promise<void>;
};

export function ContextPreviewCard({ preview, busy, onAdjust }: Props): JSX.Element {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [requestedInformation, setRequestedInformation] = useState("");
  useEffect(() => {
    setSelected(new Set());
    setRequestedInformation("");
  }, [preview.retrieval_revision]);

  const canExclude = preview.adjustment_allowed
    && preview.allowed_adjustments.includes("EXCLUDE_EVIDENCE");
  const canRetrieveMore = preview.adjustment_allowed
    && preview.allowed_adjustments.includes("RETRIEVE_MORE");

  return (
    <article className="info-card" aria-label="사용 컨텍스트 미리보기">
      <strong>사용 컨텍스트</strong>
      <p className="muted">메일 {preview.gmail_count} · 태스크 {preview.tasks_count} · 일정 {preview.calendar_count} · revision {preview.retrieval_revision}</p>
      {preview.items.length ? (
        <ul className="card-list">
          {preview.items.map((item) => (
            <li key={item.segment_id} className="inline-row">
              {canExclude ? (
                <input
                  aria-label={`${item.display_label} 제외 선택`}
                  type="checkbox"
                  checked={selected.has(item.segment_id)}
                  onChange={(event) => setSelected((current) => {
                    const next = new Set(current);
                    if (event.target.checked) next.add(item.segment_id);
                    else next.delete(item.segment_id);
                    return next;
                  })}
                />
              ) : null}
              <span><strong>{item.display_label}</strong> <span className="pill">{item.source}</span></span>
              <span className="muted">{item.role}</span>
              {item.excerpt ? <span>{item.excerpt}</span> : null}
            </li>
          ))}
        </ul>
      ) : <p className="muted">현재 선택된 컨텍스트가 없습니다.</p>}
      {canExclude ? (
        <button
          className="button-secondary"
          type="button"
          disabled={busy || selected.size === 0}
          onClick={() => void onAdjust("EXCLUDE_EVIDENCE", [...selected])}
        >
          선택한 근거 제외
        </button>
      ) : null}
      {canRetrieveMore ? (
        <div>
          <label>추가로 필요한 정보<input value={requestedInformation} onChange={(event) => setRequestedInformation(event.target.value)} maxLength={2048} /></label>
          <button
            className="button-secondary"
            type="button"
            disabled={busy || !requestedInformation.trim()}
            onClick={() => void onAdjust("RETRIEVE_MORE", requestedInformation.trim())}
          >
            추가 자료 찾기
          </button>
        </div>
      ) : null}
    </article>
  );
}
