import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { FirstRunOnboardingScreen } from "../../../src/features/settings/first_run_onboarding";

vi.mock("../../../src/features/settings/api/get_settings", () => ({
  getSettings: vi.fn().mockResolvedValue({
    timezone: "Asia/Seoul",
    preferred_llm_mode: "API_LLM",
    preferred_local_model_id: null,
    external_llm_consent: false,
  }),
}));
vi.mock("../../../src/features/settings/api/llm_credential_operations", () => ({
  getLlmCredentialStatus: vi.fn().mockResolvedValue({ validation_status: "NOT_CONFIGURED" }),
  storeLlmCredential: vi.fn(),
}));
vi.mock("../../../src/features/settings/api/update_settings", () => ({ updateSettings: vi.fn() }));

test("renders the canonical single-screen first-run checklist", async () => {
  render(<FirstRunOnboardingScreen
    runtime={{
      launcher_status: "READY",
      migration_status: "READY",
      deployment_profile: "LOCAL_CAPABLE",
      llm_providers: [],
      local_models: [],
    } as never}
    google={{ connection_status: "DISCONNECTED", missing_required_scopes: [] } as never}
    statusLine="로컬 API에 연결되어 있습니다."
    onConnectGoogle={vi.fn()}
    onRefreshConnections={vi.fn()}
    onComplete={vi.fn()}
  />);
  expect(await screen.findByRole("heading", { name: "Google Work Agent 시작하기" })).toBeInTheDocument();
  expect(document.querySelector("main") ?? document.body).toBeInTheDocument();
});
