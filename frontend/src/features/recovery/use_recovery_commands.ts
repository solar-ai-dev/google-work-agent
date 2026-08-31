import { useCallback } from "react";
import type { RunSnapshot } from "../../api/contract";
import { resolveRecovery } from "./api/resolve_recovery";

type Options = { runSnapshot: RunSnapshot | null; busyCommand: string | null; setBusyCommand: (value: string | null) => void; commandIdFor: (operation: string) => string; completeCommand: (operation: string) => void; refreshRun: (runId: string) => Promise<boolean> };

export function useRecoveryCommands({ runSnapshot, busyCommand, setBusyCommand, commandIdFor, completeCommand, refreshRun }: Options) {
  const handleResolveRecovery = useCallback(async (resolutionKind: NonNullable<RunSnapshot["recovery"]>["allowed_resolution_kinds"][number]): Promise<void> => {
    if (!runSnapshot?.recovery || busyCommand || !runSnapshot.recovery.allowed_resolution_kinds.includes(resolutionKind)) return;
    const operation = `recovery-${resolutionKind}`;
    setBusyCommand(operation);
    try {
      await resolveRecovery({ run_id: runSnapshot.run.run_id, command_id: commandIdFor(operation), expected_version: runSnapshot.run.version, target: runSnapshot.recovery.target, resolution_kind: resolutionKind });
      completeCommand(operation);
      await refreshRun(runSnapshot.run.run_id);
    } catch (error) { await refreshRun(runSnapshot.run.run_id); throw error; }
    finally { setBusyCommand(null); }
  }, [busyCommand, commandIdFor, completeCommand, refreshRun, runSnapshot, setBusyCommand]);

  return { handleResolveRecovery };
}
