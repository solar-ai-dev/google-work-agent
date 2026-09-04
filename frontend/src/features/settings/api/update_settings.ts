import { requestJson } from "../../../api/client";
import type { SettingsView } from "./get_settings";

export type SettingsPatch = Partial<
  Omit<SettingsView, "schema_version" | "preferred_local_model_id">
>;

export function updateSettings(commandId: string, settingsPatch: SettingsPatch): Promise<SettingsView> {
  return requestJson("/api/v1/settings", {
    method: "PUT",
    body: { schema_version: 1, command_id: commandId, settings_patch: { schema_version: 1, ...settingsPatch } },
  });
}
