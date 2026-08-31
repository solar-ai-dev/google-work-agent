import { useRef, useState } from "react";
import { ApiClientError } from "../../api/client";
import { createDiagnosticBundle, type DiagnosticBundleMetadata } from "./api/create_diagnostic_bundle";
import type { RuntimeSummary } from "./api/get_runtime";

export function DiagnosticsPanel({ runtime, onRefresh }: { runtime: RuntimeSummary | null; onRefresh: () => Promise<void> }): JSX.Element {
  const [scope, setScope] = useState<"LAST_24H" | "RUN">("LAST_24H");
  const [runId, setRunId] = useState("");
  const [bundle, setBundle] = useState<DiagnosticBundleMetadata | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const commandIds = useRef(new Map<string, string>());

  async function createBundle(): Promise<void> {
    const normalizedRunId = runId.trim();
    if (scope === "RUN" && !normalizedRunId) {
      setMessage("실행 범위 진단에는 run ID가 필요합니다.");
      return;
    }
    const operation = `diagnostic-bundle:${scope}:${scope === "RUN" ? normalizedRunId : "last-24h"}`;
    let commandId = commandIds.current.get(operation);
    if (!commandId) {
      commandId = crypto.randomUUID();
      commandIds.current.set(operation, commandId);
    }
    setBusy(true);
    setMessage(null);
    try {
      const created = await createDiagnosticBundle(commandId, scope, scope === "RUN" ? normalizedRunId : null);
      setBundle(created);
      commandIds.current.delete(operation);
    } catch (error) {
      await onRefresh().catch(() => undefined);
      setMessage(error instanceof ApiClientError ? error.message : "진단 번들을 만들지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="info-card" aria-label="진단">
      <strong>진단</strong>
      <dl className="metadata-list">
        <div><dt>서비스</dt><dd>{runtime?.launcher_status ?? "-"}</dd></div>
        <div><dt>데이터베이스</dt><dd>{runtime?.database_status ?? "-"}</dd></div>
        <div><dt>마이그레이션</dt><dd>{runtime?.migration_status ?? "-"}</dd></div>
        <div><dt>SSE</dt><dd>{runtime?.sse_status ?? "-"}</dd></div>
        <div><dt>Manifest</dt><dd>{runtime?.manifest_status ?? "-"}</dd></div>
        <div><dt>Safe mode</dt><dd>{runtime?.safe_mode ? "ON" : "OFF"}</dd></div>
        <div><dt>최근 오류 코드</dt><dd>{runtime?.recent_sanitized_error_code ?? "없음"}</dd></div>
      </dl>
      <div className="button-row">
        <button className="button-secondary" type="button" disabled={busy} onClick={() => void onRefresh()}>상태 새로고침</button>
      </div>
      <label>범위
        <select value={scope} onChange={(event) => setScope(event.target.value === "RUN" ? "RUN" : "LAST_24H")}>
          <option value="LAST_24H">최근 24시간</option><option value="RUN">특정 실행</option>
        </select>
      </label>
      {scope === "RUN" ? <label>Run ID<input value={runId} onChange={(event) => setRunId(event.target.value)} /></label> : null}
      <button className="button-secondary" type="button" disabled={busy} onClick={() => void createBundle()}>진단 번들 만들기</button>
      {message ? <p role="alert" className="status-warn">{message}</p> : null}
      {bundle ? <p className="muted">Bundle ref: {bundle.bundle_ref} · {bundle.size_bytes} bytes · {new Date(bundle.created_at_ms).toLocaleString("ko-KR")}</p> : null}
    </section>
  );
}
