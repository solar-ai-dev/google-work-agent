import { requestJson } from "../../../api/client";

export type StagedAttachmentDescriptor = {
  staged_attachment_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  expires_at_ms: number;
  api_contract_version: string;
};

export function stageAttachment(file: File, commandId: string): Promise<StagedAttachmentDescriptor> {
  const body = new FormData();
  body.set("command_id", commandId);
  body.set("file", file, file.name);
  return requestJson("/api/v1/attachments/stage", { method: "POST", body });
}
