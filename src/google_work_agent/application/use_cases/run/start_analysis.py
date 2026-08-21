"""Application use case for start analysis."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads
from google_work_agent.domain.enums import ResultCode
from google_work_agent.ports.models import CommandReceiptStatus
from google_work_agent.ports.repositories import UnitOfWork

@dataclass(frozen=True, slots=True)
class StartAnalysisCommand:
    run_id: str
    expected_version: int
    command_id: str
    request_hash: str

@dataclass(frozen=True, slots=True)
class StartAnalysisResult:
    applied: bool
    result_code: str
    current_status: str
    current_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None

class StartAnalysisHandler:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: StartAnalysisCommand) -> StartAnalysisResult:
        with self._unit_of_work_factory() as unit_of_work:
            now_ms = self._now_ms()
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                if existing.request_hash != command.request_hash:
                    run = unit_of_work.runs.get_by_id(command.run_id)
                    return StartAnalysisResult(False, ResultCode.DUPLICATE_COMMAND.value, run.status.value if run else "UNKNOWN", run.version if run else 0, (), "command_id already exists with a different request_hash")
                if existing.status is CommandReceiptStatus.RECEIVED or existing.response_json is None:
                    raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
                payload = loads(existing.response_json); payload["next_allowed_commands"] = tuple(payload.get("next_allowed_commands", ())); return StartAnalysisResult(**payload)
            unit_of_work.command_receipts.add_received(command_id=command.command_id, command_type="StartAnalysis", request_hash=command.request_hash, aggregate_type="Run", aggregate_id=command.run_id, created_at_ms=now_ms)
            domain_result = unit_of_work.runs.start_analysis(command.run_id, expected_version=command.expected_version)
            result = StartAnalysisResult(domain_result.applied, domain_result.result_code.value, domain_result.current_status.value, domain_result.current_version, tuple(item.value for item in domain_result.next_allowed_commands), domain_result.conflict_detail)
            unit_of_work.command_receipts.finish_json(command_id=command.command_id, applied=result.applied, result_code=domain_result.result_code, result_version=result.current_version, response_json=dumps(asdict(result), sort_keys=True), completed_at_ms=now_ms)
            unit_of_work.commit(); return result
