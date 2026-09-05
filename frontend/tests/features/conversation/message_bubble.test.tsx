import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { AssistantMessageBubble } from "../../../src/features/conversation/MessageBubble";

test("assistant answers render as a left conversation bubble with a timestamp", () => {
  render(<AssistantMessageBubble content="요청한 내용을 정리했습니다." createdAtMs={new Date(2026, 8, 3, 15, 7).getTime()} />);

  const answer = screen.getByRole("article", { name: "에이전트 응답" });
  expect(answer).toHaveClass("message-row--assistant");
  expect(answer.querySelector(".message-bubble--assistant")).toHaveTextContent("요청한 내용을 정리했습니다.");
  expect(answer.querySelector(".message-timestamp")).not.toBeEmptyDOMElement();
});

test("assistant answers render CommonMark structure and safe external links", () => {
  render(
    <AssistantMessageBubble
      content={"## 최신 결정\n\n- **네비게이션바**로 확정\n- [관련 문서](https://example.com)"}
      createdAtMs={new Date(2026, 8, 3, 15, 7).getTime()}
    />,
  );

  expect(screen.getByRole("heading", { level: 2, name: "최신 결정" })).toBeVisible();
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
  expect(screen.getByText("네비게이션바", { selector: "strong" })).toBeVisible();
  expect(screen.getByRole("link", { name: "관련 문서" })).toHaveAttribute(
    "rel",
    "noreferrer noopener",
  );
  expect(screen.getByRole("link", { name: "관련 문서" })).toHaveAttribute("target", "_blank");
});
