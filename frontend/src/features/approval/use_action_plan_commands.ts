import { useCallback } from "react";
import { stageAttachment } from "../../api";
import { ApiClientError } from "../../api/client";
import type { RunAction, RunSnapshot } from "../../api/contract";
import { approveAction, modifyAction, prepareRetry, rejectAction } from "./api/action_commands";

type Options = { runSnapshot: RunSnapshot | null; currentAccountId: string | null; busyCommand: string | null; setBusyCommand: (value: string | null) => void; commandIdFor: (operation: string) => string; completeCommand: (operation: string) => void; selectRun: (runId: string) => Promise<void>; refreshRun: (runId: string) => Promise<boolean>; onStatusLine: (message: string) => void };

export function useActionPlanCommands({ runSnapshot, currentAccountId, busyCommand, setBusyCommand, commandIdFor, completeCommand, selectRun, refreshRun, onStatusLine }: Options) {
  const handleApprove = useCallback(async (action: RunAction, acknowledgements: ReadonlySet<string> = new Set()): Promise<void> => {
    if (!runSnapshot || !currentAccountId || busyCommand) return;
    const operation = `approve-${action.action_id}`;
    setBusyCommand(operation);
    try {
      await approveAction({ action_id: action.action_id, command_id: commandIdFor(operation), expected_version: action.version, duplicate_acknowledged: acknowledgements.has("TASK_DUPLICATE"), calendar_conflict_acknowledged: acknowledgements.has("CALENDAR_CONFLICT") });
      completeCommand(operation);
      await selectRun(runSnapshot.run.run_id);
    } catch (error) { await refreshRun(runSnapshot.run.run_id); throw error; }
    finally { setBusyCommand(null); }
  }, [busyCommand, commandIdFor, completeCommand, currentAccountId, refreshRun, runSnapshot, selectRun, setBusyCommand]);

  const handleSimpleAction = useCallback(async (kind: "modify" | "reject" | "retry", action: RunAction, argumentsPatch: Record<string, unknown> = {}): Promise<void> => {
    if (!runSnapshot || busyCommand) return;
    const operation = `${kind}-${action.action_id}`;
    setBusyCommand(operation);
    try {
      const commandId = commandIdFor(operation);
      if (kind === "modify") await modifyAction({ action_id: action.action_id, command_id: commandId, expected_version: action.version, arguments_patch: argumentsPatch });
      else if (kind === "reject") await rejectAction({ action_id: action.action_id, command_id: commandId, expected_version: action.version });
      else await prepareRetry({ action_id: action.action_id, command_id: commandId, expected_version: action.version });
      completeCommand(operation);
      await selectRun(runSnapshot.run.run_id);
    } catch (error) { await refreshRun(runSnapshot.run.run_id); throw error; }
    finally { setBusyCommand(null); }
  }, [busyCommand, commandIdFor, completeCommand, refreshRun, runSnapshot, selectRun, setBusyCommand]);

  const handleAttachFiles = useCallback(async (action: RunAction, files: FileList): Promise<void> => {
    if (!runSnapshot || busyCommand || files.length === 0) return;
    const operation = `attachment-modify-${action.action_id}`;
    setBusyCommand(`modify-${action.action_id}`);
    try {
      const descriptors = [];
      for (const file of Array.from(files).slice(0, 10)) {
        const staged = await stageAttachment(file);
        descriptors.push({ staged_attachment_id: staged.staged_attachment_id, filename: staged.filename, mime_type: staged.mime_type, size_bytes: staged.size_bytes, sha256: staged.sha256 });
      }
      await modifyAction({ action_id: action.action_id, command_id: commandIdFor(operation), expected_version: action.version, arguments_patch: { attachments: descriptors } });
      completeCommand(operation);
      await selectRun(runSnapshot.run.run_id);
    } catch (error) { onStatusLine(error instanceof ApiClientError ? error.message : "첨부 파일을 추가하지 못했습니다."); }
    finally { setBusyCommand(null); }
  }, [busyCommand, commandIdFor, completeCommand, onStatusLine, runSnapshot, selectRun, setBusyCommand]);

  return { handleApprove, handleSimpleAction, handleAttachFiles };
}
