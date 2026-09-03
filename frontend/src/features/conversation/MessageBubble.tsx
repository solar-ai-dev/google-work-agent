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

export function AssistantMessageBubble({
  content,
  createdAtMs,
}: {
  content: string;
  createdAtMs: number;
}): JSX.Element {
  return (
    <article className="message-row message-row--assistant" aria-label="에이전트 응답">
      <p className="message-bubble message-bubble--assistant">{content}</p>
      <span className="message-timestamp">{formatMessageTime(createdAtMs)}</span>
    </article>
  );
}

function formatMessageTime(value: number): string {
  return new Date(value).toLocaleString("ko-KR", { hour: "numeric", minute: "2-digit", hour12: true });
}
