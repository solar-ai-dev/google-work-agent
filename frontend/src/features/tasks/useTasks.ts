import { useCallback, useEffect, useRef, useState } from "react";
import { listTaskResources } from "../../api";
import { ApiClientError } from "../../api/client";
import type { ResourceItem } from "../../api/contract";

export type TaskSort = "provider" | "scheduled_date";
type SourceCount = { value: number; exact: boolean } | null;
type TaskCacheEntry = { items: ResourceItem[]; nextPageToken: string | null; totalCount: number | null };

const UI_PAGE_SIZE = 20;
const PROVIDER_BATCH_SIZE = 100;

function cacheKey(accountId: string | null | undefined, parentId: string | null, sort: TaskSort, filter: string): string {
  return [accountId ?? "anon", parentId ?? "", sort, filter.trim().toLowerCase()].join("|");
}

function taskScheduledDate(item: ResourceItem): string | null {
  const value = item.metadata.scheduled_date;
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null;
}

function sortByScheduledDate(items: ResourceItem[]): ResourceItem[] {
  return [...new Map(items.map((item) => [item.resource_id, item])).values()].sort((left, right) => {
    const leftDate = taskScheduledDate(left);
    const rightDate = taskScheduledDate(right);
    if (leftDate === null) return rightDate === null ? 0 : 1;
    if (rightDate === null) return -1;
    return leftDate.localeCompare(rightDate);
  });
}

export function useTasks({
  accountId,
  parentId,
  active,
  filter,
}: {
  accountId: string | null | undefined;
  parentId: string | null;
  active: boolean;
  filter: string;
}) {
  const [items, setItems] = useState<ResourceItem[]>([]);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [lastLoadedPageIndex, setLastLoadedPageIndex] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState<number | null>(null);
  const [sort, setSortState] = useState<TaskSort>("provider");
  const [count, setCount] = useState<SourceCount>(null);
  const [completed, setCompleted] = useState({ expanded: false, initialized: false, items: [] as ResourceItem[], pageIndex: 0, loading: false, error: null as string | null });
  const cacheRef = useRef(new Map<string, TaskCacheEntry>());
  const requestRef = useRef({ generation: 0, key: "" });
  const completedRequestRef = useRef(0);
  const preloadRef = useRef<Promise<SourceCount> | null>(null);
  const sortInFlightRef = useRef(new Set<string>());
  const previousFilterRef = useRef(filter);
  const previousBrowseScopeRef = useRef(`${accountId ?? "anon"}|${parentId ?? ""}`);

  const resetView = useCallback((): void => {
    requestRef.current = { generation: requestRef.current.generation + 1, key: "" };
    setItems([]); setNextPageToken(null); setPageIndex(0); setLastLoadedPageIndex(0); setLoaded(false); setLoading(false); setError(null); setTotalCount(null); setCount(null);
  }, []);

  const reset = useCallback((): void => {
    cacheRef.current.clear();
    preloadRef.current = null;
    completedRequestRef.current += 1;
    setCompleted({ expanded: false, initialized: false, items: [], pageIndex: 0, loading: false, error: null });
    resetView();
  }, [resetView]);

  const loadCompleted = useCallback(async (force = false): Promise<void> => {
    if (!force && completed.initialized) return;
    const generation = completedRequestRef.current + 1;
    completedRequestRef.current = generation;
    setCompleted((current) => ({ ...current, loading: true, error: null }));
    try {
      let pageToken: string | null = null;
      let completedItems: ResourceItem[] = [];
      do {
        const response = await listTaskResources(parentId, pageToken, PROVIDER_BATCH_SIZE, "completed");
        completedItems = [...new Map([...completedItems, ...response.items.filter((item) => item.metadata.task_status === "completed")].map((item) => [item.resource_id, item])).values()];
        pageToken = response.next_page_token;
      } while (pageToken !== null);
      if (completedRequestRef.current !== generation) return;
      setCompleted((current) => ({ ...current, initialized: true, items: completedItems, pageIndex: 0, loading: false, error: null }));
    } catch (cause) {
      if (completedRequestRef.current !== generation) return;
      setCompleted((current) => ({ ...current, loading: false, error: cause instanceof ApiClientError ? cause.message : "완료된 할 일을 불러오지 못했습니다." }));
    }
  }, [completed.initialized, parentId]);

  const loadPage = useCallback(async (targetPageIndex: number, { force = false }: { force?: boolean } = {}): Promise<void> => {
    const normalizedFilter = filter.trim().toLowerCase();
    const key = cacheKey(accountId, parentId, sort, normalizedFilter);
    const generation = requestRef.current.generation + 1;
    requestRef.current = { generation, key };
    const isCurrent = (): boolean => requestRef.current.generation === generation && requestRef.current.key === key;
    const cached = !force ? cacheRef.current.get(key) : undefined;
    if (!force && cached && cached.nextPageToken === null) {
      setItems(cached.items); setNextPageToken(null); setTotalCount(cached.totalCount); setPageIndex(targetPageIndex); setLastLoadedPageIndex(targetPageIndex); setLoaded(true); setLoading(false); setError(null);
      return;
    }
    const defaultKey = cacheKey(accountId, parentId, "provider", normalizedFilter);
    if (sort === "scheduled_date") {
      const defaultCached = !force ? cacheRef.current.get(defaultKey) : undefined;
      if (defaultCached?.nextPageToken === null) {
        const sorted = sortByScheduledDate(defaultCached.items);
        cacheRef.current.set(key, { items: sorted, nextPageToken: null, totalCount: sorted.length });
        setItems(sorted); setNextPageToken(null); setTotalCount(sorted.length); setPageIndex(targetPageIndex); setLastLoadedPageIndex(targetPageIndex); setLoaded(true); setLoading(false); setError(null); setCount({ value: sorted.length, exact: true });
        return;
      }
      if (sortInFlightRef.current.has(key)) return;
      sortInFlightRef.current.add(key);
      setLoading(true); setError(null);
      try {
        let nextItems = force ? [] : defaultCached?.items ?? items;
        let token = force ? null : defaultCached?.nextPageToken ?? nextPageToken;
        do {
          const response = await listTaskResources(parentId, token, PROVIDER_BATCH_SIZE);
          nextItems = [...nextItems, ...response.items];
          token = response.next_page_token;
        } while (token !== null);
        const sorted = sortByScheduledDate(nextItems);
        cacheRef.current.set(key, { items: sorted, nextPageToken: null, totalCount: sorted.length });
        if (!isCurrent()) return;
        setItems(sorted); setNextPageToken(null); setTotalCount(sorted.length); setPageIndex(targetPageIndex); setLastLoadedPageIndex(targetPageIndex); setLoaded(true); setLoading(false); setError(null); setCount({ value: sorted.length, exact: true });
      } catch (cause) {
        if (isCurrent()) { setLoading(false); setError(cause instanceof ApiClientError ? cause.message : "리소스를 불러오지 못했습니다."); }
      } finally { sortInFlightRef.current.delete(key); }
      return;
    }
    const cachedItems = !force && cached ? cached.items : items;
    const cachedToken = !force && cached ? cached.nextPageToken : nextPageToken;
    const knownLastPage = cachedToken !== null && targetPageIndex === Math.max(0, Math.ceil(cachedItems.length / UI_PAGE_SIZE) - 1);
    if (!force && cachedItems.length > targetPageIndex * UI_PAGE_SIZE && !knownLastPage) {
      setItems(cachedItems); setNextPageToken(cachedToken); setTotalCount(cached?.totalCount ?? totalCount); setPageIndex(targetPageIndex); setLastLoadedPageIndex(targetPageIndex); setLoaded(true); setLoading(false); setError(null);
      return;
    }
    if (!force && cachedItems.length > 0 && cachedToken === null) return;
    setLoading(true); setError(null);
    try {
      const response = await listTaskResources(parentId, force ? null : cachedToken, PROVIDER_BATCH_SIZE);
      const nextItems = force || cachedItems.length === 0 ? response.items : [...cachedItems, ...response.items];
      const token = response.next_page_token;
      const nextTotal = token === null ? nextItems.length : null;
      cacheRef.current.set(key, { items: nextItems, nextPageToken: token, totalCount: nextTotal });
      if (!isCurrent()) return;
      setItems(nextItems); setNextPageToken(token); setTotalCount(nextTotal); setPageIndex(targetPageIndex); setLastLoadedPageIndex(targetPageIndex); setLoaded(true); setLoading(false); setError(null); setCount({ value: nextItems.length, exact: token === null });
    } catch (cause) {
      if (isCurrent()) setError(cause instanceof ApiClientError ? cause.message : "리소스를 불러오지 못했습니다.");
      if (isCurrent()) setLoading(false);
    }
  }, [accountId, filter, items, nextPageToken, parentId, sort, totalCount]);

  const preload = useCallback(async (): Promise<SourceCount> => {
    if (preloadRef.current) return preloadRef.current;
    const key = cacheKey(accountId, null, "provider", "");
    preloadRef.current = (async (): Promise<SourceCount> => {
      const cached = cacheRef.current.get(key);
      if (cached) return { value: cached.items.length, exact: cached.nextPageToken === null };
      try {
        const response = await listTaskResources(null, null, PROVIDER_BATCH_SIZE);
        const result = { value: response.items.length, exact: response.next_page_token === null };
        cacheRef.current.set(key, { items: response.items, nextPageToken: response.next_page_token, totalCount: result.exact ? result.value : null });
        setCount(result);
        return result;
      } catch { return null; }
    })();
    return preloadRef.current;
  }, [accountId]);

  const refresh = useCallback(async (): Promise<void> => { cacheRef.current.delete(cacheKey(accountId, parentId, sort, filter)); await loadPage(0, { force: true }); void loadCompleted(true); }, [accountId, filter, loadCompleted, loadPage, parentId, sort]);
  const setSort = useCallback((nextSort: TaskSort): void => { if (sort === nextSort) return; setSortState(nextSort); resetView(); }, [resetView, sort]);
  const toggleCompleted = useCallback((): void => setCompleted((current) => ({ ...current, expanded: !current.expanded })), []);
  const showMoreCompleted = useCallback((): void => setCompleted((current) => ({ ...current, pageIndex: current.pageIndex + 1 })), []);

  useEffect(() => {
    if (!active || previousFilterRef.current === filter) return;
    previousFilterRef.current = filter;
    resetView();
  }, [active, filter, resetView]);

  useEffect(() => {
    const scope = `${accountId ?? "anon"}|${parentId ?? ""}`;
    if (previousBrowseScopeRef.current === scope) return;
    previousBrowseScopeRef.current = scope;
    resetView();
  }, [accountId, parentId, resetView]);

  return { items, nextPageToken, pageIndex, lastLoadedPageIndex, loaded, loading, error, totalCount, sort, count, completed, loadPage, preload, loadCompleted, refresh, reset, setSort, toggleCompleted, showMoreCompleted };
}

export type TasksController = ReturnType<typeof useTasks>;
