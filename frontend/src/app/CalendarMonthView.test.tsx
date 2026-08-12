import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { ResourceItem } from "../api/contract";
import { CalendarMonthView, calendarMonthRange } from "./CalendarMonthView";

function event(overrides: Partial<ResourceItem> = {}): ResourceItem {
  return {
    source: "calendar",
    resource_type: "calendar_event",
    resource_id: "event-1",
    parent_id: "primary",
    title: "회의",
    subtitle: null,
    link_url: "https://calendar.google.com/",
    version: "1",
    related_resource_ids: [],
    metadata: { start: "2026-08-10T09:00:00+09:00", end: "2026-08-10T10:00:00+09:00" },
    ...overrides,
  };
}

test("builds a Sunday-start month grid and renders markers plus the selected date list", async () => {
  const user = userEvent.setup();
  const onSelectDate = vi.fn();
  render(
    <CalendarMonthView
      monthAnchor="2026-08"
      timezone="Asia/Seoul"
      selectedDate="2026-08-10"
      loading={false}
      error={null}
      items={[
        event(),
        event({ resource_id: "event-all-day", title: "휴가", metadata: { start: "2026-08-10", end: "2026-08-12" } }),
      ]}
      onPreviousMonth={vi.fn()}
      onNextMonth={vi.fn()}
      onSelectDate={onSelectDate}
      onSelectEvent={vi.fn()}
    />,
  );

  expect(calendarMonthRange("2026-08").gridStart).toBe("2026-07-26");
  expect(screen.getByText("일")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "2026-08-10 일정 2개" })).toBeInTheDocument();
  expect(screen.getByText("09:00")).toBeInTheDocument();
  expect(screen.getByText("종일")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "2026-08-11 일정 1개" }));
  expect(onSelectDate).toHaveBeenCalledWith("2026-08-11");
});

test("does not render an event marker outside an all-day event's exclusive end date", () => {
  render(
    <CalendarMonthView
      monthAnchor="2026-08"
      timezone="Asia/Seoul"
      selectedDate="2026-08-12"
      loading={false}
      error={null}
      items={[event({ metadata: { start: "2026-08-10", end: "2026-08-12" } })]}
      onPreviousMonth={vi.fn()}
      onNextMonth={vi.fn()}
      onSelectDate={vi.fn()}
      onSelectEvent={vi.fn()}
    />,
  );

  expect(screen.getByRole("button", { name: "2026-08-12" })).toBeInTheDocument();
});
