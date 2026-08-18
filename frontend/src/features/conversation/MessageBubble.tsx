export function DateSeparator({ label }: { label: string }): JSX.Element {
  return (
    <div className="date-separator" role="separator" aria-label={label}>
      <span>{label}</span>
    </div>
  );
}

export function UserMessageBubble({
  content,
  createdAtMs,
}: {
  content: string;
  createdAtMs?: number;
}): JSX.Element {
  return (
    <div className="message-row message-row--user">
      <p className="message-bubble message-bubble--user">{content}</p>
      {createdAtMs !== undefined ? (
        <span className="message-timestamp">{formatMessageTime(createdAtMs)}</span>
      ) : null}
    </div>
  );
}

function formatMessageTime(value: number): string {
  return new Date(value).toLocaleString("ko-KR", { hour: "numeric", minute: "2-digit", hour12: true });
}
