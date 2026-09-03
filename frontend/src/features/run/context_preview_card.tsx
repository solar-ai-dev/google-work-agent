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
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [requestedInformation, setRequestedInformation] = useState("");
  useEffect(() => {
    setSelected(new Set());
    setRequestedInformation("");
  }, [preview.retrieval_revision]);
  useEffect(() => {
    if (!open) return undefined;
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  const canExclude = preview.adjustment_allowed
    && preview.allowed_adjustments.includes("EXCLUDE_EVIDENCE");
  const canRetrieveMore = preview.adjustment_allowed
    && preview.allowed_adjustments.includes("RETRIEVE_MORE");
  const contextCount = preview.gmail_count + preview.tasks_count + preview.calendar_count;

  return (
    <div className="context-preview-anchor">
      <button className="context-preview-trigger" type="button" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>
        사용 컨텍스트 <strong>{contextCount}개</strong>
      </button>
      {open ? (
        <div className="context-modal-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target) setOpen(false); }}>
          <section className="context-modal" role="dialog" aria-modal="true" aria-labelledby="context-modal-title">
            <header>
              <div><strong id="context-modal-title">사용 컨텍스트 {contextCount}개</strong><p className="muted">메일 {preview.gmail_count} · 태스크 {preview.tasks_count} · 일정 {preview.calendar_count}</p></div>
              <button className="icon-button icon-button--plain" type="button" aria-label="사용 컨텍스트 닫기" onClick={() => setOpen(false)}>×</button>
            </header>
            {preview.items.length ? (
              <ul className="context-item-list">
                {preview.items.map((item) => (
                  <li key={item.segment_id}>
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
                    <span><strong>{item.display_label}</strong><span className="pill">{sourceLabel(item.source)}</span><span className="muted">{item.role}</span>{item.excerpt ? <span>{item.excerpt}</span> : null}</span>
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
              <div className="context-retrieve-more">
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
          </section>
        </div>
      ) : null}
    </div>
  );
}

function sourceLabel(source: ContextPreview["items"][number]["source"]): string {
  return ({ gmail: "메일", tasks: "태스크", calendar: "일정" } as const)[source];
}
