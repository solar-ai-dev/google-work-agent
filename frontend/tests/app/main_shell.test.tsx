import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { MainShell } from "../../src/app/main_shell";

beforeEach(() => localStorage.clear());

test("owns shell panel visibility and persists only UI preferences", async () => {
  const { container } = render(<MainShell google={null} currentAccount={null} statusLine="ready" googleConnectPending={false} onConnectGoogle={vi.fn()} onOpenSettings={vi.fn()} onShowHelp={vi.fn()} theme="light" onThemeChange={vi.fn()} settingsPanel={<div>settings panel</div>}><aside>resources</aside><main>workspace</main><aside>conversations</aside></MainShell>);

  await userEvent.click(screen.getByRole("button", { name: "Google 패널 전환" }));
  expect(container.querySelector(".shell-grid")).toHaveClass("resource-panel-closed");
  expect(localStorage.getItem("gwa.shell-preferences")).toContain("resourcePanelOpen");
  expect(screen.getByText("settings panel")).toBeInTheDocument();
});
