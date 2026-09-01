import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { MainShell } from "../../src/app/main_shell";

test("keeps temporary resource visibility local and delegates persisted right-panel preference", async () => {
  const onConversationPanelOpenChange = vi.fn();
  const { container } = render(<MainShell google={null} currentAccount={null} statusLine="ready" googleConnectPending={false} onConnectGoogle={vi.fn()} onOpenSettings={vi.fn()} onShowHelp={vi.fn()} theme="light" onThemeChange={vi.fn()} conversationPanelDefaultOpen={false} onConversationPanelOpenChange={onConversationPanelOpenChange} settingsPanel={<div>settings panel</div>}><aside>resources</aside><main>workspace</main><aside>conversations</aside></MainShell>);

  expect(container.querySelector(".shell-grid")).toHaveClass("conversation-panel-closed");

  await userEvent.click(screen.getByRole("button", { name: "Google 패널 전환" }));
  expect(container.querySelector(".shell-grid")).toHaveClass("resource-panel-closed");

  await userEvent.click(screen.getByRole("button", { name: "대화 내역 전환" }));
  expect(onConversationPanelOpenChange).toHaveBeenCalledWith(true);
  expect(localStorage.length).toBe(0);
  expect(screen.getByText("settings panel")).toBeInTheDocument();
});
