import { API_CONTRACT_VERSION, type RunCommandResponse, type RunSnapshot } from "../../../api/contract";
import { requestJson } from "../../../api/client";

type RecoveryProjection = NonNullable<RunSnapshot["recovery"]>;

export function resolveRecovery(payload: { run_id: string; command_id: string; expected_version: number; target: RecoveryProjection["target"]; resolution_kind: RecoveryProjection["allowed_resolution_kinds"][number] }): Promise<RunCommandResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(payload.run_id)}/resolve-recovery`, {
    method: "POST",
    body: { command_id: payload.command_id, expected_version: payload.expected_version, target: payload.target, resolution_kind: payload.resolution_kind, api_contract_version: API_CONTRACT_VERSION },
  });
}
