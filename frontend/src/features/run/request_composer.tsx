import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { ApiClientError } from "../../api/client";
import type { ConversationItem } from "../../api/contract";
import { startRun } from "./api/run_commands";

export type SubmitNewRunInput = {
  conversationId: string | null;
  requestText: string;
  selectionHandles: string[];
  conversationCommandId: string;
  runCommandId: string;
  requestedMode: "AUTO" | "LOCAL_GPU" | "API_LLM";
  createConversation: (payload: { command_id: string; title: string | null }) => Promise<ConversationItem>;
};

export type SubmitNewRunResult = { conversationId: string; runId: string; conversationCreated: boolean };

export async function submitNewRun(input: SubmitNewRunInput): Promise<SubmitNewRunResult> {
  const requestText = input.requestText.trim();
  if (!requestText) throw new Error("A non-empty request is required.");
  const selectionHandles = [...new Set(input.selectionHandles.map((handle) => handle.trim()).filter(Boolean))];
  if (selectionHandles.length > 20) throw new Error("At most 20 selected resources are allowed.");
  const conversation = input.conversationId === null
    ? await input.createConversation({ command_id: input.conversationCommandId, title: requestText.slice(0, 80) })
    : null;
  const conversationId = conversation?.conversation_id ?? input.conversationId;
  if (conversationId === null) throw new Error("Conversation identity is unavailable.");
  const run = await startRun({
    command_id: input.runCommandId,
    conversation_id: conversationId,
    request_text: requestText,
    entry_mode: selectionHandles.length > 0 ? "RESOURCE_SELECTED" : "AGENT_SEARCH",
    selected_resource_handles: selectionHandles,
    requested_mode: input.requestedMode,
  });
  return { conversationId, runId: run.run_id, conversationCreated: conversation !== null };
}

type RequestComposerControllerOptions = {
  currentAccountId: string | null;
  selectedConversationId: string | null;
  selectedResourceHandles: string[];
  busyCommand: string | null;
  setBusyCommand: Dispatch<SetStateAction<string | null>>;
  getProjectionGeneration: () => number;
  beginConversationProjection: (conversationId: string) => number;
  reloadConversationHistory: (conversationId: string, generation: number) => Promise<void>;
  refreshConversations: () => Promise<unknown>;
  selectRun: (runId: string, conversationId: string, generation: number) => Promise<void>;
  onStatusLine: (message: string) => void;
  commandIdFor: (operation: string) => string;
  completeCommand: (operation: string) => void;
  createConversation: SubmitNewRunInput["createConversation"];
  requestedMode: SubmitNewRunInput["requestedMode"];
};

export function useRequestComposerController(options: RequestComposerControllerOptions) {
  const [composerText, setComposerText] = useState("");
  const [composerError, setComposerError] = useState<string | null>(null);

  useEffect(() => setComposerError(null), [options.selectedConversationId]);

  const handleStartRun = useCallback(async (quickPrompt?: string): Promise<void> => {
    if (!options.currentAccountId) {
      const message = "현재 연결된 계정 정보를 찾지 못했습니다.";
      options.onStatusLine(message);
      setComposerError(message);
      return;
    }
    const requestText = quickPrompt ?? composerText;
    if (!requestText.trim() || options.busyCommand) return;
    options.setBusyCommand("start-run");
    setComposerError(null);
    const normalizedHandles = [...new Set(options.selectedResourceHandles.map((handle) => handle.trim()).filter(Boolean))];
    const operationIdentity = JSON.stringify({
      conversationId: options.selectedConversationId,
      requestText: requestText.trim(),
      selectionHandles: normalizedHandles,
    });
    const conversationOperation = `create-conversation:${operationIdentity}`;
    const runOperation = `start-run:${operationIdentity}`;
    try {
      let conversationId = options.selectedConversationId;
      let generation = options.getProjectionGeneration();
      const result = await submitNewRun({
        conversationId,
        requestText,
        selectionHandles: normalizedHandles,
        conversationCommandId: options.commandIdFor(conversationOperation),
        runCommandId: options.commandIdFor(runOperation),
        requestedMode: options.requestedMode,
        createConversation: options.createConversation,
      });
      conversationId = result.conversationId;
      if (result.conversationCreated) generation = options.beginConversationProjection(conversationId);
      await options.reloadConversationHistory(conversationId, generation);
      await options.refreshConversations();
      await options.selectRun(result.runId, conversationId, generation);
      options.completeCommand(conversationOperation);
      options.completeCommand(runOperation);
      setComposerText("");
    } catch (error) {
      const message = error instanceof ApiClientError ? error.message : "요청을 시작하지 못했습니다.";
      options.onStatusLine(message);
      setComposerError(message);
    } finally {
      options.setBusyCommand(null);
    }
  }, [composerText, options]);

  return { composerText, composerError, setComposerText, setComposerError, handleStartRun };
}

type Props = {
  text: string;
  error: string | null;
  busy: boolean;
  prompt: string;
  selectedResourceLabels: string[];
  setText: Dispatch<SetStateAction<string>>;
  setError: Dispatch<SetStateAction<string | null>>;
  onSubmit: (quickPrompt?: string) => Promise<void>;
};

export function RequestComposer({ text, error, busy, prompt, selectedResourceLabels, setText, setError, onSubmit }: Props): JSX.Element {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${node.scrollHeight}px`;
  }, [text]);

  return (
    <div className="composer-dock">
      <div className="composer-surface">
        {selectedResourceLabels.length > 0 ? <div className="composer-context" aria-live="polite"><strong>요청에 사용할 자료 {selectedResourceLabels.length}개</strong><span>{selectedResourceLabels.join(" · ")}</span></div> : null}
        <div className="composer-input-row">
          <textarea ref={textareaRef} className="composer composer--main" aria-label={prompt} placeholder={prompt} rows={1} value={text} onChange={(event) => { setText(event.target.value); setError(null); }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void onSubmit(); } }} />
          <button className="icon-button composer-send" type="button" aria-label="보내기" title="보내기" disabled={busy} onClick={() => void onSubmit()}><svg className="composer-send-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 4v16l16-8z" /></svg></button>
        </div>
      </div>
      {error ? <p className="status-bad" role="alert">{error}</p> : null}
    </div>
  );
}
