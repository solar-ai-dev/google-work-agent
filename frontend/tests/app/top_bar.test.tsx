import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { TopBar } from "../../src/app/top_bar";

test("composes account, connection, panel, theme, and settings controls", async () => {
  const toggleTheme = vi.fn();
  render(<TopBar google={{ connection_status: "CONNECTED" } as never} currentAccount={{ email: "user@example.com" } as never} statusLine="ready" googleConnectPending={false} onConnectGoogle={vi.fn()} onOpenSettings={vi.fn()} onShowHelp={vi.fn()} onToggleResourcePanel={vi.fn()} onToggleConversationPanel={vi.fn()} resourcePanelOpen conversationPanelOpen theme="light" onThemeChange={toggleTheme} />);

  expect(screen.getByText("Google 연결됨")).toBeInTheDocument();
  expect(screen.getByText("user@example.com")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Google 패널 전환" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByRole("button", { name: "테마 전환" }));
  expect(toggleTheme).toHaveBeenCalledWith("dark");
});
