import { requestJson } from "../../../api/client";

export type LlmCredentialStatus = {
  schema_version: 1;
  provider: string;
  configured: boolean;
  storage_mode: "KEYRING" | "SESSION_ONLY" | null;
  validation_status: "VALID" | "INVALID" | "UNAVAILABLE" | "NOT_CONFIGURED";
};

const PROVIDER = "gemini";

export function getLlmCredentialStatus(): Promise<LlmCredentialStatus> {
  return requestJson(`/api/v1/credentials/llm/${PROVIDER}`);
}

export function storeLlmCredential(commandId: string, apiKey: string, storageMode: "KEYRING" | "SESSION_ONLY"): Promise<LlmCredentialStatus> {
  return requestJson(`/api/v1/credentials/llm/${PROVIDER}`, {
    method: "PUT",
    body: { schema_version: 1, command_id: commandId, api_key: apiKey, storage_mode: storageMode },
  });
}

export function deleteLlmCredential(commandId: string): Promise<LlmCredentialStatus> {
  return requestJson(`/api/v1/credentials/llm/${PROVIDER}`, {
    method: "DELETE",
    body: { schema_version: 1, command_id: commandId },
  });
}
