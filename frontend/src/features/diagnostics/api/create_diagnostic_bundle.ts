import { requestJson } from "../../../api/client";

export type DiagnosticBundleMetadata = { schema_version: 1; bundle_ref: string; scope: "LAST_24H" | "RUN"; created_at_ms: number; size_bytes: number };

export function createDiagnosticBundle(commandId: string, scope: "LAST_24H" | "RUN", runId: string | null): Promise<DiagnosticBundleMetadata> {
  return requestJson("/api/v1/diagnostics/bundles", {
    method: "POST",
    body: { schema_version: 1, command_id: commandId, scope, run_id: scope === "RUN" ? runId : null },
  });
}
