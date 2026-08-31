import type { ResourceItem } from "../../api/contract";

export type CalendarMonthRange = {
  gridStart: string;
  gridEnd: string;
  days: string[];
};

type Props = {
  monthAnchor: string;
  timezone: string;
  items: ResourceItem[];
  selectedDate: string;
  loading: boolean;
  error: string | null;
  onPreviousMonth: () => void;
  onNextMonth: () => void;
  onSelectDate: (date: string) => void;
  onSelectEvent: (item: ResourceItem) => void;
};

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

export function calendarMonthRange(monthAnchor: string): CalendarMonthRange {
  const [year, month] = monthAnchor.split("-").map(Number);
  const monthStart = new Date(Date.UTC(year, month - 1, 1));
  const gridStart = new Date(monthStart);
  gridStart.setUTCDate(gridStart.getUTCDate() - gridStart.getUTCDay());
  const monthEnd = new Date(Date.UTC(year, month, 0));
  const gridEnd = new Date(monthEnd);
  gridEnd.setUTCDate(gridEnd.getUTCDate() + (7 - gridEnd.getUTCDay()));
  const days: string[] = [];
  for (const date = new Date(gridStart); date < gridEnd; date.setUTCDate(date.getUTCDate() + 1)) {
    days.push(dateKey(date));
  }
  return { gridStart: days[0], gridEnd: dateKey(gridEnd), days };
}

export function configuredDateKey(now: Date, timezone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const value = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${value("year")}-${value("month")}-${value("day")}`;
}

export function calendarRangeBoundary(date: string, timezone: string): string {
  const [year, month, day] = date.split("-").map(Number);
  return new Date(zonedMidnight(year, month, day, timezone)).toISOString();
}

export function CalendarMonthView({
  monthAnchor,
  timezone,
  items,
  selectedDate,
  loading,
  error,
  onPreviousMonth,
  onNextMonth,
  onSelectDate,
  onSelectEvent,
}: Props): JSX.Element {
  const range = calendarMonthRange(monthAnchor);
  const eventDays = new Map(range.days.map((day) => [day, [] as ResourceItem[]]));
  for (const item of items) {
    for (const date of eventDates(item, range, timezone)) {
      eventDays.get(date)?.push(item);
    }
  }
  const selectedItems = [...(eventDays.get(selectedDate) ?? [])].sort(compareStart);
  const [year, month] = monthAnchor.split("-").map(Number);
  const monthLabel = `${year}년 ${month}월`;

  return (
    <section className="calendar-month-view" aria-label="월간 일정">
      <header className="calendar-month-header">
        <button className="icon-button" type="button" aria-label="이전 달" onClick={onPreviousMonth}>‹</button>
        <strong>{monthLabel}</strong>
        <button className="icon-button" type="button" aria-label="다음 달" onClick={onNextMonth}>›</button>
      </header>
      <div className="calendar-weekdays" aria-hidden="true">
        {WEEKDAYS.map((day) => <span key={day}>{day}</span>)}
      </div>
      <div className="calendar-grid">
        {range.days.map((date) => {
          const count = eventDays.get(date)?.length ?? 0;
          return (
            <button
              key={date}
              type="button"
              className={`calendar-day ${date.startsWith(monthAnchor) ? "" : "outside-month"} ${date === selectedDate ? "selected" : ""}`}
              aria-label={`${date}${count ? ` 일정 ${count}개` : ""}`}
              onClick={() => onSelectDate(date)}
            >
              <span>{Number(date.slice(-2))}</span>
              {count ? <small className="calendar-event-marker" aria-label={`일정 ${count}개`}>•{count > 1 ? count : ""}</small> : null}
            </button>
          );
        })}
      </div>
      {loading ? <p className="muted" aria-live="polite">일정을 불러오는 중입니다.</p> : null}
      {error ? <p className="status-bad">{error}</p> : null}
      {!error ? (
        <section className="calendar-selected-events" aria-label="선택 날짜 일정">
          <h3>{formatSelectedDate(selectedDate, timezone)}</h3>
          {selectedItems.length ? (
            <ul>
              {selectedItems.map((item) => (
                <li key={item.resource_id}>
                  <button type="button" onClick={() => onSelectEvent(item)}>
                    <time>{eventTimeLabel(item, selectedDate, timezone)}</time>
                    <span>{item.title || "제목 정보 없음"}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="muted">선택한 날짜에 일정이 없습니다.</p>}
        </section>
      ) : null}
    </section>
  );
}

function eventDates(item: ResourceItem, range: CalendarMonthRange, timezone: string): string[] {
  const start = value(item.metadata.start);
  const end = value(item.metadata.end);
  if (!start || !end) return [];
  if (dateOnly(start) && dateOnly(end)) return overlappingDateKeys(start, end, range);
  const startTime = Date.parse(start);
  const endTime = Date.parse(end);
  if (!Number.isFinite(startTime) || !Number.isFinite(endTime) || endTime <= startTime) return [];
  const dates: string[] = [];
  for (const date of range.days) {
    const [year, month, day] = date.split("-").map(Number);
    const dayStart = zonedMidnight(year, month, day, timezone);
    const nextDayStart = zonedMidnight(year, month, day + 1, timezone);
    if (startTime < nextDayStart && endTime > dayStart) dates.push(date);
  }
  return dates;
}

function overlappingDateKeys(start: string, end: string, range: CalendarMonthRange): string[] {
  return range.days.filter((date) => date >= start && date < end);
}

function zonedMidnight(year: number, month: number, day: number, timezone: string): number {
  const candidate = Date.UTC(year, month - 1, day);
  const offset = timezoneOffset(candidate, timezone);
  return candidate - offset;
}

function timezoneOffset(timestamp: number, timezone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(timestamp));
  const value = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? 0);
  return Date.UTC(value("year"), value("month") - 1, value("day"), value("hour"), value("minute"), value("second")) - timestamp;
}

function eventTimeLabel(item: ResourceItem, selectedDate: string, timezone: string): string {
  const start = value(item.metadata.start);
  if (!start) return "";
  if (dateOnly(start)) return "종일";
  if (configuredDateKey(new Date(start), timezone) !== selectedDate) return "종일";
  return new Intl.DateTimeFormat("ko-KR", { timeZone: timezone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(start));
}

function compareStart(left: ResourceItem, right: ResourceItem): number {
  return String(left.metadata.start ?? "").localeCompare(String(right.metadata.start ?? ""));
}

function formatSelectedDate(date: string, timezone: string): string {
  const [year, month, day] = date.split("-").map(Number);
  return new Intl.DateTimeFormat("ko-KR", { timeZone: timezone, month: "long", day: "numeric", weekday: "short" }).format(new Date(Date.UTC(year, month - 1, day, 12)));
}

function dateOnly(value: string): boolean { return /^\d{4}-\d{2}-\d{2}$/.test(value); }
function dateKey(date: Date): string { return date.toISOString().slice(0, 10); }
function value(value: unknown): string | null { return typeof value === "string" && value ? value : null; }
