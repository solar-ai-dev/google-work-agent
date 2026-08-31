import { requestJson } from "../../../api/client";

export type BackupMetadata = { schema_version: 1; backup_ref: string; created_at_ms: number; size_bytes: number; manifest_hash: string };
export type RestoreResult = { schema_version: 1; backup_ref: string; status: "RESTORED" | "REJECTED"; detail_code: string | null };

export function listBackups(): Promise<{ schema_version: 1; items: BackupMetadata[] }> {
  return requestJson("/api/v1/backups");
}

export function createBackup(commandId: string): Promise<BackupMetadata> {
  return requestJson("/api/v1/backups", { method: "POST", body: { schema_version: 1, command_id: commandId } });
}

export function restoreBackup(commandId: string, backupRef: string): Promise<RestoreResult> {
  return requestJson("/api/v1/restore", { method: "POST", body: { schema_version: 1, command_id: commandId, backup_ref: backupRef } });
}
