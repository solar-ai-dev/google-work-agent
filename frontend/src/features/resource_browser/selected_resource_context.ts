import type { ResourceItem } from "../../api/contract";

export type SelectedResourceContext = {
  items: ResourceItem[];
  resourceIds: string[];
  selectionHandles: string[];
  labels: string[];
};

export function buildSelectedResourceContext(
  items: ResourceItem[],
  labelFor: (item: ResourceItem) => string = (item) => item.title,
): SelectedResourceContext {
  const selected: ResourceItem[] = [];
  const seenHandles = new Set<string>();
  for (const item of items) {
    const handle = item.selection_handle.trim();
    if (!handle || seenHandles.has(handle) || selected.length >= 20) continue;
    seenHandles.add(handle);
    selected.push({ ...item, selection_handle: handle });
  }
  return {
    items: selected,
    resourceIds: selected.map((item) => item.resource_id),
    selectionHandles: selected.map((item) => item.selection_handle),
    labels: selected.map(labelFor).filter((label) => label.trim().length > 0),
  };
}
