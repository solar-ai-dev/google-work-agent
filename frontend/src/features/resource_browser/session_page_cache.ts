export class ResourceBrowserSessionCache<T> {
  private scopeKey: string | null = null;
  private readonly entries = new Map<string, T>();

  constructor(private readonly maxEntries = 64) {
    if (!Number.isInteger(maxEntries) || maxEntries < 1) throw new Error("maxEntries must be a positive integer");
  }

  bindScope(scopeKey: string): void {
    if (this.scopeKey === scopeKey) return;
    this.scopeKey = scopeKey;
    this.entries.clear();
  }

  get(key: string): T | undefined {
    return this.entries.get(key);
  }

  set(key: string, value: T): void {
    this.entries.delete(key);
    this.entries.set(key, value);
    while (this.entries.size > this.maxEntries) {
      const oldestKey = this.entries.keys().next().value as string | undefined;
      if (oldestKey === undefined) break;
      this.entries.delete(oldestKey);
    }
  }

  has(key: string): boolean {
    return this.entries.has(key);
  }

  delete(key: string): void {
    this.entries.delete(key);
  }

  clear(): void {
    this.entries.clear();
  }
}
