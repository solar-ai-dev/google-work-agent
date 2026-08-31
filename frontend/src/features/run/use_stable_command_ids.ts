import { useCallback, useRef } from "react";

export function useStableCommandIds() {
  const commandIdsRef = useRef(new Map<string, string>());

  const commandIdFor = useCallback((operation: string): string => {
    const existing = commandIdsRef.current.get(operation);
    if (existing) return existing;
    const created = crypto.randomUUID();
    commandIdsRef.current.set(operation, created);
    return created;
  }, []);

  const completeCommand = useCallback((operation: string): void => {
    commandIdsRef.current.delete(operation);
  }, []);

  return { commandIdFor, completeCommand };
}
