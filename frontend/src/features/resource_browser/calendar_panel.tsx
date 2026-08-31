import { CalendarMonthView } from "./calendar_month_view";
import type { ResourceItem } from "../../api/contract";

type CalendarPanelController = {
  monthAnchor: string | null;
  selectedDate: string | null;
  items: ResourceItem[];
  loading: boolean;
  error: string | null;
  goPreviousMonth: () => void;
  goNextMonth: () => void;
  selectDate: (date: string) => void;
};

type Props = {
  calendar: CalendarPanelController;
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
          <svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <circle cx="10.5" cy="10.5" r="5.75" />
            <path d="m15 15 4.25 4.25" />
          </svg>
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
