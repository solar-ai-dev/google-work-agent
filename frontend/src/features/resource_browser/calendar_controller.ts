import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClientError } from "../../api/client";
import type { ResourceItem } from "../../api/contract";
import { calendarMonthRange, calendarRangeBoundary, configuredDateKey } from "./calendar_month_view";
import { listResources } from "./api/list_resources";
import { ResourceBrowserSessionCache } from "./session_page_cache";

type CalendarMonthRequestInput = {
  cacheKey: string;
  calendarId: string | null;
  timeMin: string;
  timeMax: string;
};

type CalendarMonthCacheEntry = {
  items: ResourceItem[];
};

const CALENDAR_BROWSE_SIZE = 100;

function cacheKey({
  accountId,
  calendarId,
  timeMin,
  timeMax,
}: {
  accountId: string | null | undefined;
  calendarId: string | null;
  timeMin: string;
  timeMax: string;
}): string {
  return [accountId ?? "anon", "calendar", calendarId ?? "", timeMin, timeMax].join("|");
}

function shiftMonth(monthAnchor: string, offset: number): string {
  const [year, month] = monthAnchor.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1 + offset, 1));
  return `${shifted.getUTCFullYear()}-${String(shifted.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function useCalendar({
  accountId,
  calendarId,
  active,
  timezone,
}: {
  accountId: string | null | undefined;
  calendarId: string | null;
  active: boolean;
  timezone: string;
}) {
  const [monthAnchor, setMonthAnchor] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [items, setItems] = useState<ResourceItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cacheRef = useRef(new ResourceBrowserSessionCache<CalendarMonthCacheEntry>());
  const requestRef = useRef({ generation: 0, cacheKey: "" });
  const cacheGenerationRef = useRef(new Map<string, number>());
  const inFlightRef = useRef(new Map<string, Promise<ResourceItem[]>>());

  useEffect(() => {
    cacheRef.current.bindScope(accountId ?? "anonymous");
  }, [accountId]);

  const monthRequestInput = useCallback((nextMonthAnchor: string): CalendarMonthRequestInput => {
    const range = calendarMonthRange(nextMonthAnchor);
    const timeMin = calendarRangeBoundary(range.gridStart, timezone);
    const timeMax = calendarRangeBoundary(range.gridEnd, timezone);
    return {
      cacheKey: cacheKey({ accountId, calendarId, timeMin, timeMax }),
      calendarId,
      timeMin,
      timeMax,
    };
  }, [accountId, calendarId, timezone]);

  const requestMonth = useCallback((input: CalendarMonthRequestInput, force = false): Promise<ResourceItem[]> => {
    const cacheGeneration = force
      ? (cacheGenerationRef.current.get(input.cacheKey) ?? 0) + 1
      : (cacheGenerationRef.current.get(input.cacheKey) ?? 0);
    cacheGenerationRef.current.set(input.cacheKey, cacheGeneration);
    if (force) cacheRef.current.delete(input.cacheKey);
    const inFlightKey = `${input.cacheKey}|${cacheGeneration}`;
    const existing = inFlightRef.current.get(inFlightKey);
    if (existing) return existing;

    const request = (async (): Promise<ResourceItem[]> => {
      let nextItems: ResourceItem[] = [];
      let pageToken: string | null = null;
      do {
        const response = await listResources({
          source: "calendar",
          calendarId: input.calendarId,
          continuation: pageToken,
          pageSize: CALENDAR_BROWSE_SIZE,
          timeMin: input.timeMin,
          timeMax: input.timeMax,
        });
        nextItems = [...nextItems, ...response.items];
        pageToken = response.next_page_token;
      } while (pageToken !== null);
      if (cacheGenerationRef.current.get(input.cacheKey) === cacheGeneration) {
        cacheRef.current.set(input.cacheKey, { items: nextItems });
      }
      return nextItems;
    })();
    inFlightRef.current.set(inFlightKey, request);
    const clearInFlight = (): void => {
      if (inFlightRef.current.get(inFlightKey) === request) inFlightRef.current.delete(inFlightKey);
    };
    void request.then(clearInFlight, clearInFlight);
    return request;
  }, []);

  const prefetchAdjacentMonths = useCallback((nextMonthAnchor: string): void => {
    for (const offset of [-1, 1]) {
      const input = monthRequestInput(shiftMonth(nextMonthAnchor, offset));
      if (cacheRef.current.has(input.cacheKey)) continue;
      void requestMonth(input).catch(() => undefined);
    }
  }, [monthRequestInput, requestMonth]);

  const loadMonth = useCallback(async (nextMonthAnchor: string, force = false): Promise<void> => {
    const input = monthRequestInput(nextMonthAnchor);
    const generation = requestRef.current.generation + 1;
    requestRef.current = { generation, cacheKey: input.cacheKey };
    const isCurrentRequest = (): boolean => (
      requestRef.current.generation === generation
      && requestRef.current.cacheKey === input.cacheKey
    );
    const cached = !force ? cacheRef.current.get(input.cacheKey) : undefined;
    if (cached) {
      setItems(cached.items);
      setLoading(false);
      setError(null);
      prefetchAdjacentMonths(nextMonthAnchor);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const nextItems = await requestMonth(input, force);
      if (!isCurrentRequest()) return;
      setItems(nextItems);
      setLoading(false);
      setError(null);
      prefetchAdjacentMonths(nextMonthAnchor);
    } catch (cause) {
      if (!isCurrentRequest()) return;
      setLoading(false);
      setError(cause instanceof ApiClientError ? cause.message : "일정을 불러오지 못했습니다.");
    }
  }, [monthRequestInput, prefetchAdjacentMonths, requestMonth]);

  const selectDate = useCallback((date: string): void => setSelectedDate(date), []);
  const goPreviousMonth = useCallback((): void => {
    setMonthAnchor((current) => {
      if (current === null) return current;
      const previous = shiftMonth(current, -1);
      setSelectedDate(`${previous}-01`);
      return previous;
    });
  }, []);
  const goNextMonth = useCallback((): void => {
    setMonthAnchor((current) => {
      if (current === null) return current;
      const next = shiftMonth(current, 1);
      setSelectedDate(`${next}-01`);
      return next;
    });
  }, []);
  const refresh = useCallback(async (): Promise<void> => {
    if (monthAnchor !== null) await loadMonth(monthAnchor, true);
  }, [loadMonth, monthAnchor]);
  const reset = useCallback((): void => {
    requestRef.current = { generation: requestRef.current.generation + 1, cacheKey: "" };
    cacheRef.current.clear();
    cacheGenerationRef.current.clear();
    inFlightRef.current.clear();
    setMonthAnchor(null);
    setSelectedDate(null);
    setItems([]);
    setLoading(false);
    setError(null);
  }, []);

  useEffect(() => {
    if (!active) return;
    const nextMonthAnchor = monthAnchor ?? configuredDateKey(new Date(), timezone).slice(0, 7);
    if (monthAnchor === null) {
      setMonthAnchor(nextMonthAnchor);
      setSelectedDate(configuredDateKey(new Date(), timezone));
      return;
    }
    void loadMonth(nextMonthAnchor);
  }, [active, loadMonth, monthAnchor, timezone]);

  return {
    monthAnchor,
    selectedDate,
    items,
    loading,
    error,
    selectDate,
    goPreviousMonth,
    goNextMonth,
    refresh,
    reset,
  };
}

export type CalendarController = ReturnType<typeof useCalendar>;
