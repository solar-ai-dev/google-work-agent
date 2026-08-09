import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  approveAction,
  bootstrapSession,
  cancelRun,
  confirmRun,
  createConversation,
  deleteLLMApiKey,
  disconnectGoogle,
  getCurrentAccount,
  getGoogleConnection,
  getLLMConnection,
  getLatestConversationRun,
  getLive,
  getReady,
  getRunContext,
  getRunSnapshot,
  getRuntime,
  getSettings,
  listCalendarResources,
  listConversations,
  listGmailResources,
  listTaskResources,
  modifyAction,
  patchSettings,
  prepareRetry,
  rejectAction,
  resolveRecovery,
  resumeRun,
  startGoogleOAuth,
  startRun,
  storeLLMApiKey,
  testLLMConnection,
} from "../api";
import type {
  ConversationItem,
  CurrentGoogleAccountResponse,
  GoogleConnectionResponse,
  ResourceItem,
  RunAction,
  RunContext,
  RunSnapshot,
  RuntimeSummary,
  StartupCheck,
} from "../api/contract";
import { ApiClientError } from "../api/client";
import { subscribeRunEvents } from "../api/sse";

type StartupState = {
  phase: string;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  checks: StartupCheck[];
  error?: string;
};

type ResourceTab = "gmail" | "tasks" | "calendar";

type ResourceState = {
  tab: ResourceTab;
  query: string;
  items: ResourceItem[];
  nextPageToken: string | null;
  pageIndex: number;
  pageItems: ResourceItem[][];
  pageTokens: Array<string | null>;
  selectedIds: string[];
  focusItem: ResourceItem | null;
  parentId: string | null;
  loading: boolean;
  error: string | null;
};

type PendingConfirmation = {
  interruptId: string;
  question: string;
};

const resourceCache = new Map<string, { items: ResourceItem[]; nextPageToken: string | null }>();

const THEME_KEY = "gwa.theme";
const SETTINGS_KEY = "gwa.settings";

export function App(): JSX.Element {
  const [theme, setTheme] = useState(localStorage.getItem(THEME_KEY) ?? "light");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [startup, setStartup] = useState<StartupState>({
    phase: "boot",
    status: "idle",
    message: "시작 검사를 준비하고 있습니다.",
    checks: [],
  });
  const [runtime, setRuntime] = useState<RuntimeSummary | null>(null);
  const [google, setGoogle] = useState<GoogleConnectionResponse | null>(null);
  const [currentAccount, setCurrentAccount] = useState<CurrentGoogleAccountResponse["account"]>(null);
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [conversationQuery, setConversationQuery] = useState("");
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [runSnapshot, setRunSnapshot] = useState<RunSnapshot | null>(null);
  const [runContext, setRunContext] = useState<RunContext | null>(null);
  const [composerText, setComposerText] = useState("");
  const [busyCommand, setBusyCommand] = useState<string | null>(null);
  const [googleConnectPending, setGoogleConnectPending] = useState(false);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [confirmationText, setConfirmationText] = useState("");
  const [statusLine, setStatusLine] = useState("로컬 API에 연결되어 있습니다.");
  const [resourceState, setResourceState] = useState<ResourceState>({
    tab: "gmail",
    query: "",
    items: [],
    nextPageToken: null,
    pageIndex: 0,
    pageItems: [],
    pageTokens: [null],
    selectedIds: [],
    focusItem: null,
    parentId: null,
    loading: false,
    error: null,
  });
  const subscriptionRef = useRef<(() => void) | null>(null);
  const subscriptionRunIdRef = useRef<string | null>(null);
  const startupPromiseRef = useRef<Promise<void> | null>(null);

  const refreshConversations = useCallback(async (accountId: string): Promise<void> => {
    const response = await listConversations(accountId);
    setConversations(response.items);
  }, []);

  const refreshRuntimeSummary = useCallback(async (): Promise<void> => {
    const [runtimeResponse, googleResponse] = await Promise.all([getRuntime(), getGoogleConnection()]);
    setRuntime(runtimeResponse.summary);
    setGoogle(googleResponse);
  }, []);

  const refreshRun = useCallback(async (runId: string): Promise<void> => {
    const [snapshotResponse, contextResponse] = await Promise.all([
      getRunSnapshot(runId),
      getRunContext(runId),
    ]);
    setRunSnapshot(snapshotResponse.snapshot);
    setRunContext(contextResponse.context);
    setSelectedConversationId(snapshotResponse.snapshot.conversation_id);
    setPendingConfirmation((current) =>
      snapshotResponse.snapshot.status === "WAITING_CONFIRMATION" ? current : null,
    );
  }, []);

  const selectRun = useCallback(async (runId: string): Promise<void> => {
    await refreshRun(runId);
    if (subscriptionRunIdRef.current === runId && subscriptionRef.current) {
      return;
    }
    subscriptionRef.current?.();
    subscriptionRef.current = subscribeRunEvents(runId, {
      onStateChange: (message) => setStatusLine(message),
      onEvent: (event) => {
        if (event.eventType === "confirmation_required") {
          const interrupt = event.payload.user_interrupt;
          if (interrupt && typeof interrupt === "object") {
            const values = interrupt as Record<string, unknown>;
            if (typeof values.interrupt_id === "string") {
              setPendingConfirmation({
                interruptId: values.interrupt_id,
                question:
                  typeof values.question === "string"
                    ? values.question
                    : "계속하려면 필요한 내용을 확인해 주세요.",
              });
            }
          }
        }
        void refreshRun(runId);
      },
    });
    subscriptionRunIdRef.current = runId;
  }, [refreshRun]);

  const loadResources = useCallback(async (tab: ResourceTab, pageIndex: number): Promise<void> => {
    const pageToken = resourceState.pageTokens[pageIndex] ?? null;
    const knownPage = resourceState.pageItems[pageIndex];
    if (knownPage) {
      setResourceState((current) => ({
        ...current,
        items: knownPage,
        nextPageToken: current.pageTokens[pageIndex + 1] ?? null,
        pageIndex,
        loading: false,
        error: null,
      }));
      return;
    }
    const cacheKey = [
      currentAccount?.account_id ?? "anon",
      tab,
      resourceState.parentId ?? "",
      resourceState.query.trim().toLowerCase(),
      pageToken ?? "",
    ].join("|");
    const cached = resourceCache.get(cacheKey);
    if (cached) {
      setResourceState((current) => ({
        ...current,
        items: cached.items,
        nextPageToken: cached.nextPageToken,
        pageIndex,
        pageItems: Object.assign([...current.pageItems], { [pageIndex]: cached.items }),
        loading: false,
        error: null,
      }));
      return;
    }
    setResourceState((current) => ({ ...current, loading: true, error: null }));
    try {
      const response =
        tab === "gmail"
          ? await listGmailResources(resourceState.query, pageToken)
          : tab === "tasks"
            ? await listTaskResources(resourceState.parentId, pageToken)
            : await listCalendarResources(resourceState.parentId, pageToken);
      resourceCache.set(cacheKey, { items: response.items, nextPageToken: response.next_page_token });
      setResourceState((current) => ({
        ...current,
        items: response.items,
        nextPageToken: response.next_page_token,
        pageIndex,
        pageItems: Object.assign([...current.pageItems], { [pageIndex]: response.items }),
        pageTokens: Object.assign([...current.pageTokens], { [pageIndex + 1]: response.next_page_token }),
        loading: false,
      }));
    } catch (error) {
      setResourceState((current) => ({
        ...current,
        loading: false,
        error: error instanceof ApiClientError ? error.message : "리소스를 불러오지 못했습니다.",
      }));
    }
  }, [currentAccount?.account_id, resourceState.pageItems, resourceState.pageTokens, resourceState.parentId, resourceState.query]);

  const runStartup = useCallback(async (): Promise<void> => {
    // Preserve the one-time fragment in invocation-local memory before awaits.
    const bootstrapFragment = readBootstrapFragment(window.location.hash);
    resourceCache.clear();
    setStartup({
      phase: "checks",
      status: "loading",
      message: "로컬 서비스 준비 상태를 확인하고 있습니다.",
      checks: [],
    });
    try {
      await getLive();
      const ready = await getReady();
      setStartup({
        phase: "session",
        status: "loading",
        message: bootstrapFragment ? "로컬 세션을 수립하고 있습니다." : "기존 세션을 확인하고 있습니다.",
        checks: ready.checks,
      });
      if (bootstrapFragment) {
        await bootstrapSession(bootstrapFragment);
        window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
      }
      setStartup((current) => ({ ...current, phase: "runtime", message: "런타임 상태를 읽고 있습니다." }));
      const [runtimeResponse, googleResponse, accountResponse] = await Promise.all([
        getRuntime(),
        getGoogleConnection(),
        getCurrentAccount(),
      ]);
      setRuntime(runtimeResponse.summary);
      setGoogle(googleResponse);
      setCurrentAccount(accountResponse.account);
      if (accountResponse.account?.account_id) {
        await refreshConversations(accountResponse.account.account_id);
      }
      setStartup({
        phase: "ready",
        status: "ready",
        message: "UI를 준비했습니다.",
        checks: ready.checks,
      });
      await loadResources("gmail", 0);
      const openRunId = runtimeResponse.summary.open_run_ids[0];
      if (openRunId) {
        await selectRun(openRunId);
      }
    } catch (error) {
      const message = error instanceof ApiClientError ? error.message : "앱을 다시 열어 주세요.";
      setStartup({
        phase: "failed",
        status: "error",
        message: "시작 검사를 완료하지 못했습니다.",
        checks: [],
        error: message,
      });
    }
  }, [loadResources, refreshConversations, selectRun]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ settingsOpen }));
  }, [settingsOpen]);

  useEffect(() => {
    if (startupPromiseRef.current === null) {
      startupPromiseRef.current = runStartup();
    }
    return () => {
      subscriptionRef.current?.();
      subscriptionRef.current = null;
      subscriptionRunIdRef.current = null;
    };
  }, [runStartup]);

  useEffect(() => {
    if (startup.status !== "ready" || !currentAccount || resourceState.pageItems.length > 0) {
      return;
    }
    void loadResources(resourceState.tab, 0);
  }, [currentAccount, loadResources, resourceState.pageItems.length, resourceState.parentId, resourceState.tab, startup.status]);

  const selectedResources = useMemo(
    () => resourceState.items.filter((item) => resourceState.selectedIds.includes(item.resource_id)),
    [resourceState.items, resourceState.selectedIds],
  );

  async function selectConversation(conversationId: string): Promise<void> {
    setSelectedConversationId(conversationId);
    const latest = await getLatestConversationRun(conversationId);
    if (latest.run) {
      await selectRun(latest.run.run_id);
      return;
    }
    setRunSnapshot(null);
    setRunContext(null);
  }


  async function handleStartRun(quickPrompt?: string): Promise<void> {
    if (!currentAccount?.account_id) {
      setStatusLine("현재 연결된 계정 정보를 찾지 못했습니다.");
      return;
    }
    const requestText = (quickPrompt ?? composerText).trim();
    if (!requestText || busyCommand) {
      return;
    }
    setBusyCommand("start-run");
    try {
      const conversationId = selectedConversationId ?? crypto.randomUUID();
      if (!selectedConversationId) {
        await createConversation({
          command_id: crypto.randomUUID(),
          conversation_id: conversationId,
          account_id: currentAccount.account_id,
          title: requestText.slice(0, 80),
        });
        await refreshConversations(currentAccount.account_id);
        setSelectedConversationId(conversationId);
      }
      const commandId = crypto.randomUUID();
      const selectedResourceIds = [...resourceState.selectedIds];
      const runId = crypto.randomUUID();
      const workflowKey = `workflow-${runId}`;
      const response = await startRun({
        command_id: commandId,
        conversation_id: conversationId,
        user_message_id: crypto.randomUUID(),
        run_id: runId,
        workflow_key: workflowKey,
        request_text: requestText,
        entry_mode: selectedResourceIds.length > 0 ? "RESOURCE_SELECTED" : "AGENT_SEARCH",
        selected_resource_ids: selectedResourceIds,
        requested_mode: "AUTO",
      });
      await selectRun(response.run_id);
      setComposerText("");
    } finally {
      setBusyCommand(null);
    }
  }

  async function handleApprove(action: RunAction): Promise<void> {
    if (!runSnapshot || !currentAccount?.account_id || busyCommand) {
      return;
    }
    setBusyCommand(`approve-${action.action_id}`);
    try {
      const commandId = crypto.randomUUID();
      await approveAction({
        action_id: action.action_id,
        command_id: commandId,
        expected_version: action.version,
      });
      await selectRun(runSnapshot.run_id);
    } finally {
      setBusyCommand(null);
    }
  }

  async function handleSimpleAction(
    kind: "modify" | "reject" | "retry",
    action: RunAction,
  ): Promise<void> {
    if (!runSnapshot || busyCommand) {
      return;
    }
    const commandId = crypto.randomUUID();
    setBusyCommand(`${kind}-${action.action_id}`);
    try {
      if (kind === "modify") {
        await modifyAction({
          action_id: action.action_id,
          command_id: commandId,
          expected_version: action.version,
        });
      } else if (kind === "reject") {
        await rejectAction({
          action_id: action.action_id,
          command_id: commandId,
          expected_version: action.version,
        });
      } else {
        await prepareRetry({
          action_id: action.action_id,
          command_id: commandId,
          expected_action_version: action.version,
        });
      }
      await selectRun(runSnapshot.run_id);
    } finally {
      setBusyCommand(null);
    }
  }

  async function handleCancelRun(): Promise<void> {
    if (!runSnapshot || busyCommand) {
      return;
    }
    setBusyCommand("cancel-run");
    try {
      const commandId = crypto.randomUUID();
      await cancelRun({
        run_id: runSnapshot.run_id,
        command_id: commandId,
        expected_run_version: runSnapshot.version,
      });
      await selectRun(runSnapshot.run_id);
    } finally {
      setBusyCommand(null);
    }
  }

  async function handleResumeRun(): Promise<void> {
    if (!runSnapshot || busyCommand) {
      return;
    }
    const resumeKind = {
      REAUTH_REQUIRED: "REAUTH_COMPLETED",
      BLOCKED: "SAFE_CHECKPOINT_RESUME",
      RECOVERY_REQUIRED: "RECOVERY_RECHECK",
    }[runSnapshot.status] as "REAUTH_COMPLETED" | "SAFE_CHECKPOINT_RESUME" | "RECOVERY_RECHECK" | undefined;
    if (!resumeKind) {
      setStatusLine("현재 상태는 전용 확인 또는 승인 경로를 사용해야 합니다.");
      return;
    }
    setBusyCommand("resume-run");
    try {
      const commandId = crypto.randomUUID();
      await resumeRun({
        run_id: runSnapshot.run_id,
        command_id: commandId,
        expected_version: runSnapshot.version,
        resume_kind: resumeKind,
      });
      await selectRun(runSnapshot.run_id);
    } finally {
      setBusyCommand(null);
    }
  }

  async function handleConfirmation(): Promise<void> {
    if (!runSnapshot || !pendingConfirmation || !confirmationText.trim() || busyCommand) {
      return;
    }
    setBusyCommand("confirm-run");
    try {
      await confirmRun({
        run_id: runSnapshot.run_id,
        command_id: crypto.randomUUID(),
        expected_version: runSnapshot.version,
        interrupt_id: pendingConfirmation.interruptId,
        response_kind: "FREE_TEXT",
        free_text: confirmationText.trim(),
      });
      setConfirmationText("");
      await refreshRun(runSnapshot.run_id);
    } finally {
      setBusyCommand(null);
    }
  }

  async function handleResolveRecovery(
    action: RunAction,
    resolutionKind: "ACCEPT_PARTIAL" | "CREATE_CORRECTIVE_PLAN",
  ): Promise<void> {
    if (!runSnapshot || busyCommand) {
      return;
    }
    setBusyCommand(`recovery-${resolutionKind}`);
    try {
      await resolveRecovery({
        run_id: runSnapshot.run_id,
        command_id: crypto.randomUUID(),
        expected_version: runSnapshot.version,
        action_id: action.action_id,
        resolution_kind: resolutionKind,
      });
      await refreshRun(runSnapshot.run_id);
    } finally {
      setBusyCommand(null);
    }
  }

  async function handleGoogleConnect(): Promise<void> {
    if (google?.connected || googleConnectPending) {
      return;
    }
    setGoogleConnectPending(true);
    try {
      const response = await startGoogleOAuth();
      window.open(requireOAuthLaunchUrl(response.authorization_url), "_blank", "noopener,noreferrer");
      setStatusLine("Google 연결 완료를 기다리고 있습니다.");
    } catch (error) {
      setStatusLine(error instanceof ApiClientError ? error.message : "Google 연결을 시작하지 못했습니다.");
    } finally {
      setGoogleConnectPending(false);
    }
  }

  async function handleGoogleDisconnect(): Promise<void> {
    await disconnectGoogle();
    resourceCache.clear();
    setCurrentAccount(null);
    setResourceState((current) => ({
      ...current,
      items: [],
      nextPageToken: null,
      pageIndex: 0,
      pageItems: [],
      pageTokens: [null],
      selectedIds: [],
      focusItem: null,
    }));
    await refreshRuntimeSummary();
  }

  if (startup.status !== "ready") {
    return (
      <main className="startup">
        <section className="startup-card" aria-live="polite">
          <h1>Google Work Agent</h1>
          <p>{startup.message}</p>
          {startup.error ? <p className="status-bad">{startup.error}</p> : null}
          <ul className="card-list">
            {startup.checks.map((check) => (
              <li key={check.name} className="info-card">
                <strong>{check.name}</strong>
                <div className="muted">{check.state}</div>
                {check.detail ? <div className="muted">{check.detail}</div> : null}
              </li>
            ))}
          </ul>
          <div className="button-row">
            <button className="button-primary" type="button" onClick={() => void runStartup()}>
              다시 검사
            </button>
            <button className="button-secondary" type="button" onClick={() => setSettingsOpen(true)}>
              진단 열기
            </button>
          </div>
        </section>
        {settingsOpen ? (
        <SettingsDrawer
          runtime={runtime}
          google={google}
          theme={theme}
          onThemeChange={setTheme}
          onClose={() => setSettingsOpen(false)}
          onDisconnect={handleGoogleDisconnect}
          onRuntimeRefresh={refreshRuntimeSummary}
        />
        ) : null}
      </main>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <strong>Google Work Agent</strong>
          <div className="muted">{statusLine}</div>
        </div>
        <div className="inline-row">
          <span className="pill">{google?.connected ? "Google 연결됨" : "Google 미연결"}</span>
          {currentAccount ? <span className="muted">{currentAccount.email}</span> : null}
          <button
            className="button-secondary"
            type="button"
            title="자료를 선택하거나 자연어 요청을 입력하면 Agent가 업무를 시작합니다."
            onClick={() => setStatusLine("자료를 선택하거나 자연어 요청을 입력해 업무를 시작할 수 있습니다.")}
          >
            도움말
          </button>
          {!google?.connected ? (
            <button
              className="button-primary"
              type="button"
              disabled={googleConnectPending}
              onClick={() => void handleGoogleConnect()}
            >
              {googleConnectPending ? "Google 연결 중..." : "Google 연결"}
            </button>
          ) : null}
          <button className="button-secondary" type="button" onClick={() => setSettingsOpen(true)}>
            설정
          </button>
        </div>
      </header>
      <div className="shell-grid">
        <aside className="panel">
          <div className="panel-header">
            <strong>Google 자료</strong>
            <div className="inline-row">
              <button
                className="button-secondary"
                type="button"
                onClick={() => {
                  resourceCache.clear();
                  setResourceState((current) => ({ ...current, pageIndex: 0, pageItems: [], pageTokens: [null] }));
                  void loadResources(resourceState.tab, 0);
                }}
              >
                새로고침
              </button>
            </div>
          </div>
          <div className="panel-body">
            <div className="inline-row">
              {(["gmail", "tasks", "calendar"] as ResourceTab[]).map((tab) => (
                <button
                  key={tab}
                  className={resourceState.tab === tab ? "button-primary" : "button-secondary"}
                  type="button"
                  onClick={() => setResourceState((current) => ({
                    ...current,
                    tab,
                    items: [],
                    nextPageToken: null,
                    pageIndex: 0,
                    pageItems: [],
                    pageTokens: [null],
                    parentId: null,
                    focusItem: null,
                  }))}
                >
                  {tab.toUpperCase()}
                </button>
              ))}
            </div>
            {resourceState.tab === "gmail" ? (
              <label>
                <span className="muted">검색</span>
                <input
                  value={resourceState.query}
                  onChange={(event) => setResourceState((current) => ({
                    ...current,
                    query: event.target.value,
                    pageIndex: 0,
                    pageItems: [],
                    pageTokens: [null],
                  }))}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      void loadResources("gmail", 0);
                    }
                  }}
                />
              </label>
            ) : null}
            {resourceState.loading ? <p className="muted" aria-live="polite">자료를 불러오는 중입니다.</p> : null}
            {resourceState.error ? <p className="status-bad">{resourceState.error}</p> : null}
            {!resourceState.loading && !resourceState.error && resourceState.items.length === 0 ? (
              <p className="muted">표시할 자료가 없습니다.</p>
            ) : null}
            <ul className="resource-list" aria-label="Google 업무 자료">
              {resourceState.items.map((item) => {
                const selected = resourceState.selectedIds.includes(item.resource_id);
                const focused = resourceState.focusItem?.resource_id === item.resource_id;
                return (
                  <li key={item.resource_id} className={`resource-item ${selected ? "selected" : ""} ${focused ? "focused" : ""}`}>
                    <button
                      className="resource-summary"
                      type="button"
                      aria-pressed={focused}
                      onClick={() => setResourceState((current) => ({ ...current, focusItem: item }))}
                    >
                      <strong>{item.title}</strong>
                      {item.subtitle ? <span className="muted">{item.subtitle}</span> : null}
                      <span className="muted">{resourceLabel(item)}</span>
                    </button>
                    <div className="button-row resource-actions">
                      <button
                        className="button-secondary"
                        type="button"
                        onClick={() => setResourceState((current) => ({
                          ...current,
                          selectedIds: current.selectedIds.includes(item.resource_id)
                            ? current.selectedIds.filter((resourceId) => resourceId !== item.resource_id)
                            : [...current.selectedIds, item.resource_id],
                          focusItem: item,
                        }))}
                      >
                        {selected ? "선택 해제" : "선택"}
                      </button>
                      <button className="button-secondary" type="button" onClick={() => void handleStartRun(`${item.title} 관련 핵심을 정리해 줘`)}>
                        채팅에 추가
                      </button>
                      <button className="button-secondary" type="button" onClick={() => window.open(safeGoogleLink(item.link_url), "_blank", "noopener,noreferrer")}>
                        원본 열기
                      </button>
                      {(item.resource_type === "task_list" || item.resource_type === "calendar") ? (
                        <button
                          className="button-secondary"
                          type="button"
                          onClick={() => setResourceState((current) => ({
                            ...current,
                            parentId: item.resource_id,
                            items: [],
                            nextPageToken: null,
                            pageIndex: 0,
                            pageItems: [],
                            pageTokens: [null],
                            focusItem: item,
                          }))}
                        >
                          하위 보기
                        </button>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
            <nav className="pagination" aria-label="자료 페이지">
              <button className="button-secondary" type="button" disabled={resourceState.pageIndex === 0} onClick={() => void loadResources(resourceState.tab, resourceState.pageIndex - 1)}>
                이전
              </button>
              {resourceState.pageItems.map((_, index) => (
                <button key={index} className={index === resourceState.pageIndex ? "button-primary" : "button-secondary"} type="button" onClick={() => void loadResources(resourceState.tab, index)}>
                  {index + 1}
                </button>
              ))}
              {resourceState.pageTokens[resourceState.pageIndex + 1] ? (
                <button className="button-secondary" type="button" onClick={() => void loadResources(resourceState.tab, resourceState.pageIndex + 1)}>
                  다음
                </button>
              ) : null}
            </nav>
          </div>
        </aside>

        <main className="panel">
          <div className="panel-header">
            <div>
              <strong>{selectedConversationId ? "대화 진행" : "새 요청"}</strong>
              <div className="muted">{userRunStatus(runSnapshot?.status)}</div>
            </div>
            <div className="button-row">
              {runSnapshot?.next_allowed_commands.includes("CANCEL") ? (
                <button className="button-danger" type="button" onClick={() => void handleCancelRun()}>
                  취소
                </button>
              ) : null}
              {runSnapshot?.next_allowed_commands.includes("RESUME") ? (
                <button className="button-secondary" type="button" onClick={() => void handleResumeRun()}>
                  재개
                </button>
              ) : null}
            </div>
          </div>
          <div className="panel-body">
            <section className="resource-viewer" aria-label="선택 자료 상세">
              <div className="section-heading">
                <strong>선택 자료</strong>
                {resourceState.focusItem ? <span className="pill">{resourceState.focusItem.source}</span> : null}
              </div>
              {resourceState.focusItem ? (
                <>
                  <h2>{resourceState.focusItem.title}</h2>
                  {resourceState.focusItem.subtitle ? <p>{resourceState.focusItem.subtitle}</p> : null}
                  {Object.keys(resourceState.focusItem.metadata).length > 0 ? (
                    <dl className="metadata-list">
                      {Object.entries(resourceState.focusItem.metadata).slice(0, 6).map(([key, value]) => (
                        <div key={key}>
                          <dt>{key}</dt>
                          <dd>{formatMetadata(value)}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : <p className="muted">현재 목록에서 제공된 상세 정보가 없습니다.</p>}
                </>
              ) : <p className="muted">왼쪽 목록에서 자료를 열면 제공 가능한 상세 정보가 표시됩니다.</p>}
            </section>
            {runContext?.request_text ? (
              <article className="info-card">
                <strong>사용자 요청</strong>
                <p>{runContext.request_text}</p>
              </article>
            ) : null}

            {runSnapshot?.status === "WAITING_CONFIRMATION" ? (
              <article className="info-card">
                <strong>추가 확인</strong>
                <p>
                  {pendingConfirmation?.question ?? "확인 요청 정보를 동기화하고 있습니다."}
                </p>
                <textarea
                  aria-label="확인 응답"
                  className="composer"
                  disabled={!pendingConfirmation}
                  value={confirmationText}
                  onChange={(event) => setConfirmationText(event.target.value)}
                />
                <button
                  className="button-primary"
                  type="button"
                  disabled={
                    !pendingConfirmation ||
                    !confirmationText.trim() ||
                    busyCommand === "confirm-run"
                  }
                  onClick={() => void handleConfirmation()}
                >
                  응답 보내기
                </button>
              </article>
            ) : null}

            {selectedResources.length > 0 ? (
              <div className="inline-row">
                {selectedResources.map((item) => (
                  <span key={item.resource_id} className="pill">
                    {item.title}
                  </span>
                ))}
              </div>
            ) : null}

            <section className="card-list">
              {runSnapshot?.active_plan ? (
                <article className="info-card">
                  <strong>Action Plan</strong>
                  <div className="muted">{runSnapshot.active_plan.summary_text ?? "요약이 아직 없습니다."}</div>
                  <div className="muted">Action {runSnapshot.execution_status.action_count}건</div>
                </article>
              ) : null}

              {runSnapshot?.actions.map((action) => {
                const approval = runSnapshot.approvals.find((item) => item.action_id === action.action_id);
                const waitingApproval =
                  action.approval_required && ["PROPOSED", "MODIFIED"].includes(action.status);
                return (
                  <article key={action.action_id} className="info-card">
                    <div className="inline-row" style={{ justifyContent: "space-between" }}>
                      <strong>{action.tool_name}</strong>
                      <span className="pill">{action.status}</span>
                    </div>
                    <div className="muted">
                      {action.effect_type} / {action.verification_policy}
                    </div>
                    <details>
                      <summary>승인 상세</summary>
                      <dl className="metadata-list">
                        <div><dt>Action</dt><dd>{action.tool_name}</dd></div>
                        <div><dt>검증</dt><dd>{action.verification_policy}</dd></div>
                      </dl>
                    </details>
                    {approval ? (
                      <div className="muted">
                        승인 상태 {approval.status} / 만료 {formatTime(approval.expires_at_ms)}
                      </div>
                    ) : null}
                    {waitingApproval ? (
                      <div className="button-row">
                        <button
                          className="button-primary"
                          type="button"
                          disabled={busyCommand === `approve-${action.action_id}`}
                          onClick={() => void handleApprove(action)}
                        >
                          승인
                        </button>
                        <button
                          className="button-secondary"
                          type="button"
                          disabled={busyCommand === `modify-${action.action_id}`}
                          onClick={() => void handleSimpleAction("modify", action)}
                        >
                          수정
                        </button>
                        <button
                          className="button-danger"
                          type="button"
                          disabled={busyCommand === `reject-${action.action_id}`}
                          onClick={() => void handleSimpleAction("reject", action)}
                        >
                          건너뛰기
                        </button>
                      </div>
                    ) : null}
                    {action.status === "FAILED" ? (
                      <button className="button-secondary" type="button" onClick={() => void handleSimpleAction("retry", action)}>
                        다시 준비
                      </button>
                    ) : null}
                    {action.status === "UNKNOWN_RESULT" ? (
                      <p className="status-warn">실제 결과를 확인하는 중입니다. 새 쓰기 실행은 잠시 막혀 있습니다.</p>
                    ) : null}
                    {action.status === "MISMATCH" ? (
                      <div>
                        <p className="status-warn">
                          실행 결과가 승인 내용과 다릅니다. 자동 수정이나 롤백은 수행하지 않습니다.
                        </p>
                        <div className="button-row">
                          <button
                            className="button-secondary"
                            type="button"
                            onClick={() => void handleResolveRecovery(action, "ACCEPT_PARTIAL")}
                          >
                            현재 결과 수용
                          </button>
                          <button
                            className="button-primary"
                            type="button"
                            onClick={() =>
                              void handleResolveRecovery(action, "CREATE_CORRECTIVE_PLAN")
                            }
                          >
                            새 계획 만들기
                          </button>
                        </div>
                      </div>
                    ) : null}
                  </article>
                );
              })}

              {runSnapshot ? (
                <article className="info-card">
                  <strong>검증 결과</strong>
                  <div className="muted">Verified {runSnapshot.verification_summary.verified_count}</div>
                  <div className="muted">Mismatch {runSnapshot.verification_summary.mismatch_count}</div>
                </article>
              ) : null}

              {runSnapshot?.recovery_summary.unknown_result_action_count ? (
                <article className="info-card">
                  <strong>Recovery</strong>
                  <p>결과 불명 작업 {runSnapshot.recovery_summary.unknown_result_action_count}건을 확인하고 있습니다.</p>
                </article>
              ) : null}
            </section>

            <label>
              <span className="muted">자연어 요청</span>
              <textarea
                className="composer"
                value={composerText}
                onChange={(event) => setComposerText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void handleStartRun();
                  }
                }}
              />
            </label>
            <div className="button-row">
              <button className="button-primary" type="button" disabled={busyCommand === "start-run"} onClick={() => void handleStartRun()}>
                요청 시작
              </button>
              <button className="button-secondary" type="button" onClick={() => setComposerText("")}>
                입력 지우기
              </button>
            </div>
          </div>
        </main>

        <aside className="panel conversation-panel">
          <div className="panel-header">
            <strong>대화</strong>
            <button className="button-secondary" type="button" onClick={() => setSelectedConversationId(null)}>
              새 대화
            </button>
          </div>
          <div className="panel-body">
            <label className="search-field">
              <span className="muted">대화 검색</span>
              <input value={conversationQuery} onChange={(event) => setConversationQuery(event.target.value)} />
            </label>
            <ul className="conversation-list">
              {conversations.filter((conversation) => conversation.title.toLowerCase().includes(conversationQuery.trim().toLowerCase())).map((conversation) => (
                <li key={conversation.id} className={`conversation-item ${selectedConversationId === conversation.id ? "selected" : ""}`}>
                  <button
                    type="button"
                    style={{ all: "unset", display: "grid", gap: "0.35rem", cursor: "pointer" }}
                    onClick={() => void selectConversation(conversation.id)}
                  >
                    <strong>{conversation.title}</strong>
                    <span className="muted">{formatTime(conversation.updated_at_ms)}</span>
                  </button>
                </li>
              ))}
            </ul>
            {conversations.length === 0 ? <p className="muted">아직 대화가 없습니다.</p> : null}
            <section className="recent-execution">
              <strong>최근 실행</strong>
              {runSnapshot ? <p className="muted">현재 대화의 실행 상태는 중앙 작업 공간에서 확인할 수 있습니다.</p> : <p className="muted">표시할 실행 기록이 없습니다.</p>}
            </section>
          </div>
        </aside>
      </div>

      {settingsOpen ? (
        <SettingsDrawer
          runtime={runtime}
          google={google}
          theme={theme}
          onThemeChange={setTheme}
          onClose={() => setSettingsOpen(false)}
          onConnect={handleGoogleConnect}
          onDisconnect={handleGoogleDisconnect}
          onRuntimeRefresh={refreshRuntimeSummary}
        />
      ) : null}
    </div>
  );
}

function SettingsDrawer(props: {
  runtime: RuntimeSummary | null;
  google: GoogleConnectionResponse | null;
  theme: string;
  onThemeChange: (theme: string) => void;
  onClose: () => void;
  onConnect?: () => void;
  onDisconnect: () => void;
  onRuntimeRefresh: () => Promise<void>;
}): JSX.Element {
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsSavedMessage, setSettingsSavedMessage] = useState<string | null>(null);
  const [requestedRuntimeMode, setRequestedRuntimeMode] = useState("API_LLM");
  const [externalLLMConsent, setExternalLLMConsent] = useState(false);
  const [ollamaEndpoint, setOllamaEndpoint] = useState("");
  const [approvedModelId, setApprovedModelId] = useState("");
  const [llmState, setLLMState] = useState<Record<string, unknown> | null>(null);
  const [llmStatusMessage, setLLMStatusMessage] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [storageMode, setStorageMode] = useState<"KEYRING" | "SESSION_MEMORY">("KEYRING");

  const loadRuntimeSettings = useCallback(async (): Promise<void> => {
    setSettingsLoading(true);
    setSettingsError(null);
    try {
      const [settingsResponse, llmResponse] = await Promise.all([getSettings(), getLLMConnection()]);
      const settings = asRecord(settingsResponse.settings);
      setRequestedRuntimeMode(String(settings.requested_runtime_mode ?? "API_LLM"));
      setExternalLLMConsent(Boolean(settings.external_llm_consent));
      setOllamaEndpoint(String(settings.ollama_endpoint ?? ""));
      setApprovedModelId(String(settings.approved_model_id ?? ""));
      setLLMState(asRecord(llmResponse.llm));
    } catch (error) {
      setSettingsError(
        error instanceof ApiClientError ? error.message : "설정 정보를 불러오지 못했습니다.",
      );
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRuntimeSettings();
  }, [loadRuntimeSettings]);

  const llmSummary = useMemo(() => readLLMState(props.runtime?.llm), [props.runtime?.llm]);
  const connectionSummary = useMemo(() => readLLMState(llmState), [llmState]);

  async function handleSaveLLMSettings(): Promise<void> {
    setSettingsSavedMessage(null);
    setSettingsError(null);
    try {
      await patchSettings({
        command_id: `settings-${Date.now()}`,
        requested_runtime_mode: requestedRuntimeMode,
        external_llm_consent: externalLLMConsent,
        ollama_endpoint: ollamaEndpoint.trim() || null,
        approved_model_id: approvedModelId.trim() || null,
      });
      await Promise.all([props.onRuntimeRefresh(), loadRuntimeSettings()]);
      setSettingsSavedMessage("LLM 설정을 저장했습니다.");
    } catch (error) {
      setSettingsError(error instanceof ApiClientError ? error.message : "설정을 저장하지 못했습니다.");
    }
  }

  async function handleStoreLLMApiKey(): Promise<void> {
    setLLMStatusMessage(null);
    setSettingsError(null);
    try {
      await storeLLMApiKey({ api_key: apiKey, storage_mode: storageMode });
      setApiKey("");
      await Promise.all([props.onRuntimeRefresh(), loadRuntimeSettings()]);
      setLLMStatusMessage("API 키를 저장했습니다.");
    } catch (error) {
      setSettingsError(
        error instanceof ApiClientError ? error.message : "API 키를 저장하지 못했습니다.",
      );
    }
  }

  async function handleDeleteLLMApiKey(): Promise<void> {
    setLLMStatusMessage(null);
    setSettingsError(null);
    try {
      await deleteLLMApiKey();
      await Promise.all([props.onRuntimeRefresh(), loadRuntimeSettings()]);
      setLLMStatusMessage("API 키를 삭제했습니다.");
    } catch (error) {
      setSettingsError(
        error instanceof ApiClientError ? error.message : "API 키를 삭제하지 못했습니다.",
      );
    }
  }

  async function handleTestLLMConnection(): Promise<void> {
    setLLMStatusMessage(null);
    setSettingsError(null);
    try {
      const response = await testLLMConnection();
      setLLMState(asRecord(response.llm));
      await props.onRuntimeRefresh();
      setLLMStatusMessage("LLM 연결 상태를 다시 확인했습니다.");
    } catch (error) {
      setSettingsError(
        error instanceof ApiClientError ? error.message : "LLM 연결 테스트에 실패했습니다.",
      );
    }
  }

  return (
    <aside className="drawer" aria-label="설정 및 진단">
      <div className="panel-header">
        <strong>설정·진단</strong>
        <button className="button-secondary" type="button" onClick={props.onClose}>
          닫기
        </button>
      </div>
      <div className="panel-body">
        <section className="info-card">
          <strong>일반</strong>
          <div className="button-row">
            <button className={props.theme === "light" ? "button-primary" : "button-secondary"} type="button" onClick={() => props.onThemeChange("light")}>
              Light
            </button>
            <button className={props.theme === "dark" ? "button-primary" : "button-secondary"} type="button" onClick={() => props.onThemeChange("dark")}>
              Dark
            </button>
          </div>
        </section>
        <section className="info-card">
          <strong>Google</strong>
          <p>{props.google?.connected ? props.google.account_email : "연결되지 않음"}</p>
          <div className="button-row">
            {!props.google?.connected && props.onConnect ? (
              <button className="button-primary" type="button" onClick={props.onConnect}>
                Google 로그인
              </button>
            ) : null}
            {props.google?.connected ? (
              <button className="button-danger" type="button" onClick={props.onDisconnect}>
                연결 해제
              </button>
            ) : null}
          </div>
          {props.google?.missing_scopes.length ? (
            <p className="status-warn">누락 Scope: {props.google.missing_scopes.join(", ")}</p>
          ) : null}
          {props.google?.safe_error_code ? (
            <p className="status-warn">{props.google.safe_error_code}</p>
          ) : null}
          {props.google?.safe_error_description ? (
            <p className="status-warn">{props.google.safe_error_description}</p>
          ) : null}
        </section>
        <section className="info-card">
          <strong>Runtime</strong>
          <div className="muted">Deployment {props.runtime?.deployment_profile ?? "-"}</div>
          <div className="muted">MCP {props.runtime?.mcp ?? "-"}</div>
          <div className="muted">API LLM {props.runtime?.api_llm ?? "-"}</div>
          <div className="muted">Ollama {props.runtime?.ollama ?? "-"}</div>
        </section>
        <section className="info-card">
          <strong>LLM</strong>
          {settingsLoading ? <p className="muted">설정을 불러오는 중입니다.</p> : null}
          {settingsError ? <p className="status-warn">{settingsError}</p> : null}
          {settingsSavedMessage ? <p className="muted">{settingsSavedMessage}</p> : null}
          {llmStatusMessage ? <p className="muted">{llmStatusMessage}</p> : null}
          <label style={{ display: "grid", gap: "0.35rem" }}>
            <span className="muted">Requested mode</span>
            <select
              value={requestedRuntimeMode}
              onChange={(event) => setRequestedRuntimeMode(event.target.value)}
              disabled={settingsLoading}
            >
              <option value="API_LLM">API_LLM</option>
              <option value="AUTO">AUTO</option>
              <option value="LOCAL_GPU">LOCAL_GPU</option>
            </select>
          </label>
          <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.75rem" }}>
            <input
              type="checkbox"
              checked={externalLLMConsent}
              onChange={(event) => setExternalLLMConsent(event.target.checked)}
              disabled={settingsLoading}
            />
            <span>외부 LLM 사용 동의</span>
          </label>
          <label style={{ display: "grid", gap: "0.35rem", marginTop: "0.75rem" }}>
            <span className="muted">Ollama endpoint</span>
            <input
              value={ollamaEndpoint}
              onChange={(event) => setOllamaEndpoint(event.target.value)}
              placeholder="http://127.0.0.1:11434"
              disabled={settingsLoading}
            />
          </label>
          <label style={{ display: "grid", gap: "0.35rem", marginTop: "0.75rem" }}>
            <span className="muted">Approved model id</span>
            <input
              value={approvedModelId}
              onChange={(event) => setApprovedModelId(event.target.value)}
              placeholder="approved-model"
              disabled={settingsLoading}
            />
          </label>
          <div className="button-row" style={{ marginTop: "0.75rem" }}>
            <button className="button-primary" type="button" onClick={() => void handleSaveLLMSettings()}>
              LLM 설정 저장
            </button>
            <button className="button-secondary" type="button" onClick={() => void handleTestLLMConnection()}>
              연결 테스트
            </button>
          </div>
          <div className="muted" style={{ marginTop: "0.75rem" }}>
            Build {llmSummary.buildProfile ?? "-"} / Actual {llmSummary.actualRuntime ?? "-"}
          </div>
          <div className="muted">Available {llmSummary.availableModes.join(", ") || "-"}</div>
          <div className="muted">
            API credential {connectionSummary.apiCredentialState ?? "-"} / API availability{" "}
            {connectionSummary.apiAvailability ?? "-"}
          </div>
          <div className="muted">
            Ollama {connectionSummary.ollamaAvailability ?? "-"} / Model{" "}
            {connectionSummary.approvedModelState ?? "-"}
          </div>
        </section>
        <section className="info-card">
          <strong>API Key</strong>
          <label style={{ display: "grid", gap: "0.35rem" }}>
            <span className="muted">Storage mode</span>
            <select
              value={storageMode}
              onChange={(event) =>
                setStorageMode(event.target.value === "SESSION_MEMORY" ? "SESSION_MEMORY" : "KEYRING")
              }
            >
              <option value="KEYRING">KEYRING</option>
              <option value="SESSION_MEMORY">SESSION_MEMORY</option>
            </select>
          </label>
          <label style={{ display: "grid", gap: "0.35rem", marginTop: "0.75rem" }}>
            <span className="muted">API key</span>
            <input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="sk-..."
            />
          </label>
          <div className="button-row" style={{ marginTop: "0.75rem" }}>
            <button
              className="button-primary"
              type="button"
              onClick={() => void handleStoreLLMApiKey()}
              disabled={!apiKey.trim()}
            >
              API 키 저장
            </button>
            <button className="button-secondary" type="button" onClick={() => void handleDeleteLLMApiKey()}>
              API 키 삭제
            </button>
          </div>
        </section>
      </div>
    </aside>
  );
}

function requireOAuthLaunchUrl(value: string): string {
  const url = new URL(value);
  if (
    url.protocol !== "http:" ||
    url.hostname !== "127.0.0.1" ||
    !url.port ||
    url.pathname !== "/oauth/authorize"
  ) {
    throw new Error("Unexpected OAuth authorization URL");
  }
  return url.toString();
}

function readBootstrapFragment(hash: string): { bootstrap_secret: string; service_instance_id: string } | null {
  const source = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!source) {
    return null;
  }
  const params = new URLSearchParams(source);
  const bootstrapSecret =
    params.get("bootstrap_secret") ?? params.get("bootstrapSecret") ?? params.get("bootstrap");
  const serviceInstanceId =
    params.get("service_instance_id") ?? params.get("serviceInstanceId");
  if (!bootstrapSecret || !serviceInstanceId) {
    return null;
  }
  return {
    bootstrap_secret: bootstrapSecret,
    service_instance_id: serviceInstanceId,
  };
}

function formatTime(value: number): string {
  return new Date(value).toLocaleString("ko-KR", { hour12: false });
}

function userRunStatus(status: string | undefined): string {
  switch (status) {
    case "WAITING_APPROVAL":
      return "승인이 필요합니다.";
    case "WAITING_CONFIRMATION":
      return "추가 정보를 확인하고 있습니다.";
    case "PLANNING":
      return "요청을 검토하고 있습니다.";
    case "RETRIEVING":
      return "관련 자료를 확인하고 있습니다.";
    case "VERIFYING":
      return "작업 결과를 확인하고 있습니다.";
    case "COMPLETED":
    case "SUCCEEDED":
      return "작업이 완료되었습니다.";
    case "FAILED":
      return "작업을 완료하지 못했습니다.";
    case "RECOVERY_REQUIRED":
      return "실제 결과를 확인해야 합니다.";
    default:
      return "작업을 처리하고 있습니다.";
  }
}

function resourceLabel(item: ResourceItem): string {
  const metadata = item.metadata;
  const value = metadata.received_at ?? metadata.updated_at ?? metadata.due ?? metadata.start ?? metadata.status;
  return typeof value === "string" || typeof value === "number" ? String(value) : item.resource_type;
}

function formatMetadata(value: unknown): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "제공된 상세 정보";
}

function safeGoogleLink(url: string): string {
  const parsed = new URL(url);
  const allowedHosts = new Set(["mail.google.com", "tasks.google.com", "calendar.google.com"]);
  if (parsed.protocol !== "https:" || !allowedHosts.has(parsed.host)) {
    return "https://calendar.google.com/";
  }
  return parsed.toString();
}

function readLLMState(value: Record<string, unknown> | null | undefined): {
  buildProfile: string | null;
  actualRuntime: string | null;
  availableModes: string[];
  apiCredentialState: string | null;
  apiAvailability: string | null;
  ollamaAvailability: string | null;
  approvedModelState: string | null;
} {
  const llm = asRecord(value);
  const apiProvider = asRecord(llm.api_provider);
  const ollama = asRecord(llm.ollama);
  return {
    buildProfile: typeof llm.build_profile === "string" ? llm.build_profile : null,
    actualRuntime: typeof llm.actual_runtime === "string" ? llm.actual_runtime : null,
    availableModes: Array.isArray(llm.available_modes)
      ? llm.available_modes.filter((item): item is string => typeof item === "string")
      : [],
    apiCredentialState:
      typeof apiProvider.credential_state === "string" ? apiProvider.credential_state : null,
    apiAvailability: typeof apiProvider.availability === "string" ? apiProvider.availability : null,
    ollamaAvailability: typeof ollama.availability === "string" ? ollama.availability : null,
    approvedModelState:
      typeof ollama.approved_model_state === "string" ? ollama.approved_model_state : null,
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, unknown>;
}
