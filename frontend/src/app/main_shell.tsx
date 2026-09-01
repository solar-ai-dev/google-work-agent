import { useEffect, useState, type ReactNode } from "react";
import type { CurrentGoogleAccount, GoogleConnection } from "../features/settings";
import { TopBar } from "./top_bar";

type Props = {
  google: GoogleConnection | null;
  currentAccount: CurrentGoogleAccount["account"];
  statusLine: string;
  googleConnectPending: boolean;
  onConnectGoogle: () => void;
  onOpenSettings: () => void;
  onShowHelp: () => void;
  theme: string;
  onThemeChange: (theme: string) => void;
  conversationPanelDefaultOpen: boolean;
  onConversationPanelOpenChange: (isOpen: boolean) => void;
  settingsPanel: ReactNode;
  children: ReactNode;
};

export function MainShell({
  settingsPanel,
  children,
  conversationPanelDefaultOpen,
  onConversationPanelOpenChange,
  ...topBarProps
}: Props): JSX.Element {
  const [resourcePanelOpen, setResourcePanelOpen] = useState(true);
  const [conversationPanelOpen, setConversationPanelOpen] = useState(conversationPanelDefaultOpen);

  useEffect(() => {
    setConversationPanelOpen(conversationPanelDefaultOpen);
  }, [conversationPanelDefaultOpen]);

  function toggleConversationPanel(): void {
    const next = !conversationPanelOpen;
    setConversationPanelOpen(next);
    onConversationPanelOpenChange(next);
  }

  return (
    <div className="app-shell">
      <TopBar
        {...topBarProps}
        onToggleResourcePanel={() => setResourcePanelOpen((current) => !current)}
        onToggleConversationPanel={toggleConversationPanel}
        resourcePanelOpen={resourcePanelOpen}
        conversationPanelOpen={conversationPanelOpen}
      />
      <div
        className={`shell-grid ${resourcePanelOpen ? "" : "resource-panel-closed"} ${conversationPanelOpen ? "" : "conversation-panel-closed"}`}
      >
        {children}
      </div>
      {settingsPanel}
    </div>
  );
}
