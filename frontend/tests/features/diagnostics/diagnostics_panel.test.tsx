import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { DiagnosticsPanel } from "../../../src/features/diagnostics/diagnostics_panel";
import * as api from "../../../src/features/diagnostics/api/create_diagnostic_bundle";

vi.mock("../../../src/features/diagnostics/api/create_diagnostic_bundle", () => ({ createDiagnosticBundle: vi.fn() }));

test("DiagnosticsPanel exposes only opaque bundle metadata", async () => {
  vi.mocked(api.createDiagnosticBundle).mockResolvedValue({ schema_version: 1, bundle_ref: "bundle-ref", scope: "LAST_24H", created_at_ms: 1, size_bytes: 20 });
  render(<DiagnosticsPanel runtime={{ launcher_status: "READY", database_status: "READY", migration_status: "READY", sse_status: "READY", manifest_status: "VALID", safe_mode: false, recent_sanitized_error_code: null } as never} onRefresh={vi.fn()} />);
  await userEvent.setup().click(screen.getByRole("button", { name: "진단 번들 만들기" }));
  expect(await screen.findByText(/bundle-ref/)).toBeInTheDocument();
  expect(document.body.textContent).not.toContain("C:\\");
});
