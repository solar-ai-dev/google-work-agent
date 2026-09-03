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
