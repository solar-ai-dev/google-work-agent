import { requestJson } from "../../../api/client";

export type GoogleConnection = {
  schema_version: 1;
  connector_id: string;
  account_id: string | null;
  display_email: string | null;
  connection_status: "CONNECTING" | "CONNECTED" | "DISCONNECTED" | "REAUTH_REQUIRED" | "UNAVAILABLE";
  granted_scopes: string[];
  missing_required_scopes: string[];
};

export type CurrentGoogleAccount = {
  account: { account_id: string; email: string; display_name?: string | null } | null;
  api_contract_version: string;
};

export function getGoogleConnection(): Promise<GoogleConnection> {
  return requestJson("/api/v1/connections/google/status");
}

export function getCurrentGoogleAccount(): Promise<CurrentGoogleAccount> {
  return requestJson("/api/v1/identity/google-account");
}

export function startGoogleConnection(commandId: string): Promise<{ schema_version: 1; authorization_url: string; callback_id: string }> {
  return requestJson("/api/v1/connections/google/start", { method: "POST", body: { schema_version: 1, command_id: commandId } });
}

export function disconnectGoogle(commandId: string): Promise<{ schema_version: 1; revocation_attempted: boolean; local_credential_deleted: boolean; connection_status: "DISCONNECTED" | "UNAVAILABLE" }> {
  return requestJson("/api/v1/connections/google/disconnect", { method: "POST", body: { schema_version: 1, command_id: commandId } });
}
