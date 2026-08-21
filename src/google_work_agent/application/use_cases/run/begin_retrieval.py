"""Application use case for begin retrieval."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads
from google_work_agent.domain.enums import ResultCode
from google_work_agent.ports.models import CommandReceiptStatus
from google_work_agent.ports.repositories import UnitOfWork

@dataclass(frozen=True, slots=True)
class BeginRetrievalCommand:
    run_id: str
    expected_version: int
    command_id: str
    request_hash: str

@dataclass(frozen=True, slots=True)
class BeginRetrievalResult:
    applied: bool
    result_code: str
    current_status: str
    current_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None

class BeginRetrievalHandler:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]) -> None:
        self._unit_of_work_factory = unit_of_work_factory; self._now_ms = now_ms
    def __call__(self, command: BeginRetrievalCommand) -> BeginRetrievalResult:
        with self._unit_of_work_factory() as u:
            now=self._now_ms(); e=u.command_receipts.get_by_command_id(command.command_id)
            if e is not None:
                if e.request_hash != command.request_hash:
                    r=u.runs.get_by_id(command.run_id); return BeginRetrievalResult(False, ResultCode.DUPLICATE_COMMAND.value, r.status.value if r else "UNKNOWN", r.version if r else 0, (), "command_id already exists with a different request_hash")
                if e.status is CommandReceiptStatus.RECEIVED or e.response_json is None: raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
                p=loads(e.response_json); p["next_allowed_commands"]=tuple(p.get("next_allowed_commands",())); return BeginRetrievalResult(**p)
            u.command_receipts.add_received(command_id=command.command_id,command_type="BeginRetrieval",request_hash=command.request_hash,aggregate_type="Run",aggregate_id=command.run_id,created_at_ms=now)
            d=u.runs.begin_retrieval(command.run_id,expected_version=command.expected_version)
            r=BeginRetrievalResult(d.applied,d.result_code.value,d.current_status.value,d.current_version,tuple(x.value for x in d.next_allowed_commands),d.conflict_detail)
            u.command_receipts.finish_json(command_id=command.command_id,applied=r.applied,result_code=d.result_code,result_version=r.current_version,response_json=dumps(asdict(r),sort_keys=True),completed_at_ms=now); u.commit(); return r
