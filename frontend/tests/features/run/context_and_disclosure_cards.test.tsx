import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { ContextPreviewCard } from "../../../src/features/run/context_preview_card";
import { ExternalLlmDisclosureCard } from "../../../src/features/run/external_llm_disclosure_card";

beforeEach(() => localStorage.clear());

test("renders the canonical context preview and invokes an exclusion adjustment", async () => {
  const adjust = vi.fn().mockResolvedValue(undefined);
  render(<ContextPreviewCard preview={{
    schema_version: 1,
    run_id: "run-1",
    retrieval_revision: 3,
    items: [{ segment_id: "segment-1", role: "SUPPORTS", source: "gmail", resource_type: "gmail_message", resource_id: "message-1", display_label: "프로젝트 메일", excerpt: "마감은 금요일입니다." }],
    gmail_count: 1,
    tasks_count: 0,
    calendar_count: 0,
    adjustment_allowed: true,
    allowed_adjustments: ["EXCLUDE_EVIDENCE", "RETRIEVE_MORE"],
  }} busy={false} onAdjust={adjust} />);

  expect(screen.getByRole("button", { name: "사용 컨텍스트 1개" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "사용 컨텍스트 1개" }));
  expect(screen.getByRole("dialog", { name: "사용 컨텍스트 1개" })).toHaveTextContent("마감은 금요일입니다.");
  await userEvent.click(screen.getByRole("checkbox", { name: "프로젝트 메일 제외 선택" }));
  await userEvent.click(screen.getByRole("button", { name: "선택한 근거 제외" }));
  expect(adjust).toHaveBeenCalledWith("EXCLUDE_EVIDENCE", ["segment-1"]);
});

test("renders a two-line external LLM snackbar and permanently dismisses it", async () => {
  const scope = {
    schema_version: 1,
    run_id: "run-1",
    scope_revision: 2,
    scope_hash: "a".repeat(64),
    source_kinds: ["gmail", "calendar"],
    data_classes: ["USER_REQUEST", "EVIDENCE_EXCERPT"],
  } as const;
  render(<ExternalLlmDisclosureCard scope={{
    ...scope,
  }} />);

  const snackbar = screen.getByRole("status", { name: "외부 LLM 전송 안내" });
  expect(snackbar).toHaveTextContent("외부 API LLM 전송 안내");
  expect(snackbar).toHaveTextContent("이 Run의 추론을 위해 아래 범위가 외부 LLM Provider로 전송될 수 있습니다.");
  expect(snackbar).not.toHaveTextContent("gmail");
  await userEvent.click(screen.getByRole("button", { name: "다시 보지 않음" }));
  expect(screen.queryByRole("status", { name: "외부 LLM 전송 안내" })).not.toBeInTheDocument();
  expect(localStorage.getItem("gwa.external-llm-disclosure.dismissed")).toBe("true");
});
