import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { FirstRunOnboardingScreen } from "../../../src/features/settings/first_run_onboarding";

vi.mock("../../../src/api", () => ({
  getSettings: vi.fn().mockResolvedValue({ timezone: "Asia/Seoul", default_calendar_id: null, default_tasklist_id: null, external_llm_consent: false }),
  getLLMConnection: vi.fn().mockResolvedValue({ validation_status: "MISSING" }),
  patchSettings: vi.fn(),
  storeLLMApiKey: vi.fn(),
}));

test("renders the canonical single-screen first-run checklist", async () => {
  render(<FirstRunOnboardingScreen runtime={{ launcher_status: "READY", migration_status: "READY" } as never} google={{ connection_status: "DISCONNECTED" } as never} onConnectGoogle={vi.fn()} onRefreshConnections={vi.fn()} onComplete={vi.fn()} />);
  expect(await screen.findByRole("heading", { name: "Google Work Agent 시작하기" })).toBeInTheDocument();
  expect(document.querySelector("main") ?? document.body).toBeInTheDocument();
});
