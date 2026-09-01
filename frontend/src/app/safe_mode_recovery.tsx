import { useEffect, useRef, useState } from "react";
import { ApiClientError } from "../api/client";
import {
  listBackups,
  requestShutdown,
  restoreBackup,
  type BackupMetadata,
} from "../features/settings/api/backup_operations";

type Props = {
  reason: string;
  onRetry: () => void;
};

export function SafeModeRecovery({ reason, onRetry }: Props): JSX.Element {
  const [backups, setBackups] = useState<BackupMetadata[]>([]);
  const [backupRef, setBackupRef] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const commandIds = useRef(new Map<string, string>());

  useEffect(() => {
    void listBackups()
      .then((response) => setBackups(response.items))
      .catch((error: unknown) => setMessage(errorMessage(error, "백업 목록을 불러오지 못했습니다.")));
  }, []);

  function commandIdFor(operation: string): string {
    let commandId = commandIds.current.get(operation);
    if (!commandId) {
      commandId = crypto.randomUUID();
      commandIds.current.set(operation, commandId);
    }
    return commandId;
  }

  async function restore(): Promise<void> {
    if (!backupRef || !confirmed) return;
    const operation = `safe-mode:restore:${backupRef}`;
    setBusy(true);
    setMessage(null);
    try {
      const result = await restoreBackup(commandIdFor(operation), backupRef);
      if (result.status !== "RESTORED") throw new Error(result.detail_code ?? "Restore rejected");
      commandIds.current.delete(operation);
      setMessage("복원·Migration·준비 상태 확인이 완료되었습니다.");
      onRetry();
    } catch (error) {
      setMessage(errorMessage(error, "복원 처리를 완료하지 못했습니다."));
    } finally {
      setBusy(false);
    }
  }

  async function shutdown(): Promise<void> {
    const operation = "safe-mode:shutdown";
    setBusy(true);
    setMessage(null);
    try {
      const result = await requestShutdown(commandIdFor(operation));
      if (!result.accepted) throw new Error("Shutdown rejected");
      commandIds.current.delete(operation);
      setMessage("안전한 종료를 요청했습니다.");
    } catch (error) {
      setMessage(errorMessage(error, "종료를 요청하지 못했습니다."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="startup">
      <section className="startup-card" aria-label="Safe Mode 복구">
        <h1>Google Work Agent Safe Mode</h1>
        <p>일반 Run과 Write는 차단되어 있습니다. 백업 복원 또는 안전 종료를 사용할 수 있습니다.</p>
        <p className="status-warn">{reason}</p>
        {message ? <p role="status">{message}</p> : null}
        <section className="info-card" aria-label="Safe Mode 백업 복원">
          <strong>백업 복원</strong>
          <select aria-label="복원할 백업" value={backupRef} onChange={(event) => { setBackupRef(event.target.value); setConfirmed(false); }}>
            <option value="">백업 선택</option>
            {backups.map((backup) => <option key={backup.backup_ref} value={backup.backup_ref}>{new Date(backup.created_at_ms).toLocaleString("ko-KR")} · {backup.size_bytes} bytes</option>)}
          </select>
          <label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />선택한 백업으로 복원함을 확인합니다.</label>
          <div className="button-row">
            <button className="button-danger" type="button" disabled={busy || !backupRef || !confirmed} onClick={() => void restore()}>복원 처리</button>
            <button className="button-secondary" type="button" disabled={busy} onClick={onRetry}>준비 상태 다시 확인</button>
          </div>
        </section>
        <button className="button-danger" type="button" disabled={busy} onClick={() => void shutdown()}>안전하게 종료</button>
      </section>
    </main>
  );
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiClientError ? error.message : fallback;
}
