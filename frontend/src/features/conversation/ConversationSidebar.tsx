import { useState } from "react";
import type { ConversationItem } from "../../api/contract";

type ConversationSidebarProps = {
  conversations: ConversationItem[];
  selectedConversationId: string | null;
  hasRunSnapshot: boolean;
  onBeginConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
};

export function ConversationSidebar({
  conversations,
  selectedConversationId,
  hasRunSnapshot,
  onBeginConversation,
  onSelectConversation,
}: ConversationSidebarProps): JSX.Element {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const visibleConversations = conversations.filter((conversation) => (
    conversation.title.toLowerCase().includes(normalizedQuery)
  ));

  return (
    <aside className="panel conversation-panel">
      <div className="panel-header">
        <strong>대화</strong>
        <button className="button-secondary" type="button" onClick={onBeginConversation}>
          <span aria-hidden="true">+</span> 새 대화
        </button>
      </div>
      <div className="panel-body">
        <label className="resource-search conversation-search">
          <svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <circle cx="10.5" cy="10.5" r="5.75" />
            <path d="m15 15 4.25 4.25" />
          </svg>
          <input aria-label="대화 검색" placeholder="대화 검색" value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <ul className="conversation-list">
          {visibleConversations.map((conversation) => (
            <li key={conversation.id} className={`conversation-item ${selectedConversationId === conversation.id ? "selected" : ""}`}>
              <button type="button" className="conversation-summary" onClick={() => onSelectConversation(conversation.id)}>
                <svg className="conversation-row-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <path d="M5.5 6.5h13v8h-7l-4 3.5v-3.5h-2z" />
                </svg>
                <span className="conversation-summary-content">
                  <span className="conversation-summary-header">
                    <strong>{conversation.title}</strong>
                    <span className="muted conversation-summary-time">{formatConversationTimestamp(conversation.updated_at_ms)}</span>
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
        {conversations.length === 0 ? <p className="muted">아직 대화가 없습니다.</p> : null}
        <section className="recent-execution">
          <strong>최근 실행</strong>
          {hasRunSnapshot ? <p className="muted">현재 대화의 실행 상태는 중앙 작업 공간에서 확인할 수 있습니다.</p> : <p className="muted">표시할 실행 기록이 없습니다.</p>}
        </section>
      </div>
    </aside>
  );
}

function formatConversationTimestamp(value: number, now = new Date()): string {
  const timestamp = new Date(value);
  const isToday = timestamp.getFullYear() === now.getFullYear()
    && timestamp.getMonth() === now.getMonth()
    && timestamp.getDate() === now.getDate();

  return timestamp.toLocaleString("ko-KR", isToday
    ? { hour: "numeric", minute: "2-digit", hour12: true }
    : { month: "long", day: "numeric" });
}
