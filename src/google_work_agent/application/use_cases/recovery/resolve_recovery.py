"""Application use case for explicit Run recovery resolution."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads
from google_work_agent.domain.enums import RecoveryResolution, ResultCode, RunStatus
from google_work_agent.domain.run.transitions.resolve_recovery import transition_resolve_recovery
from google_work_agent.ports.models import CommandReceiptStatus
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

@dataclass(frozen=True, slots=True)
class ResolveRecoveryCommand:
    run_id: str
    expected_version: int
    command_id: str
    request_hash: str
    resolution: RecoveryResolution
    cancel_intent_active: bool = False
    terminal_snapshot: bool = False
    irrecoverable_confirmed: bool = False

@dataclass(frozen=True, slots=True)
class ResolveRecoveryResult:
    applied: bool
    result_code: str
    current_status: str
    current_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None

class ResolveRecoveryHandler:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ResolveRecoveryCommand) -> ResolveRecoveryResult:
        with self._unit_of_work_factory() as unit_of_work:
            now_ms = self._now_ms()
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                if existing.request_hash != command.request_hash:
                    run = unit_of_work.runs.get_by_id(command.run_id)
                    return ResolveRecoveryResult(False, ResultCode.DUPLICATE_COMMAND.value, run.status.value if run else "UNKNOWN", run.version if run else 0, (), "command_id already exists with a different request_hash")
                if existing.status is CommandReceiptStatus.RECEIVED or existing.response_json is None:
                    raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
                payload = loads(existing.response_json); payload["next_allowed_commands"] = tuple(payload.get("next_allowed_commands", ())); return ResolveRecoveryResult(**payload)
            run = unit_of_work.runs.get_by_id(command.run_id)
            if run is None: raise LookupError(f"run not found: {command.run_id}")
            target = transition_resolve_recovery(run.status, resolution=command.resolution, cancel_intent_active=command.cancel_intent_active, terminal_snapshot=command.terminal_snapshot, irrecoverable_confirmed=command.irrecoverable_confirmed)
            unit_of_work.command_receipts.add_received(command_id=command.command_id, command_type="ResolveRecovery", request_hash=command.request_hash, aggregate_type="Run", aggregate_id=command.run_id, created_at_ms=now_ms)
            d = unit_of_work.runs.resolve_recovery(command.run_id, expected_version=command.expected_version, recovery_next_status=target, finished_at_ms=now_ms if target in {RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED} else None)
            result = ResolveRecoveryResult(d.applied,d.result_code.value,d.current_status.value,d.current_version,tuple(item.value for item in d.next_allowed_commands),d.conflict_detail)
            unit_of_work.command_receipts.finish_json(command_id=command.command_id,applied=result.applied,result_code=d.result_code,result_version=result.current_version,response_json=dumps(asdict(result),sort_keys=True),completed_at_ms=now_ms);unit_of_work.commit();return result
