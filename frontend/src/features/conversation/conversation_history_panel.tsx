import { useCallback, useRef, useState } from "react";
import { ApiClientError } from "../../api/client";
import type { ConversationHistoryResponse, ConversationItem, ConversationMessage } from "../../api/contract";
import { getConversationHistory, listConversations } from "./api/get_conversation_history";

type UseConversationHistoryProjectionOptions = {
  onStatusLine: (message: string) => void;
  onResetProjection: () => void;
};

export type ConversationProjectionIdentity = { conversationId: string | null; generation: number };

export function useConversationHistoryProjection({
  onStatusLine,
  onResetProjection,
}: UseConversationHistoryProjectionOptions) {
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [historyMessages, setHistoryMessages] = useState<ConversationMessage[]>([]);
  const projectionRef = useRef<ConversationProjectionIdentity>({ generation: 0, conversationId: null });
  const syncedRunIdsRef = useRef(new Set<string>());

  const refreshConversations = useCallback(async (): Promise<ConversationItem[]> => {
    const response = await listConversations();
    setConversations(response.items);
    return response.items;
  }, []);

  const beginConversationProjection = useCallback((conversationId: string | null): number => {
    const generation = projectionRef.current.generation + 1;
    projectionRef.current = { generation, conversationId };
    syncedRunIdsRef.current = new Set<string>();
    setSelectedConversationId(conversationId);
    setHistoryMessages([]);
    onResetProjection();
    return generation;
  }, [onResetProjection]);

  const getConversationProjection = useCallback((): ConversationProjectionIdentity => projectionRef.current, []);
  const isCurrentProjection = useCallback((conversationId: string, generation: number): boolean => (
    projectionRef.current.generation === generation && projectionRef.current.conversationId === conversationId
  ), []);

  const applyConversationHistory = useCallback((
    history: ConversationHistoryResponse,
    conversationId: string,
    generation: number,
  ): boolean => {
    if (!isCurrentProjection(conversationId, generation)) return false;
    setHistoryMessages(history.messages);
    for (const run of history.runs) {
      if (run.finished_at_ms !== null) syncedRunIdsRef.current.add(run.run_id);
    }
    return true;
  }, [isCurrentProjection]);

  const reloadConversationHistory = useCallback(async (conversationId: string, generation: number): Promise<void> => {
    try {
      applyConversationHistory(await getConversationHistory(conversationId), conversationId, generation);
    } catch (error) {
      if (isCurrentProjection(conversationId, generation)) {
        onStatusLine(error instanceof ApiClientError ? error.message : "이전 대화를 복구하지 못했습니다.");
      }
    }
  }, [applyConversationHistory, isCurrentProjection, onStatusLine]);

  const selectConversation = useCallback(async (
    conversationId: string,
    selectLatestRun: (runId: string, conversationId: string, generation: number) => Promise<void>,
  ): Promise<void> => {
    const generation = beginConversationProjection(conversationId);
    try {
      const history = await getConversationHistory(conversationId);
      if (!applyConversationHistory(history, conversationId, generation)) return;
      const latestRun = history.runs.at(-1);
      if (latestRun) await selectLatestRun(latestRun.run_id, conversationId, generation);
    } catch (error) {
      if (isCurrentProjection(conversationId, generation)) {
        onStatusLine(error instanceof ApiClientError ? error.message : "대화 실행 정보를 불러오지 못했습니다.");
      }
    }
  }, [applyConversationHistory, beginConversationProjection, isCurrentProjection, onStatusLine]);

  const isRunHistorySynced = useCallback((runId: string): boolean => syncedRunIdsRef.current.has(runId), []);
  const markRunHistorySynced = useCallback((runId: string): void => { syncedRunIdsRef.current.add(runId); }, []);

  return {
    conversations,
    selectedConversationId,
    historyMessages,
    refreshConversations,
    beginConversationProjection,
    getConversationProjection,
    isCurrentProjection,
    reloadConversationHistory,
    selectConversation,
    isRunHistorySynced,
    markRunHistorySynced,
  };
}

type ConversationHistoryPanelProps = {
  conversations: ConversationItem[];
  selectedConversationId: string | null;
  hasRunSnapshot: boolean;
  onBeginConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
};

export function ConversationHistoryPanel({
  conversations,
  selectedConversationId,
  hasRunSnapshot,
  onBeginConversation,
  onSelectConversation,
}: ConversationHistoryPanelProps): JSX.Element {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const visibleConversations = conversations.filter((conversation) => (
    (conversation.title ?? "").toLowerCase().includes(normalizedQuery)
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
            <li key={conversation.conversation_id} className={`conversation-item ${selectedConversationId === conversation.conversation_id ? "selected" : ""}`}>
              <button type="button" className="conversation-summary" onClick={() => onSelectConversation(conversation.conversation_id)}>
                <svg className="conversation-row-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <path d="M5.5 6.5h13v8h-7l-4 3.5v-3.5h-2z" />
                </svg>
                <span className="conversation-summary-content">
                  <span className="conversation-summary-header">
                    <strong>{conversation.title ?? "제목 없음"}</strong>
                    {conversation.latest_message_at_ms === null ? null : (
                      <span className="muted conversation-summary-time">{formatConversationTimestamp(conversation.latest_message_at_ms)}</span>
                    )}
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
