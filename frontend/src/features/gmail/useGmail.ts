import { useCallback, useEffect, useRef, useState } from "react";
import { getResourceCount, listGmailResources } from "../../api";
import { ApiClientError } from "../../api/client";
import type { ResourceItem, ResourceListResponse } from "../../api/contract";

type GmailPageCacheEntry = {
  pageToken: string | null;
  nextPageToken: string | null;
  items: ResourceItem[] | null;
};

type GmailProviderPage = {
  response: ResourceListResponse;
  includesMetadata: boolean;
};

type GmailCacheEntry = {
  pages: Record<number, GmailPageCacheEntry>;
  totalCount: number | null;
};

type GmailState = {
  searchInput: string;
  query: string;
  pages: Record<number, GmailPageCacheEntry>;
  nextPageToken: string | null;
  pageIndex: number;
  lastLoadedPageIndex: number;
  loaded: boolean;
  loading: boolean;
  error: string | null;
  totalCount: number | null;
  countLoading: boolean;
  count: { value: number; exact: boolean } | null;
};

const GMAIL_BROWSE_SIZE = 20;

function cacheKey(accountId: string | null | undefined, query: string): string {
  return `${accountId ?? "anon"}|gmail|${query.trim().toLowerCase()}`;
}

function metadataItems(pages: Record<number, GmailPageCacheEntry>): ResourceItem[] {
  return Object.values(pages).flatMap((page) => page.items ?? []);
}

export function useGmail({ accountId, active }: { accountId: string | null | undefined; active: boolean }) {
  const [state, setState] = useState<GmailState>({
    searchInput: "",
    query: "",
    pages: {},
    nextPageToken: null,
    pageIndex: 0,
    lastLoadedPageIndex: 0,
    loaded: false,
    loading: false,
    error: null,
    totalCount: null,
    countLoading: false,
    count: null,
  });
  const cacheRef = useRef(new Map<string, GmailCacheEntry>());
  const countCacheRef = useRef(new Map<string, number | null>());
  const inFlightRef = useRef(new Map<string, { includesMetadata: boolean; promise: Promise<GmailProviderPage> }>());
  const requestRef = useRef({ generation: 0, cacheKey: "", pageIndex: 0 });

  const requestPage = useCallback(async (
    currentCacheKey: string,
    query: string,
    pageToken: string | null,
    includeThreadMetadata: boolean,
  ): Promise<GmailProviderPage> => {
    const inFlightKey = `${currentCacheKey}|${pageToken ?? "first"}`;
    const inFlight = inFlightRef.current.get(inFlightKey);
    if (inFlight) {
      const result = await inFlight.promise;
      if (!includeThreadMetadata || result.includesMetadata) return result;
      return requestPage(currentCacheKey, query, pageToken, true);
    }
    const promise = listGmailResources(query, pageToken, GMAIL_BROWSE_SIZE, includeThreadMetadata)
      .then((response) => ({ response, includesMetadata: includeThreadMetadata }));
    inFlightRef.current.set(inFlightKey, { includesMetadata: includeThreadMetadata, promise });
    try {
      return await promise;
    } finally {
      if (inFlightRef.current.get(inFlightKey)?.promise === promise) inFlightRef.current.delete(inFlightKey);
    }
  }, []);

  const reset = useCallback((): void => {
    requestRef.current = { generation: requestRef.current.generation + 1, cacheKey: "", pageIndex: 0 };
    cacheRef.current.clear();
    countCacheRef.current.clear();
    setState((current) => ({ ...current, pages: {}, nextPageToken: null, pageIndex: 0, lastLoadedPageIndex: 0, loaded: false, loading: false, error: null, totalCount: null, countLoading: false, count: null }));
  }, []);

  const loadCount = useCallback(async ({ force = false, publish = true }: { force?: boolean; publish?: boolean } = {}): Promise<{ value: number; exact: boolean } | null> => {
    const currentCacheKey = cacheKey(accountId, state.query);
    if (!force && countCacheRef.current.has(currentCacheKey)) {
      const cached = countCacheRef.current.get(currentCacheKey) ?? null;
      const count = cached === null ? null : { value: cached, exact: true };
      if (publish) setState((current) => current.totalCount === cached && !current.countLoading && current.count?.value === count?.value
        ? current
        : { ...current, totalCount: cached, countLoading: false, count });
      return count;
    }
    if (publish) setState((current) => ({ ...current, totalCount: null, countLoading: true }));
    try {
      const response = await getResourceCount("gmail", { query: state.query, taskListId: null, calendarId: null, timeMin: null, timeMax: null });
      const count = { value: response.total_count, exact: true };
      countCacheRef.current.set(currentCacheKey, response.total_count);
      if (publish) setState((current) => ({ ...current, totalCount: response.total_count, countLoading: false, count }));
      return count;
    } catch {
      countCacheRef.current.set(currentCacheKey, null);
      if (publish) setState((current) => ({ ...current, totalCount: null, countLoading: false, count: null }));
      return null;
    }
  }, [accountId, state.query]);

  const loadPage = useCallback(async (pageIndex: number, { force = false }: { force?: boolean } = {}): Promise<void> => {
    const currentCacheKey = cacheKey(accountId, state.query);
    const generation = requestRef.current.generation + 1;
    requestRef.current = { generation, cacheKey: currentCacheKey, pageIndex };
    const isCurrent = (): boolean => requestRef.current.generation === generation && requestRef.current.cacheKey === currentCacheKey && requestRef.current.pageIndex === pageIndex;
    const cached = !force ? cacheRef.current.get(currentCacheKey) : undefined;
    const cachedPages = !force && cached ? cached.pages : state.pages;
    const prefetchNextPage = (pages: Record<number, GmailPageCacheEntry>, loadedPageIndex: number): void => {
      const nextPageIndex = loadedPageIndex + 1;
      const loadedPage = pages[loadedPageIndex];
      if (loadedPage?.nextPageToken === null || pages[nextPageIndex]?.items) return;
      void requestPage(currentCacheKey, state.query, loadedPage.nextPageToken, true).then(({ response }) => {
        const currentPages = { ...(cacheRef.current.get(currentCacheKey)?.pages ?? pages) };
        if (currentPages[nextPageIndex]?.items) return;
        currentPages[nextPageIndex] = { pageToken: loadedPage.nextPageToken, nextPageToken: response.next_page_token, items: response.items };
        cacheRef.current.set(currentCacheKey, { pages: currentPages, totalCount: null });
      }).catch(() => undefined);
    };
    const cachedPage = !force ? cachedPages[pageIndex] : undefined;
    if (cachedPage?.items) {
      setState((current) => ({ ...current, pages: cachedPages, nextPageToken: cachedPage.nextPageToken, pageIndex, lastLoadedPageIndex: pageIndex, loaded: true, loading: false, error: null }));
      prefetchNextPage(cachedPages, pageIndex);
      return;
    }
    setState((current) => ({ ...current, pageIndex, loading: true, error: null }));
    try {
      const nextPages = force ? {} : { ...cachedPages };
      for (let currentPageIndex = 0; currentPageIndex <= pageIndex; currentPageIndex += 1) {
        const known = nextPages[currentPageIndex];
        if (known) {
          if (currentPageIndex === pageIndex && known.items === null) {
            const { response } = await requestPage(currentCacheKey, state.query, known.pageToken, true);
            nextPages[currentPageIndex] = { ...known, items: response.items, nextPageToken: response.next_page_token };
          }
          continue;
        }
        const pageToken = currentPageIndex === 0 ? null : nextPages[currentPageIndex - 1]?.nextPageToken;
        if (currentPageIndex > 0 && pageToken === null) break;
        if (pageToken !== null && Object.values(nextPages).some((page) => page.pageToken === pageToken)) throw new Error("Gmail page token repeated during pagination traversal.");
        const includeThreadMetadata = currentPageIndex === pageIndex;
        const { response, includesMetadata } = await requestPage(currentCacheKey, state.query, pageToken, includeThreadMetadata);
        nextPages[currentPageIndex] = { pageToken, nextPageToken: response.next_page_token, items: includesMetadata ? response.items : null };
      }
      const targetPage = nextPages[pageIndex];
      if (!targetPage?.items) {
        if (isCurrent()) setState((current) => ({ ...current, loading: false, error: null }));
        return;
      }
      cacheRef.current.set(currentCacheKey, { pages: nextPages, totalCount: null });
      if (!isCurrent()) return;
      setState((current) => ({ ...current, pages: nextPages, nextPageToken: targetPage.nextPageToken, pageIndex, lastLoadedPageIndex: pageIndex, loaded: true, loading: false, error: null }));
      prefetchNextPage(nextPages, pageIndex);
    } catch (error) {
      if (!isCurrent()) return;
      setState((current) => ({ ...current, pageIndex: current.lastLoadedPageIndex, loading: false, error: error instanceof ApiClientError ? error.message : "리소스를 불러오지 못했습니다." }));
    }
  }, [accountId, requestPage, state.pages, state.query]);

  useEffect(() => {
    if (!active || state.searchInput === state.query) return;
    const timer = window.setTimeout(() => {
      requestRef.current = { generation: requestRef.current.generation + 1, cacheKey: "", pageIndex: 0 };
      setState((current) => ({ ...current, query: current.searchInput, pages: {}, nextPageToken: null, pageIndex: 0, lastLoadedPageIndex: 0, loaded: false, loading: false, error: null, totalCount: null, countLoading: false, count: null }));
    }, 300);
    return () => window.clearTimeout(timer);
  }, [active, state.query, state.searchInput]);

  const refresh = useCallback(async (): Promise<void> => {
    const currentCacheKey = cacheKey(accountId, state.query);
    cacheRef.current.delete(currentCacheKey);
    countCacheRef.current.delete(currentCacheKey);
    await loadPage(0, { force: true });
    void loadCount({ force: true });
  }, [accountId, loadCount, loadPage, state.query]);

  return { ...state, items: metadataItems(state.pages), setSearchInput: (searchInput: string) => setState((current) => ({ ...current, searchInput })), loadPage, loadCount, refresh, reset };
}

export type GmailController = ReturnType<typeof useGmail>;
