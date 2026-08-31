import type { GmailAttachmentMetadata } from "../../api/contract";

export function AttachmentList({ messageId, attachments, onDownload }: { messageId: string; attachments: GmailAttachmentMetadata[]; onDownload: (messageId: string, attachmentId: string) => void }): JSX.Element | null {
  if (attachments.length === 0) return null;
  return (
    <section className="gmail-attachments" aria-label="첨부파일">
      <strong>첨부파일</strong>
      <ul>
        {attachments.map((attachment) => (
          <li key={`${messageId}:${attachment.attachment_id}`}>
            <button className="button-link" type="button" onClick={() => onDownload(messageId, attachment.attachment_id)}>{attachment.filename}</button>
            <small>{attachment.mime_type}{attachment.size_bytes !== null ? ` · ${formatFileSize(attachment.size_bytes)}` : ""}</small>
          </li>
        ))}
      </ul>
    </section>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
