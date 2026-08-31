import { describe, expect, test } from "vitest";
import { ResourceBrowserSessionCache } from "../../../src/features/resource_browser/session_page_cache";

describe("ResourceBrowserSessionCache", () => {
  test("bounds entries and clears them when the session scope changes", () => {
    const cache = new ResourceBrowserSessionCache<number>(2);
    cache.bindScope("account-a|service-a");
    cache.set("gmail:q:1", 1);
    cache.set("gmail:q:2", 2);
    cache.set("gmail:q:3", 3);
    expect(cache.get("gmail:q:1")).toBeUndefined();
    expect(cache.get("gmail:q:3")).toBe(3);

    cache.bindScope("account-b|service-a");
    expect(cache.get("gmail:q:3")).toBeUndefined();
  });
});
