import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClientError } from "../api/client";
import { ConversationHistoryPanel, useConversation } from "../features/conversation";
import { ResourceSidebar, ResourceViewer, type ResourceBrowserProjection } from "../features/resource_browser";
import { getRuntime, type RuntimeSummary } from "../features/diagnostics";
import {
  FirstRunOnboardingScreen,
  SettingsDrawer,
  getCurrentGoogleAccount,
  getGoogleConnection,
  getSettings,
  startGoogleConnection,
  updateSettings,
  type CurrentGoogleAccount,
  type GoogleConnection,
  type SettingsView,
} from "../features/settings";
import { CenterWorkspace } from "./center_workspace";
import { MainShell } from "./main_shell";
import { StartupFlow, type StartupFlowContext } from "./startup_flow";

export function App(): JSX.Element {
  return <StartupFlow>{(context) => <AuthenticatedWorkspace initial={context} />}</StartupFlow>;
}
function AuthenticatedWorkspace({ initial }: { initial: StartupFlowContext }): JSX.Element {
  const [settings, setSettings] = useState<SettingsView>(initial.settings);
  const [theme, setTheme] = useState(initial.settings.theme === "DARK" ? "dark" : "light");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [runtime, setRuntime] = useState<RuntimeSummary>(initial.runtime);
  const [google, setGoogle] = useState<GoogleConnection>(initial.google);
  const [currentAccount, setCurrentAccount] = useState<CurrentGoogleAccount["account"]>(initial.currentAccount);
  const [calendarTimezone, setCalendarTimezone] = useState(initial.calendarTimezone);
  const [setupCompleted, setSetupCompleted] = useState(initial.setupCompleted);
  const [googleConnectPending, setGoogleConnectPending] = useState(false);
  const [statusLine, setStatusLine] = useState("로컬 API에 연결되어 있습니다.");
  const [workspaceReady, setWorkspaceReady] = useState(false);
  const [resourceProjection, setResourceProjection] = useState<ResourceBrowserProjection>({
    activeSource: "gmail",
    focusedItem: null,
    selectedContext: { items: [], resourceIds: [], selectionHandles: [], labels: [] },
    composerPrompt: "선택한 메일에 대해 질문하거나 업무를 요청하세요...",
    emptyMessage: "자료를 불러오는 중입니다.",
    focusedItemSelected: false,
    toggleFocusedSelection: () => undefined,
    openFocusedContainer: () => undefined,
  });
  const conversation = useConversation({
    currentAccount,
    selectedResourceHandles: resourceProjection.selectedContext.selectionHandles,
    onStatusLine: setStatusLine,
    requestedMode: runtime.runtime_mode.requested_mode,
  });
  const {
    conversations,
    selectedConversationId,
    historyMessages,
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
    handleStartRun,
    handleApprove,
    handleSimpleAction,
    handleAttachDescriptors,
    handleCancelRun,
    handleResumeRun,
    handleResumeAfterReauth,
    handleAdjustContext,
    handleConfirmation,
    handleResolveRecovery,
  } = conversation;
  const restoredOpenRunRef = useRef(false);
  const reauthConnectionCheckRef = useRef<string | null>(null);
  const reauthResumeAttemptRef = useRef<string | null>(null);
  const operationalCommandIds = useRef(new Map<string, string>());

  useEffect(() => {
    if (restoredOpenRunRef.current) {
      return;
    }
    restoredOpenRunRef.current = true;
    if (currentAccount === null) {
      setWorkspaceReady(true);
      return;
    }
    void refreshConversations().then(async (items) => {
      const openConversation = items.find((item) => item.open_run_id !== null);
      if (openConversation?.open_run_id) {
        await selectRun(openConversation.open_run_id);
      }
    }).catch((error: unknown) => {
      setStatusLine(error instanceof ApiClientError ? error.message : "이전 작업을 복구하지 못했습니다.");
    }).finally(() => setWorkspaceReady(true));
  }, [currentAccount, refreshConversations, selectRun]);

  const conversationViewModel = {
    controller: {
      selectedConversationId,
      historyMessages,
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
      handleAttachDescriptors,
      handleCancelRun,
      handleResumeRun,
      handleAdjustContext,
      handleConfirmation,
      handleResolveRecovery,
    },
    resourceContext: {
      selectedResourceIds: resourceProjection.selectedContext.resourceIds,
      selectedResourceLabels: resourceProjection.selectedContext.labels,
      composerPrompt: resourceProjection.composerPrompt,
    },
    formatTime,
    onOpenSettings: () => setSettingsOpen(true),
    onOpenDiagnostics: () => setStatusLine("설정의 Runtime 상태에서 진단 정보를 확인하세요."),
  };
  const refreshRuntimeSummary = useCallback(async (): Promise<void> => {
    const [runtimeResponse, googleResponse, accountResponse, settingsResponse] = await Promise.all([
      getRuntime(),
      getGoogleConnection(),
      getCurrentGoogleAccount(),
      getSettings(),
    ]);
    setRuntime(runtimeResponse);
    setGoogle(googleResponse);
    setCurrentAccount(accountResponse.account);
    setSettings(settingsResponse);
    setTheme(settingsResponse.theme === "DARK" ? "dark" : "light");
    setCalendarTimezone(settingsResponse.timezone);
  }, []);

  useEffect(() => {
    if (runSnapshot?.run.status !== "REAUTH_REQUIRED") {
      reauthConnectionCheckRef.current = null;
      reauthResumeAttemptRef.current = null;
      return;
    }
    const identity = `${runSnapshot.run.run_id}:${runSnapshot.run.version}`;
    const resumeAfterFreshConnection = (): void => {
      if (reauthResumeAttemptRef.current === identity) return;
      reauthResumeAttemptRef.current = identity;
      void handleResumeAfterReauth().catch((error: unknown) => {
        setStatusLine(error instanceof ApiClientError ? error.message : "Google 재인증 후 작업을 재개하지 못했습니다.");
      });
    };
    if (reauthConnectionCheckRef.current !== identity) {
      reauthConnectionCheckRef.current = identity;
      void getGoogleConnection().then((freshConnection) => {
        setGoogle(freshConnection);
        if (freshConnection.connection_status === "CONNECTED") {
          resumeAfterFreshConnection();
        }
      }).catch((error: unknown) => {
        setStatusLine(error instanceof ApiClientError ? error.message : "Google 재인증 상태를 확인하지 못했습니다.");
      });
      return;
    }
    if (google.connection_status === "CONNECTED") resumeAfterFreshConnection();
  }, [google.connection_status, handleResumeAfterReauth, runSnapshot]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  async function handleThemeChange(nextTheme: string): Promise<void> {
    const persistedTheme = nextTheme === "dark" ? "DARK" : "LIGHT";
    setTheme(nextTheme === "dark" ? "dark" : "light");
    try {
      const updated = await updateSettings(
        commandIdFor(`settings:theme:${persistedTheme}`),
        { theme: persistedTheme },
      );
      operationalCommandIds.current.delete(`settings:theme:${persistedTheme}`);
      setSettings(updated);
      setTheme(updated.theme === "DARK" ? "dark" : "light");
    } catch (error) {
      setTheme(settings.theme === "DARK" ? "dark" : "light");
      setStatusLine(error instanceof ApiClientError ? error.message : "테마 설정을 저장하지 못했습니다.");
    }
  }

  async function handleConversationPanelOpenChange(isOpen: boolean): Promise<void> {
    const operation = `settings:conversation-panel:${isOpen ? "open" : "closed"}`;
    try {
      const updated = await updateSettings(commandIdFor(operation), {
        panel_preferences: {
          ...settings.panel_preferences,
          right_panel_default_open: isOpen,
        },
      });
      operationalCommandIds.current.delete(operation);
      setSettings(updated);
    } catch (error) {
      setStatusLine(error instanceof ApiClientError ? error.message : "패널 설정을 저장하지 못했습니다.");
    }
  }

  function commandIdFor(operation: string): string {
    let commandId = operationalCommandIds.current.get(operation);
    if (!commandId) {
      commandId = crypto.randomUUID();
      operationalCommandIds.current.set(operation, commandId);
    }
    return commandId;
  }

  async function handleGoogleConnect(): Promise<void> {
    if (google?.connection_status === "CONNECTED" || googleConnectPending) {
      return;
    }
    setGoogleConnectPending(true);
    try {
      let commandId = operationalCommandIds.current.get("google:connect");
      if (!commandId) { commandId = crypto.randomUUID(); operationalCommandIds.current.set("google:connect", commandId); }
      const response = await startGoogleConnection(commandId);
      operationalCommandIds.current.delete("google:connect");
      window.open(requireOAuthLaunchUrl(response.authorization_url), "_blank", "noopener,noreferrer");
      setStatusLine("Google 연결 완료를 기다리고 있습니다.");
    } catch (error) {
      setStatusLine(error instanceof ApiClientError ? error.message : "Google 연결을 시작하지 못했습니다.");
    } finally {
      setGoogleConnectPending(false);
    }
  }

  if (!workspaceReady) {
    return <main className="startup" aria-busy="true" aria-label="이전 작업 복구 중" />;
  }

  if (!setupCompleted) {
    return (
      <FirstRunOnboardingScreen
        runtime={runtime}
        google={google}
        statusLine={statusLine}
        onConnectGoogle={() => void handleGoogleConnect()}
        onRefreshConnections={refreshRuntimeSummary}
        onComplete={() => {
          setCalendarTimezone(settings.timezone);
          setSetupCompleted(true);
        }}
      />
    );
  }

  return (
    <MainShell
      google={google}
      currentAccount={currentAccount}
      statusLine={statusLine}
      googleConnectPending={googleConnectPending}
      theme={theme}
      onThemeChange={(nextTheme) => void handleThemeChange(nextTheme)}
      conversationPanelDefaultOpen={settings.panel_preferences.right_panel_default_open}
      onConversationPanelOpenChange={(isOpen) => void handleConversationPanelOpenChange(isOpen)}
      onShowHelp={() => setStatusLine("자료를 선택하거나 자연어 요청을 입력해 업무를 시작할 수 있습니다.")}
      onConnectGoogle={() => void handleGoogleConnect()}
      onOpenSettings={() => setSettingsOpen(true)}
      settingsPanel={settingsOpen ? (
        <SettingsDrawer
          runtime={runtime}
          theme={theme}
          onThemeChange={(nextTheme) => void handleThemeChange(nextTheme)}
          onClose={() => setSettingsOpen(false)}
          onOperationalStateChanged={refreshRuntimeSummary}
        />
      ) : null}
    >
        <ResourceSidebar
          scopeKey={`${runtime.service_instance_id}|${currentAccount?.account_id ?? "disconnected"}`}
          accountId={currentAccount?.account_id}
          connected={google.connection_status === "CONNECTED"}
          timezone={calendarTimezone}
          onProjectionChange={setResourceProjection}
        />

        <CenterWorkspace
          resourceViewer={<ResourceViewer projection={resourceProjection} />}
          conversationViewModel={conversationViewModel}
        />

        <ConversationHistoryPanel
          conversations={conversations}
          selectedConversationId={selectedConversationId}
          hasRunSnapshot={runSnapshot !== null}
          onBeginConversation={() => beginConversationProjection(null)}
          onSelectConversation={(conversationId) => void selectConversation(conversationId)}
        />
    </MainShell>
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
  url.searchParams.set("return_to", new URL("/", window.location.origin).toString());
  return url.toString();
}

function formatTime(value: number): string {
  return new Date(value).toLocaleString("ko-KR", { hour12: false });
}
