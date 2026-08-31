import { requestBlobResponse } from "../../../api/client";

export async function downloadAttachment(messageId: string, attachmentId: string): Promise<void> {
  const response = await requestBlobResponse(`/api/v1/gmail/messages/${encodeURIComponent(messageId)}/attachments/${encodeURIComponent(attachmentId)}`);
  const filename = safeFilename(response.contentDisposition) ?? "attachment";
  const objectUrl = URL.createObjectURL(response.blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.rel = "noopener";
    anchor.click();
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

function safeFilename(contentDisposition: string | null): string | null {
  const match = contentDisposition?.match(/(?:^|;)\s*filename="([^"]+)"/i);
  if (!match) return null;
  const value = match[1].trim();
  if (!value || value.length > 255 || value.includes("/") || value.includes("\\") || hasControlCharacter(value)) return null;
  return value;
}

function hasControlCharacter(value: string): boolean {
  return Array.from(value).some((character) => {
    const code = character.charCodeAt(0);
    return code < 32 || code === 127;
  });
}
