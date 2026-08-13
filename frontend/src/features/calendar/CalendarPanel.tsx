import { CalendarMonthView } from "../../app/CalendarMonthView";
import type { ResourceItem } from "../../api/contract";
import type { CalendarController } from "./useCalendar";

type Props = {
  calendar: CalendarController;
  timezone: string;
  filter: string;
  onFilterChange: (filter: string) => void;
  onFocusEvent: (item: ResourceItem) => void;
};

export function CalendarPanel({
  calendar,
  timezone,
  filter,
  onFilterChange,
  onFocusEvent,
}: Props): JSX.Element {
  return (
    <>
      <div className="resource-search-row">
        <label className="resource-search">
          <span className="resource-search-icon" aria-hidden="true">⌕</span>
          <input aria-label="일정 검색" placeholder="일정 검색" value={filter} onChange={(event) => onFilterChange(event.target.value)} />
        </label>
      </div>
      {calendar.monthAnchor && calendar.selectedDate ? (
        <CalendarMonthView
          monthAnchor={calendar.monthAnchor}
          timezone={timezone}
          items={calendar.items}
          selectedDate={calendar.selectedDate}
          loading={calendar.loading}
          error={calendar.error}
          onPreviousMonth={calendar.goPreviousMonth}
          onNextMonth={calendar.goNextMonth}
          onSelectDate={calendar.selectDate}
          onSelectEvent={onFocusEvent}
        />
      ) : null}
    </>
  );
}
