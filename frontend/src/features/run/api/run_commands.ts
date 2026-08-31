import { API_CONTRACT_VERSION, type RunCommandResponse } from "../../../api/contract";
import { requestJson } from "../../../api/client";

export function cancelRun(payload: { run_id: string; command_id: string; expected_version: number }): Promise<RunCommandResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(payload.run_id)}/cancel`, {
    method: "POST",
    body: { command_id: payload.command_id, expected_version: payload.expected_version, api_contract_version: API_CONTRACT_VERSION },
  });
}

export function resumeRun(payload: { run_id: string; command_id: string; expected_version: number; resume_kind: "REAUTH_COMPLETED" | "SAFE_CHECKPOINT_RESUME" | "RECOVERY_RECHECK" }): Promise<RunCommandResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(payload.run_id)}/resume`, {
    method: "POST",
    body: { command_id: payload.command_id, expected_version: payload.expected_version, resume_kind: payload.resume_kind, api_contract_version: API_CONTRACT_VERSION },
  });
}

export function confirmRun(payload: { run_id: string; command_id: string; expected_version: number; interrupt_id: string; response_kind: "OPTION" | "FREE_TEXT" | "DECLINE"; selected_option?: string | null; free_text?: string | null }): Promise<RunCommandResponse> {
  return requestJson(`/api/v1/runs/${encodeURIComponent(payload.run_id)}/confirm`, {
    method: "POST",
    body: { command_id: payload.command_id, expected_version: payload.expected_version, interrupt_id: payload.interrupt_id, response_kind: payload.response_kind, selected_option: payload.selected_option ?? null, free_text: payload.free_text ?? null, api_contract_version: API_CONTRACT_VERSION },
  });
}
