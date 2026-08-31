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
  settingsPanel: ReactNode;
  children: ReactNode;
};

const SHELL_PREFERENCES_KEY = "gwa.shell-preferences";

export function MainShell({ settingsPanel, children, ...topBarProps }: Props): JSX.Element {
  const [panels, setPanels] = useState(readPanelPreferences);

  useEffect(() => {
    localStorage.setItem(SHELL_PREFERENCES_KEY, JSON.stringify(panels));
  }, [panels]);

  return (
    <div className="app-shell">
      <TopBar
        {...topBarProps}
        onToggleResourcePanel={() => setPanels((current) => ({ ...current, resourcePanelOpen: !current.resourcePanelOpen }))}
        onToggleConversationPanel={() => setPanels((current) => ({ ...current, conversationPanelOpen: !current.conversationPanelOpen }))}
        resourcePanelOpen={panels.resourcePanelOpen}
        conversationPanelOpen={panels.conversationPanelOpen}
      />
      <div
        className={`shell-grid ${panels.resourcePanelOpen ? "" : "resource-panel-closed"} ${panels.conversationPanelOpen ? "" : "conversation-panel-closed"}`}
      >
        {children}
      </div>
      {settingsPanel}
    </div>
  );
}

function readPanelPreferences(): { resourcePanelOpen: boolean; conversationPanelOpen: boolean } {
  try {
    const value = JSON.parse(localStorage.getItem(SHELL_PREFERENCES_KEY) ?? "null") as Record<string, unknown> | null;
    return {
      resourcePanelOpen: value?.resourcePanelOpen !== false,
      conversationPanelOpen: value?.conversationPanelOpen !== false,
    };
  } catch {
    return { resourcePanelOpen: true, conversationPanelOpen: true };
  }
}
