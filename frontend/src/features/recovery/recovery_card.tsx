import type { RunSnapshot } from "../../api/contract";

type RecoveryProjection = NonNullable<RunSnapshot["recovery"]>;

export function RecoveryCard({ snapshot, busy, onResolve, onErrorAction = () => undefined }: { snapshot: RunSnapshot; busy: string | null; onResolve: (kind: RecoveryProjection["allowed_resolution_kinds"][number]) => void; onErrorAction?: (kind: "REAUTHENTICATE_GOOGLE" | "OPEN_SETTINGS" | "OPEN_DIAGNOSTICS") => void }): JSX.Element | null {
  const recovery = snapshot.recovery;
  if (!recovery && !snapshot.error) return null;
  return (
    <article className="info-card">
      <strong>Recovery</strong>
      {recovery ? <><p>{recovery.reason_code}</p><div className="button-row">{recovery.allowed_resolution_kinds.map((kind) => <button className="button-secondary" type="button" key={kind} disabled={busy === `recovery-${kind}`} onClick={() => onResolve(kind)}>{resolutionLabel(kind)}</button>)}</div></> : null}
      {snapshot.error ? <><p className="status-warn">{snapshot.error.message}</p><div className="button-row">{snapshot.error.actions.filter((action) => action.kind === "REAUTHENTICATE_GOOGLE" || action.kind === "OPEN_SETTINGS" || action.kind === "OPEN_DIAGNOSTICS").map((action) => <button className="button-secondary" type="button" key={action.kind} onClick={() => onErrorAction(action.kind as "REAUTHENTICATE_GOOGLE" | "OPEN_SETTINGS" | "OPEN_DIAGNOSTICS")}>{errorActionLabel(action.kind)}</button>)}</div></> : null}
    </article>
  );
}

function errorActionLabel(kind: string): string {
  return ({ REAUTHENTICATE_GOOGLE: "Google 재인증", OPEN_SETTINGS: "설정 열기", OPEN_DIAGNOSTICS: "진단 보기" } as Record<string, string>)[kind] ?? kind;
}

function resolutionLabel(kind: RecoveryProjection["allowed_resolution_kinds"][number]): string {
  return ({ RECHECK: "다시 확인", ACCEPT_PARTIAL: "현재 결과 수용", CREATE_CORRECTIVE_PLAN: "교정 계획 만들기", CANCEL: "취소", FAIL: "실패로 종료" } as const)[kind];
}
