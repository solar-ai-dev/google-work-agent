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
  getGmailResourceDetail,
  getLLMConnection,
  getLatestConversationRun,
  getLive,
  getReady,
  getRunContext,
  getRunSnapshot,
  getRuntime,
  getSettings,
  listConversations,
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
  GmailResourceDetailResponse,
  ResourceItem,
  RunAction,
  RunContext,
  RunSnapshot,
  RuntimeSummary,
  StartupCheck,
} from "../api/contract";
import { ApiClientError } from "../api/client";
import { subscribeRunEvents } from "../api/sse";
import { CalendarPanel, useCalendar } from "../features/calendar";
import { ConversationView, useConversation } from "../features/conversation";
import { GmailPanel, useGmail } from "../features/gmail";
import { TasksPanel, useTasks } from "../features/tasks";

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
  selectedIds: string[];
  focusItem: ResourceItem | null;
  parentId: string | null;
};

type GmailDetailState = {
  resourceId: string | null;
  status: "idle" | "loading" | "ready" | "error";
  detail: GmailResourceDetailResponse | null;
  error: string | null;
};

const SIDEBAR_VISIBLE_PAGE_SIZE = 20;

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
  const [calendarTimezone, setCalendarTimezone] = useState("Asia/Seoul");
  const [taskSortMenuOpen, setTaskSortMenuOpen] = useState(false);
  const [conversationQuery, setConversationQuery] = useState("");
  const [sidebarFilter, setSidebarFilter] = useState("");
  const [googleConnectPending, setGoogleConnectPending] = useState(false);
  const [statusLine, setStatusLine] = useState("로컬 API에 연결되어 있습니다.");
  const [gmailDetail, setGmailDetail] = useState<GmailDetailState>({
    resourceId: null,
    status: "idle",
    detail: null,
    error: null,
  });
  const [resourceState, setResourceState] = useState<ResourceState>({
    tab: "gmail",
    selectedIds: [],
    focusItem: null,
    parentId: null,
  });
  const gmail = useGmail({ accountId: currentAccount?.account_id, active: resourceState.tab === "gmail" });
  const tasks = useTasks({ accountId: currentAccount?.account_id, parentId: resourceState.parentId, active: resourceState.tab === "tasks", filter: sidebarFilter });
  const calendar = useCalendar({
    accountId: currentAccount?.account_id,
    calendarId: resourceState.parentId,
    active: startup.status === "ready" && google?.connected === true && resourceState.tab === "calendar",
    timezone: calendarTimezone,
  });
  const selectedResourceIds = useMemo(
    () => [...new Set(resourceState.selectedIds)],
    [resourceState.selectedIds],
  );
  const selectedResourceLabels = useMemo(
    () => resourceItemsForSelection(resourceState, gmail.items, tasks.items)
      .filter((item) => selectedResourceIds.includes(item.resource_id))
      .map((item) => resourcePresentation(item).title)
      .filter((title): title is string => Boolean(title)),
    [resourceState, gmail.items, selectedResourceIds, tasks.items],
  );
  const composerPrompt = resourceComposerPrompt(resourceState.tab);
  const visibleResourceItems = useMemo(() => {
    if (resourceState.tab === "tasks") {
      if (!sidebarFilter.trim()) return tasks.items.slice(tasks.pageIndex * SIDEBAR_VISIBLE_PAGE_SIZE, (tasks.pageIndex + 1) * SIDEBAR_VISIBLE_PAGE_SIZE);
      const normalizedFilter = sidebarFilter.trim().toLocaleLowerCase("ko-KR");
      return tasks.items.filter((item) => {
        const presentation = resourcePresentation(item);
        return [presentation.title, presentation.secondary, presentation.snippet, presentation.time].filter((value): value is string => Boolean(value)).some((value) => value.toLocaleLowerCase("ko-KR").includes(normalizedFilter));
      }).slice(tasks.pageIndex * SIDEBAR_VISIBLE_PAGE_SIZE, (tasks.pageIndex + 1) * SIDEBAR_VISIBLE_PAGE_SIZE);
    }
    return [];
  }, [resourceState.tab, sidebarFilter, tasks.items, tasks.pageIndex]);
  const visibleTaskSections = useMemo(() => (
    resourceState.tab === "tasks" && tasks.sort === "scheduled_date"
      ? groupTasksByScheduledDate(visibleResourceItems)
      : null
  ), [resourceState.tab, tasks.sort, visibleResourceItems]);
  const conversation = useConversation({
    currentAccount,
    selectedResourceIds,
    onStatusLine: setStatusLine,
  });
  const {
    conversations,
    selectedConversationId,
    runSnapshot,
    runContext,
    composerText,
    composerError,
    busyCommand,
    pendingConfirmation,
    confirmationText,
    setComposerText,
    setComposerError,
    setConfirmationText,
    refreshConversations,
    beginConversationProjection,
    selectConversation,
    selectRun,
    refreshRun,
    handleStartRun,
    handleApprove,
    handleSimpleAction,
    handleCancelRun,
    handleResumeRun,
    handleConfirmation,
    handleResolveRecovery,
  } = conversation;
  const conversationViewModel = {
    controller: {
      selectedConversationId,
      runSnapshot,
      runContext,
      pendingConfirmation,
      confirmationText,
      setConfirmationText,
      composerText,
      composerError,
      setComposerText,
      setComposerError,
      busyCommand,
      handleStartRun,
      handleApprove,
      handleSimpleAction,
      handleCancelRun,
      handleResumeRun,
      handleConfirmation,
      handleResolveRecovery,
    },
    resourceContext: {
      selectedResourceIds,
      selectedResourceLabels,
      composerPrompt,
    },
    formatTime,
  };
  const startupPromiseRef = useRef<Promise<void> | null>(null);
  const taskSortMenuRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!taskSortMenuOpen) {
      return;
    }
    const closeOnOutsidePointer = (event: MouseEvent): void => {
      if (!taskSortMenuRef.current?.contains(event.target as Node)) {
        setTaskSortMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", closeOnOutsidePointer);
    return () => document.removeEventListener("mousedown", closeOnOutsidePointer);
  }, [taskSortMenuOpen]);

  const refreshRuntimeSummary = useCallback(async (): Promise<void> => {
    const [runtimeResponse, googleResponse] = await Promise.all([getRuntime(), getGoogleConnection()]);
    setRuntime(runtimeResponse.summary);
    setGoogle(googleResponse);
  }, []);

  const loadGmailDetail = useCallback(async (resourceId: string): Promise<void> => {
    setGmailDetail({ resourceId, status: "loading", detail: null, error: null });
    try {
      const detail = await getGmailResourceDetail(resourceId);
      setGmailDetail((current) => current.resourceId === resourceId
        ? { resourceId, status: "ready", detail, error: null }
        : current);
    } catch (error) {
      setGmailDetail((current) => current.resourceId === resourceId
        ? {
            resourceId,
            status: "error",
            detail: null,
            error: error instanceof ApiClientError
              ? error.message
              : "메일 내용을 불러오지 못했습니다.",
          }
        : current);
    }
  }, []);

  useEffect(() => {
    const focusItem = resourceState.focusItem;
    if (focusItem?.resource_type === "gmail_thread") {
      void loadGmailDetail(focusItem.resource_id);
      return;
    }
    setGmailDetail({ resourceId: null, status: "idle", detail: null, error: null });
  }, [loadGmailDetail, resourceState.focusItem]);

  const runStartup = useCallback(async (): Promise<void> => {
    // Preserve the one-time fragment in invocation-local memory before awaits.
    const bootstrapFragment = readBootstrapFragment(window.location.hash);
    gmail.reset();
    tasks.reset();
    calendar.reset();
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
      const [runtimeResponse, googleResponse, settingsResponse] = await Promise.all([
        getRuntime(),
        getGoogleConnection(),
        getSettings().catch(() => null),
      ]);
      const firstAccountResponse = await getCurrentAccount();
      const accountResponse = googleResponse.connected && firstAccountResponse.account === null
        ? await getCurrentAccount()
        : firstAccountResponse;
      setRuntime(runtimeResponse.summary);
      setGoogle(googleResponse);
      setCurrentAccount(accountResponse.account);
      const configuredTimezone = settingsResponse === null ? null : asRecord(settingsResponse.settings).timezone;
      if (typeof configuredTimezone === "string" && configuredTimezone) {
        setCalendarTimezone(configuredTimezone);
      }
      if (accountResponse.account?.account_id) {
        await refreshConversations(accountResponse.account.account_id);
      }
      setStartup({
        phase: "ready",
        status: "ready",
        message: "UI를 준비했습니다.",
        checks: ready.checks,
      });
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
  }, [calendar.reset, refreshConversations, selectRun]);

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
  }, [runStartup]);

  useEffect(() => {
    if (startup.status === "ready" && google?.connected) {
      void gmail.loadCount();
      void tasks.preload();
      void tasks.loadCompleted();
    }
  }, [gmail.loadCount, google?.connected, startup.status, tasks.loadCompleted, tasks.preload]);

  useEffect(() => {
    if (startup.status !== "ready" || !google?.connected || resourceState.tab !== "gmail") return;
    if (!gmail.loaded && !gmail.loading && gmail.error === null) void gmail.loadPage(gmail.pageIndex);
    else if (gmail.loaded && !gmail.countLoading) void gmail.loadCount();
  }, [gmail.countLoading, gmail.error, gmail.loadCount, gmail.loadPage, gmail.loaded, gmail.loading, gmail.pageIndex, google?.connected, resourceState.tab, startup.status]);

  useEffect(() => {
    if (startup.status !== "ready" || !google?.connected || resourceState.tab !== "tasks") return;
    if (!tasks.loaded && !tasks.loading && tasks.error === null) void tasks.loadPage(tasks.pageIndex);
  }, [google?.connected, resourceState.tab, startup.status, tasks.error, tasks.loadPage, tasks.loaded, tasks.loading, tasks.pageIndex]);

  /* Extracted to features/conversation/useConversation.ts.
  async function selectConversation(conversationId: string): Promise<void> {
    const generation = beginConversationProjection(conversationId);
    try {
      const latest = await getLatestConversationRun(conversationId);
      if (
        conversationProjectionRef.current.generation !== generation
        || conversationProjectionRef.current.conversationId !== conversationId
      ) {
        return;
      }
      if (latest.run) {
        await selectRun(latest.run.run_id, conversationId, generation);
      }
    } catch (error) {
      if (
        conversationProjectionRef.current.generation === generation
        && conversationProjectionRef.current.conversationId === conversationId
      ) {
        const message = error instanceof ApiClientError
          ? error.message
          : "대화 실행 정보를 불러오지 못했습니다.";
        setStatusLine(message);
        setComposerError(message);
      }
    }
  }


  async function handleStartRun(quickPrompt?: string): Promise<void> {
    if (!currentAccount?.account_id) {
      const message = "현재 연결된 계정 정보를 찾지 못했습니다.";
      setStatusLine(message);
      setComposerError(message);
      return;
    }
    const requestText = (quickPrompt ?? composerText).trim();
    if (!requestText || busyCommand) {
      return;
    }
    setBusyCommand("start-run");
    setComposerError(null);
    try {
      const conversationId = selectedConversationId ?? crypto.randomUUID();
      let projectionGeneration = conversationProjectionRef.current.generation;
      if (!selectedConversationId) {
        await createConversation({
          command_id: crypto.randomUUID(),
          conversation_id: conversationId,
          account_id: currentAccount.account_id,
          title: requestText.slice(0, 80),
        });
        projectionGeneration = beginConversationProjection(conversationId);
        await refreshConversations(currentAccount.account_id);
      }
      const commandId = crypto.randomUUID();
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
      await selectRun(response.run_id, conversationId, projectionGeneration);
      setComposerText("");
    } catch (error) {
      const message = error instanceof ApiClientError ? error.message : "요청을 시작하지 못했습니다.";
      setStatusLine(message);
      setComposerError(message);
    } finally {
      setBusyCommand(null);
    }
  }

  async function handleApprove(
    action: RunAction,
    duplicateAcknowledged = false,
    calendarConflictAcknowledged = false,
  ): Promise<void> {
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
        duplicate_acknowledged: duplicateAcknowledged,
        calendar_conflict_acknowledged: calendarConflictAcknowledged,
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

  */

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
    gmail.reset();
    tasks.reset();
    calendar.reset();
    setGoogle((current) => current ? { ...current, connected: false } : current);
    setCurrentAccount(null);
    setResourceState((current) => ({
      ...current,
      items: [],
      nextPageToken: null,
      pageIndex: 0,
      loaded: false,
      selectedIds: [],
      focusItem: null,
      totalCount: null,
      countLoading: false,
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
        <div className="topbar-brand">
          <span className="brand-mark" aria-hidden="true">✦</span>
          <strong>Google Work Agent</strong>
          <span className="sr-only" aria-live="polite">{statusLine}</span>
        </div>
        <div className="topbar-connection" aria-live="polite">
          <span className={`pill ${google?.connected ? "connection-connected" : "connection-disconnected"}`}>
            {google?.connected ? "Google 연결됨" : "Google 미연결"}
          </span>
        </div>
        <div className="topbar-actions">
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
        <aside className="panel resource-panel">
          <div className="panel-body">
            <div className="resource-tabbar">
              <div className="resource-tabs" role="tablist" aria-label="자료 종류">
              {(["gmail", "tasks", "calendar"] as ResourceTab[]).map((tab) => (
                  <button
                    key={tab}
                    className={`resource-tab ${resourceState.tab === tab ? "selected" : ""}`}
                    type="button"
                    role="tab"
                    aria-selected={resourceState.tab === tab}
                    onClick={() => {
                      setTaskSortMenuOpen(false);
                      setSidebarFilter("");
                      setResourceState((current) => ({
                        ...current,
                        tab,
                        parentId: null,
                        focusItem: null,
                      }));
                    }}
                  >
                    <span className="resource-tab-icon" aria-hidden="true">{resourceTabIcon(tab)}</span>
                    <span className="resource-tab-label">{resourceTabLabel(tab)}</span>
                    {tab !== "calendar" ? (
                      <span className="resource-tab-count">
                        {formatSourceCount(tab === "gmail" ? gmail.count : tasks.count)}
                      </span>
                    ) : null}
                    <span className="sr-only">{tab.toUpperCase()}</span>
                  </button>
                ))}
              </div>
              <button
                className="icon-button"
                type="button"
                aria-label="현재 목록 새로고침"
                title="새로고침"
                onClick={() => {
                  const activeTab = resourceState.tab;
                  if (activeTab === "gmail") {
                    void gmail.refresh();
                    return;
                  }
                  if (activeTab === "tasks") {
                    void tasks.refresh();
                    return;
                  }
                  if (activeTab === "calendar") {
                    void calendar.refresh();
                    return;
                  }
                }}
              >
                ↻
              </button>
            </div>
            {resourceState.tab === "gmail" ? (
              <GmailPanel
                gmail={gmail}
                selection={{
                  selectedResourceIds: resourceState.selectedIds,
                  focusedResourceId: resourceState.focusItem?.resource_id ?? null,
                  onToggleResource: (resourceId) => setResourceState((current) => ({
                    ...current,
                    selectedIds: current.selectedIds.includes(resourceId)
                      ? current.selectedIds.filter((selectedId) => selectedId !== resourceId)
                      : [...current.selectedIds, resourceId],
                  })),
                  onFocusResource: (item) => setResourceState((current) => ({ ...current, focusItem: item })),
                }}
                pagination={{
                  pageIndexes: paginationPageIndexes(gmail.pageIndex, gmail.totalCount, gmail.items.length),
                  hasNextPage: gmail.pageIndex + 1 < totalPageCount(gmail.totalCount, gmail.items.length)
                    || (gmail.totalCount === null && gmail.nextPageToken !== null),
                  onGoToPage: (pageIndex) => void gmail.loadPage(pageIndex),
                }}
                presentResource={resourcePresentation}
              />
            ) : null}
            {resourceState.tab === "tasks" ? (
              <TasksPanel
                tasks={tasks}
                filter={sidebarFilter}
                onFilterChange={setSidebarFilter}
                selection={{
                  selectedResourceIds: resourceState.selectedIds,
                  focusedResourceId: resourceState.focusItem?.resource_id ?? null,
                  onToggleResource: (resourceId) => setResourceState((current) => ({
                    ...current,
                    selectedIds: current.selectedIds.includes(resourceId)
                      ? current.selectedIds.filter((selectedId) => selectedId !== resourceId)
                      : [...current.selectedIds, resourceId],
                  })),
                  onFocusResource: (item) => setResourceState((current) => ({ ...current, focusItem: item })),
                }}
                visibleItems={visibleResourceItems}
                sections={visibleTaskSections}
                pageIndexes={paginationPageIndexes(tasks.pageIndex, tasks.totalCount, tasks.items.length)}
                hasNextPage={tasks.pageIndex + 1 < totalPageCount(tasks.totalCount, tasks.items.length) || (tasks.totalCount === null && tasks.nextPageToken !== null)}
                presentResource={resourcePresentation}
                pastDays={pastScheduledDays}
                formatCompletedAt={(item) => formatCompletedTaskDate(firstPresentationValue(item.metadata, ["completed_at"]), calendarTimezone)}
              />
            ) : null}
            {resourceState.tab === "calendar" ? (
              <CalendarPanel
                calendar={calendar}
                timezone={calendarTimezone}
                filter={sidebarFilter}
                onFilterChange={setSidebarFilter}
                onFocusEvent={(item) => setResourceState((current) => ({ ...current, focusItem: item }))}
              />
            ) : null}
          </div>
        </aside>

        <main className="panel">
          <ConversationView viewModel={conversationViewModel}>
            <section className="resource-viewer" aria-label="선택 자료 상세">
              {resourceState.focusItem ? (
                <div className="viewer-actions viewer-actions-floating">
                    {hasCanonicalGoogleUrl(
                      gmailDetail.detail?.resource_id === resourceState.focusItem.resource_id
                        ? gmailDetail.detail.canonical_url
                        : resourceState.focusItem.link_url,
                    ) ? (
                      <button
                        className="icon-button"
                        type="button"
                        aria-label="원본 열기"
                        title="원본 열기"
                        onClick={() => window.open(
                          safeGoogleLink(
                            gmailDetail.detail?.resource_id === resourceState.focusItem!.resource_id
                              ? gmailDetail.detail.canonical_url
                              : resourceState.focusItem!.link_url,
                          ),
                          "_blank",
                          "noopener,noreferrer",
                        )}
                      >
                        ↗
                      </button>
                    ) : null}
                    {(resourceState.focusItem.resource_type === "task_list" || resourceState.focusItem.resource_type === "calendar") ? (
                      <button
                        className="icon-button"
                        type="button"
                        aria-label="하위 자료 보기"
                        title="하위 자료 보기"
                        onClick={() => {
                          setResourceState((current) => ({
                            ...current,
                            parentId: resourceState.focusItem!.resource_id,
                          }));
                        }}
                      >
                        →
                      </button>
                    ) : null}
                </div>
              ) : (
                <div className="section-heading"><strong>자료 상세</strong></div>
              )}
              {resourceState.focusItem ? (
                resourceState.focusItem.resource_type === "gmail_thread" ? (
                  <GmailDetailViewer
                    state={gmailDetail}
                    onRetry={() => void loadGmailDetail(resourceState.focusItem!.resource_id)}
                  />
                ) : (
                  <>
                    <h2>{resourcePresentation(resourceState.focusItem).title ?? "제목 없음"}</h2>
                    {resourcePresentation(resourceState.focusItem).secondary ? <p>{resourcePresentation(resourceState.focusItem).secondary}</p> : null}
                    {viewerMetadataEntries(resourceState.focusItem).length > 0 ? (
                      <dl className="metadata-list">
                        {viewerMetadataEntries(resourceState.focusItem).map(([key, value]) => (
                          <div key={key}>
                            <dt>{key}</dt>
                            <dd>{value}</dd>
                          </div>
                        ))}
                      </dl>
                    ) : <p className="muted">현재 목록에서 제공된 상세 정보가 없습니다.</p>}
                  </>
                )
              ) : <p className="muted">{resourceViewerEmptyMessage(resourceState.tab)}</p>}
            </section>
          </ConversationView>
        </main>

        <aside className="panel conversation-panel">
          <div className="panel-header">
            <strong>대화</strong>
            <button className="button-secondary" type="button" onClick={() => beginConversationProjection(null)}>
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
                    className="conversation-summary"
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

function totalPageCount(totalCount: number | null, loadedItemCount: number): number {
  return Math.ceil((totalCount ?? loadedItemCount) / SIDEBAR_VISIBLE_PAGE_SIZE);
}

function formatSourceCount(count: { value: number; exact: boolean } | null): string {
  if (count === null) return "";
  return `${count.value}${count.exact ? "" : "+"}`;
}

function paginationPageIndexes(currentPage: number, totalCount: number | null, loadedItemCount: number): number[] {
  const pageCount = totalPageCount(totalCount, loadedItemCount);
  const first = Math.max(0, Math.min(currentPage - 2, pageCount - 5));
  return Array.from({ length: Math.min(5, pageCount) }, (_, index) => first + index);
}

function groupTasksByScheduledDate(items: ResourceItem[], now = new Date()): Array<{
  key: string;
  label: string;
  items: ResourceItem[];
}> {
  const today = localDateKey(now);
  const tomorrowDate = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  const tomorrow = localDateKey(tomorrowDate);
  return items.reduce<Array<{ key: string; label: string; items: ResourceItem[] }>>((sections, item) => {
    const scheduledDate = taskScheduledDate(item);
    const taskStatus = firstPresentationValue(item.metadata, ["task_status"]);
    const key = taskDateSectionKey(scheduledDate, taskStatus, today, tomorrow);
    const label = taskDateSectionLabel(scheduledDate, key);
    const previous = sections.at(-1);
    if (previous?.key === key) {
      previous.items.push(item);
      return sections;
    }
    sections.push({ key, label, items: [item] });
    return sections;
  }, []);
}

function taskDateSectionKey(
  scheduledDate: string | null,
  taskStatus: string | null,
  today: string,
  tomorrow: string,
): string {
  if (!scheduledDate) return "no-date";
  if (scheduledDate < today && taskStatus !== "completed") return "past";
  if (scheduledDate === today) return "today";
  if (scheduledDate === tomorrow) return "tomorrow";
  return `date:${scheduledDate}`;
}

function taskDateSectionLabel(scheduledDate: string | null, key: string): string {
  if (key === "past") return "지난 날짜";
  if (key === "today") return "오늘";
  if (key === "tomorrow") return "내일";
  if (key === "no-date") return "날짜 없음";
  return formatTaskDate(scheduledDate, false) ?? "날짜 없음";
}

function localDateKey(value: Date): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function taskScheduledDate(item: ResourceItem): string | null {
  const value = firstPresentationValue(item.metadata, ["scheduled_date"]);
  return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null;
}

function localCalendarDayNumber(value: string): number {
  const [year, month, day] = value.split("-").map(Number);
  return Date.UTC(year, month - 1, day) / (24 * 60 * 60 * 1000);
}

function pastScheduledDays(item: ResourceItem, now = new Date()): number | null {
  const scheduledDate = taskScheduledDate(item);
  if (!scheduledDate || firstPresentationValue(item.metadata, ["task_status"]) === "completed") return null;
  const difference = localCalendarDayNumber(localDateKey(now)) - localCalendarDayNumber(scheduledDate);
  return difference > 0 ? difference : null;
}

function resourceItemsForSelection(resourceState: ResourceState, gmailItems: ResourceItem[], taskItems: ResourceItem[]): ResourceItem[] {
  return resourceState.tab === "gmail"
    ? gmailItems
    : resourceState.tab === "tasks" ? taskItems : [];
}

function GmailDetailViewer({
  state,
  onRetry,
}: {
  state: GmailDetailState;
  onRetry: () => void;
}): JSX.Element {
  if (state.status === "loading") {
    return <div className="viewer-state" role="status">메일 내용을 불러오는 중입니다.</div>;
  }
  if (state.status === "error") {
    return (
      <div className="viewer-state" role="alert">
        <p>{state.error ?? "메일 내용을 불러오지 못했습니다."}</p>
        <button className="button-secondary" type="button" onClick={onRetry}>다시 시도</button>
      </div>
    );
  }
  if (state.status !== "ready" || !state.detail) {
    return <div className="viewer-state">메일 내용을 선택해 주세요.</div>;
  }

  const detail = state.detail;
  const sender = formatMailboxIdentity(detail.sender_name, detail.sender_email);
  const receivedAt = formatDetailDate(detail.received_at);
  return (
    <article className="gmail-detail">
      <header className="gmail-detail-header">
        <div className="gmail-detail-sender">
          {sender ? <strong>{sender}</strong> : <strong className="muted">보낸 사람 정보가 없습니다.</strong>}
          <div className="gmail-detail-meta">
            {detail.recipients.length > 0 ? <span>받는 사람 {detail.recipients.join(", ")}</span> : null}
            {detail.cc.length > 0 ? <span>참조 {detail.cc.join(", ")}</span> : null}
            {receivedAt ? <time>{receivedAt}</time> : null}
          </div>
        </div>
        {detail.subject ? <h2>{detail.subject}</h2> : null}
      </header>
      {detail.body ? (
        <div className="gmail-detail-body">{detail.body}</div>
      ) : (
        <p className="viewer-empty">표시할 메일 내용이 없습니다.</p>
      )}
      {detail.attachments.length > 0 ? (
        <section className="gmail-attachments" aria-label="첨부파일">
          <strong>첨부파일</strong>
          <ul>
            {detail.attachments.map((attachment) => (
              <li key={`${attachment.message_id}:${attachment.attachment_id}`}>
                <span>{attachment.filename}</span>
                <small>
                  {attachment.mime_type}
                  {attachment.size_bytes !== null ? ` · ${formatFileSize(attachment.size_bytes)}` : ""}
                </small>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
}

function resourcePresentation(item: ResourceItem): {
  title: string | null;
  secondary: string | null;
  snippet: string | null;
  time: string | null;
} {
  const metadata = item.metadata;
  const source = item.source.toLowerCase();
  const sender = userFacingValue(item.sender_name)
    ?? firstPresentationValue(metadata, ["sender", "from", "sender_name", "from_name", "display_name", "participants"]);
  const email = userFacingValue(item.sender_email)
    ?? firstPresentationValue(metadata, ["sender_email", "from_email", "email"]);
  const subject = userFacingValue(item.subject)
    ?? firstPresentationValue(metadata, ["subject", "title", "summary", "name"]);
  const subtitle = userFacingValue(item.subtitle);
  const itemTitle = resourceTitleValue(item.title, source);
  const title = isGenericResourceTitle(itemTitle, source) ? userFacingValue(subject) : itemTitle ?? userFacingValue(subject);
  if (source === "calendar" && item.resource_type === "calendar_event") {
    const start = userFacingValue(metadata.start);
    const end = userFacingValue(metadata.end);
    return {
      title,
      secondary: formatCalendarEventRange(start, end),
      snippet: null,
      time: null,
    };
  }
  if (source === "tasks" && item.resource_type === "task") {
    return {
      title,
      secondary: null,
      snippet: null,
      time: formatTaskDate(firstPresentationValue(metadata, ["scheduled_date"]), false),
    };
  }
  const secondary = source === "gmail"
    ? formatMailboxIdentity(sender, email)
    : sender ?? subtitle;
  const snippet = userFacingValue(item.snippet)
    ?? firstPresentationValue(metadata, ["snippet", "preview", "body_preview", "description", "notes"])
    ?? (source === "gmail" ? subtitle : null);
  const rawTime = userFacingValue(item.received_at)
    ?? firstPresentationValue(metadata, ["received_at", "received_at_ms", "date", "updated_at", "updated_at_ms", "due", "start"]);
  const time = source === "gmail" ? formatSidebarDate(rawTime) : rawTime;
  return { title, secondary, snippet, time };
}

function formatCalendarEventRange(start: string | null, end: string | null): string | null {
  if (isAllDayCalendarValue(start)) {
    const startLabel = formatCalendarEventDate(start);
    return startLabel ? `${startLabel} · 하루 종일` : null;
  }
  const startDate = parsedResourceDate(start);
  const endDate = parsedResourceDate(end);
  if (startDate && endDate && isSameCalendarDate(startDate, endDate)) {
    return `${formatCalendarEventDateTime(startDate)} - ${formatCalendarEventClock(endDate)}`;
  }
  const startLabel = startDate ? formatCalendarEventDateTime(startDate) : null;
  const endLabel = endDate ? formatCalendarEventDateTime(endDate) : null;
  if (startLabel && endLabel) return `${startLabel} - ${endLabel}`;
  return startLabel ?? endLabel;
}

function formatTaskDate(value: string | null, detailed: boolean): string | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  const dateLabel = date.toLocaleDateString("ko-KR", detailed
    ? { year: "numeric", month: "long", day: "numeric" }
    : { month: "long", day: "numeric" });
  const weekday = date.toLocaleDateString("ko-KR", { weekday: "short" });
  return `${dateLabel} (${weekday})`;
}

function formatCompletedTaskDate(value: string | null, timezone: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("ko-KR", {
    timeZone: timezone,
    month: "long",
    day: "numeric",
    weekday: "short",
  });
}

function taskStatusLabel(value: string | null): string | null {
  if (value === "incomplete") return "미완료";
  if (value === "completed") return "완료";
  return null;
}

function isAllDayCalendarValue(value: string | null): boolean {
  return Boolean(value && /^\d{4}-\d{2}-\d{2}$/.test(value));
}

function formatCalendarEventDate(value: string | null): string | null {
  if (!value) return null;
  if (isAllDayCalendarValue(value)) {
    const [year, month, day] = value.split("-").map(Number);
    return formatCalendarEventDateLabel(new Date(year, month - 1, day));
  }
  const date = parsedResourceDate(value);
  return date ? formatCalendarEventDateTime(date) : null;
}

function formatCalendarEventDateTime(date: Date): string {
  return `${formatCalendarEventDateLabel(date)} ${formatCalendarEventClock(date)}`;
}

function formatCalendarEventDateLabel(date: Date): string {
  const dateLabel = date.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
  const weekday = date.toLocaleDateString("ko-KR", { weekday: "short" });
  return `${dateLabel} (${weekday})`;
}

function formatCalendarEventClock(date: Date): string {
  return date.toLocaleTimeString("ko-KR", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function isSameCalendarDate(left: Date, right: Date): boolean {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate();
}

function resourceSearchPlaceholder(tab: ResourceTab): string {
  switch (tab) {
    case "tasks":
      return "작업 검색";
    case "calendar":
      return "일정 검색";
    default:
      return "검색 (제목, 보낸사람, 내용)";
  }
}

function resourceSearchLabel(tab: ResourceTab): string {
  switch (tab) {
    case "tasks":
      return "작업 검색";
    case "calendar":
      return "일정 검색";
    default:
      return "메일 검색";
  }
}

function resourceComposerPrompt(tab: ResourceTab): string {
  switch (tab) {
    case "tasks":
      return "선택한 태스크에 대해 질문하거나 업무를 요청하세요...";
    case "calendar":
      return "선택한 일정에 대해 질문하거나 업무를 요청하세요...";
    default:
      return "선택한 메일에 대해 질문하거나 업무를 요청하세요...";
  }
}

function resourceViewerEmptyMessage(tab: ResourceTab): string {
  switch (tab) {
    case "tasks":
      return "왼쪽 목록에서 태스크를 선택하면 상세 내용을 확인할 수 있습니다.";
    case "calendar":
      return "왼쪽 목록에서 일정을 선택하면 상세 내용을 확인할 수 있습니다.";
    default:
      return "왼쪽 목록에서 메일을 선택하면 상세 내용을 확인할 수 있습니다.";
  }
}

function formatMailboxIdentity(name: string | null, email: string | null): string | null {
  if (name && email && name !== email) return `${name} <${email}>`;
  if (name) return name;
  return email ? `<${email}>` : null;
}

function parsedResourceDate(value: string | null): Date | null {
  if (!value) return null;
  const milliseconds = /^\d{12,}$/.test(value) ? Number(value) : Date.parse(value);
  if (!Number.isFinite(milliseconds)) return null;
  const date = new Date(milliseconds);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatSidebarDate(value: string | null, now = new Date()): string | null {
  const date = parsedResourceDate(value);
  if (!date) return null;
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfValue = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayDifference = Math.round((startOfToday.getTime() - startOfValue.getTime()) / 86_400_000);
  if (dayDifference === 0) {
    return date.toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit", hour12: true });
  }
  if (dayDifference === 1) return "어제";
  if (date.getFullYear() === now.getFullYear()) {
    return date.toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
  }
  return date.toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function formatDetailDate(value: string | null): string | null {
  const date = parsedResourceDate(value);
  return date?.toLocaleString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }) ?? null;
}

function formatFileSize(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${Math.round(sizeBytes / 1024)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

function viewerMetadataEntries(item: ResourceItem): Array<[string, string]> {
  const metadata = item.metadata;
  const source = item.source.toLowerCase();
  if (source === "tasks" && item.resource_type === "task") {
    const taskStatus = taskStatusLabel(firstPresentationValue(metadata, ["task_status"]));
    const scheduledDate = firstPresentationValue(metadata, ["scheduled_date"]);
    const entries: Array<[string, string]> = [];
    if (taskStatus) entries.push(["상태", taskStatus]);
    const date = formatTaskDate(scheduledDate, true);
    if (date) entries.push(["예정일", date]);
    const notes = firstPresentationValue(metadata, ["notes"]);
    if (notes) entries.push(["내용", notes]);
    return entries;
  }
  if (source === "calendar" && item.resource_type === "calendar_event") {
    const start = userFacingValue(metadata.start);
    const end = userFacingValue(metadata.end);
    if (isAllDayCalendarValue(start)) {
      const date = formatCalendarEventDate(start);
      return date ? [["날짜", date]] : [];
    }
    const entries: Array<[string, string]> = [];
    const startLabel = formatCalendarEventDate(start);
    const endLabel = formatCalendarEventDate(end);
    if (startLabel) entries.push(["시작 시간", startLabel]);
    if (endLabel) entries.push(["종료 시간", endLabel]);
    const calendarName = firstPresentationValue(metadata, ["calendar_name", "calendar_display_name"]);
    if (calendarName) entries.push(["캘린더", calendarName]);
    const description = firstPresentationValue(metadata, ["description", "notes", "body", "snippet"]);
    if (description) entries.push(["내용", description]);
    return entries;
  }
  const fields: Array<[string, string[]]> = source === "gmail"
    ? [
        ["보낸사람", ["sender", "from", "sender_name", "from_name", "display_name", "participants"]],
        ["이메일", ["sender_email", "from_email", "email"]],
        ["받는사람", ["recipients", "to", "recipient"]],
        ["받은 시각", ["received_at", "received_at_ms", "date"]],
        ["내용", ["body", "snippet", "preview", "body_preview"]],
      ]
    : [
        ["상태", ["status"]],
        ["마감일", ["due"]],
        ["시작", ["start"]],
        ["종료", ["end"]],
        ["업데이트", ["updated_at", "updated_at_ms"]],
        ["내용", ["description", "notes", "body", "snippet"]],
      ];
  return fields.flatMap(([label, keys]) => {
    const value = firstPresentationValue(metadata, keys);
    return value ? [[label, value]] : [];
  });
}

function firstPresentationValue(metadata: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = userFacingValue(metadata[key]);
    if (value) {
      return value;
    }
  }
  return null;
}

function userFacingValue(value: unknown): string | null {
  if (typeof value === "string" || typeof value === "number") {
    const text = String(value).trim();
    return text && !isTechnicalIdentifier(text) ? text : null;
  }
  if (Array.isArray(value)) {
    const values = value
      .map((entry) => userFacingValue(entry))
      .filter((entry): entry is string => Boolean(entry));
    return values.length ? values.join(", ") : null;
  }
  return null;
}

function resourceTitleValue(value: unknown, source: string): string | null {
  if (source === "tasks" && typeof value === "string") {
    const text = value.trim();
    return text || null;
  }
  return userFacingValue(value);
}

function isTechnicalIdentifier(value: string): boolean {
  return /^[a-z0-9_-]{12,}$/i.test(value) && !value.includes("@");
}

function isGenericResourceTitle(value: string | null, source: string): boolean {
  const sourceLabel = resourceSourceLabel(source).toLowerCase();
  return source === "gmail" && [`${sourceLabel} 자료`, "gmail 자료", "google 자료"].includes(value?.toLowerCase() ?? "");
}

function resourceTabLabel(tab: ResourceTab): string {
  switch (tab) {
    case "gmail":
      return "메일";
    case "tasks":
      return "태스크";
    case "calendar":
      return "캘린더";
  }
}

function resourceTabIcon(tab: ResourceTab): string {
  switch (tab) {
    case "gmail":
      return "✉";
    case "tasks":
      return "✓";
    case "calendar":
      return "▦";
  }
}

function resourceSourceLabel(source: string): string {
  switch (source.toLowerCase()) {
    case "gmail":
      return "메일";
    case "tasks":
      return "태스크";
    case "calendar":
      return "캘린더";
    default:
      return "Google 자료";
  }
}

function safeGoogleLink(url: string): string {
  if (!hasCanonicalGoogleUrl(url)) {
    return "https://calendar.google.com/";
  }
  return new URL(url).toString();
}

function hasCanonicalGoogleUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    const allowedHosts = new Set(["mail.google.com", "tasks.google.com", "calendar.google.com"]);
    return parsed.protocol === "https:" && allowedHosts.has(parsed.host);
  } catch {
    return false;
  }
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
