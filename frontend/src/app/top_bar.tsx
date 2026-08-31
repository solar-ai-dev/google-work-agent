import type { CurrentGoogleAccount, GoogleConnection } from "../features/settings";

type Props = {
  google: GoogleConnection | null;
  currentAccount: CurrentGoogleAccount["account"];
  statusLine: string;
  googleConnectPending: boolean;
  onConnectGoogle: () => void;
  onOpenSettings: () => void;
  onShowHelp: () => void;
  onToggleResourcePanel: () => void;
  onToggleConversationPanel: () => void;
  resourcePanelOpen: boolean;
  conversationPanelOpen: boolean;
  theme: string;
  onThemeChange: (theme: string) => void;
};

export function TopBar({
  google,
  currentAccount,
  statusLine,
  googleConnectPending,
  onConnectGoogle,
  onOpenSettings,
  onShowHelp,
  onToggleResourcePanel,
  onToggleConversationPanel,
  resourcePanelOpen,
  conversationPanelOpen,
  theme,
  onThemeChange,
}: Props): JSX.Element {
  const connected = google?.connection_status === "CONNECTED";
  return (
    <header className="topbar">
      <div className="topbar-brand">
        <button
          className="icon-button topbar-icon-button"
          type="button"
          aria-label="Google 패널 전환"
          aria-pressed={resourcePanelOpen}
          onClick={onToggleResourcePanel}
        >
          ☰
        </button>
        <span className="brand-mark" aria-hidden="true">G</span>
        <strong>Google Work Agent</strong>
        <span className="sr-only" aria-live="polite">{statusLine}</span>
      </div>
      <div className="topbar-connection" aria-live="polite">
        <span className={`pill ${connected ? "connection-connected" : "connection-disconnected"}`}>
          {connected ? "Google 연결됨" : "Google 미연결"}
        </span>
      </div>
      <div className="topbar-actions">
        {currentAccount ? <span className="muted">{currentAccount.email}</span> : null}
        <button className="icon-button topbar-icon-button" type="button" aria-label="도움말" title="도움말" onClick={onShowHelp}>?</button>
        {!connected ? (
          <button className="button-primary" type="button" disabled={googleConnectPending} onClick={onConnectGoogle}>
            {googleConnectPending ? "Google 연결 중..." : "Google 연결"}
          </button>
        ) : null}
        <button
          className="icon-button topbar-icon-button"
          type="button"
          aria-label="테마 전환"
          onClick={() => onThemeChange(theme === "dark" ? "light" : "dark")}
        >
          {theme === "dark" ? "☀" : "☾"}
        </button>
        <button
          className="icon-button topbar-icon-button"
          type="button"
          aria-label="대화 내역 전환"
          aria-pressed={conversationPanelOpen}
          onClick={onToggleConversationPanel}
        >
          ◫
        </button>
        <button className="icon-button topbar-icon-button" type="button" aria-label="설정" title="설정" onClick={onOpenSettings}>⚙</button>
      </div>
    </header>
  );
}
