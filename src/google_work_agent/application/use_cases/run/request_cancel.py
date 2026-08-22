"""Application use case for durable Run cancellation."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import asdict,dataclass
from json import dumps,loads
from google_work_agent.application.write_persistence import audit_event,cancel_pending_actions
from google_work_agent.domain import ActionStatus,ResultCode
from google_work_agent.ports import CommandReceiptStatus,TraceEventRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

@dataclass(frozen=True,slots=True)
class RequestCancelCommand:
 run_id:str;expected_version:int;command_id:str;request_hash:str
@dataclass(frozen=True,slots=True)
class RequestCancelResult:
 applied:bool;result_code:str;current_status:str;current_version:int;next_allowed_commands:tuple[str,...];conflict_detail:str|None=None;result_kind:str|None=None

class RequestCancelHandler:
 """Own durable cancel truth, pending terminalization, and workflow handoff."""
 def __init__(self,*,unit_of_work_factory:Callable[[],UnitOfWork],now_ms:Callable[[],int],request_cancel_workflow:Callable[...,None]|None=None)->None:self._f=unit_of_work_factory;self._n=now_ms;self._request_cancel_workflow=request_cancel_workflow
 @classmethod
 def from_legacy_service_supplier(cls,supplier:Callable[[],object],coordinator:object)->"RequestCancelHandler":
  service=supplier();return cls(unit_of_work_factory=service._unit_of_work_factory,now_ms=service._now_ms,request_cancel_workflow=coordinator.request_cancel)
 def __call__(self,command:RequestCancelCommand,*,request_id:str|None=None)->RequestCancelResult:
  result=self._persist(command)
  if result.applied and result.current_status=="CANCEL_REQUESTED" and self._request_cancel_workflow is not None and request_id is not None:self._request_cancel_workflow(run_id=command.run_id,request_id=request_id,reason_code="user_requested")
  return result
 def _persist(self,command:RequestCancelCommand)->RequestCancelResult:
  with self._f() as u:
   n=self._n();existing=u.command_receipts.get_by_command_id(command.command_id)
   if existing is not None:
    if existing.request_hash!=command.request_hash:
     run=u.runs.get_by_id(command.run_id);return RequestCancelResult(False,ResultCode.DUPLICATE_COMMAND.value,run.status.value if run else "UNKNOWN",run.version if run else 0,(),"command_id already exists with a different request_hash")
    if existing.status is CommandReceiptStatus.RECEIVED or existing.response_json is None:raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
    payload=loads(existing.response_json);payload["next_allowed_commands"]=tuple(payload.get("next_allowed_commands",()));return RequestCancelResult(**payload)
   run=u.runs.get_by_id(command.run_id)
   if run is None:raise LookupError(f"run not found: {command.run_id}")
   plans=u.plans.list_by_run(run.id);plan=max(plans,key=lambda item:(item.revision_no,item.created_at_ms),default=None);actions=() if plan is None else u.actions.list_by_plan(plan.id)
   u.command_receipts.add_received(command_id=command.command_id,command_type="RequestRunCancellation",request_hash=command.request_hash,aggregate_type="Run",aggregate_id=command.run_id,created_at_ms=n)
   decision=u.runs.request_cancel(command.run_id,expected_version=command.expected_version)
   if not decision.applied:
    result=RequestCancelResult(False,decision.result_code.value,decision.current_status.value,decision.current_version,tuple(item.value for item in decision.next_allowed_commands),decision.conflict_detail)
   else:
    started=any(a.status in {ActionStatus.EXECUTING.value,ActionStatus.UNKNOWN_RESULT.value,ActionStatus.EXECUTED.value,ActionStatus.VERIFIED.value} for a in actions)
    if started:result=RequestCancelResult(True,ResultCode.TRANSITION_APPLIED.value,decision.current_status.value,decision.current_version,tuple(item.value for item in decision.next_allowed_commands),result_kind="CANCEL_REQUESTED")
    else:
     if plan is not None:cancel_pending_actions(unit_of_work=u,run_id=run.id,plan_id=plan.id,updated_at_ms=n);u.plans.cancel(plan.id)
     final=u.runs.finalize_cancel(run.id,expected_version=decision.current_version,finished_at_ms=n);result=RequestCancelResult(True,ResultCode.TRANSITION_APPLIED.value,final.current_status.value,final.current_version,tuple(item.value for item in final.next_allowed_commands),result_kind="CANCELLED")
   if result.applied:
    u.traces.add(TraceEventRecord(run_id=run.id,action_id=None,event_type="RUN_CANCELLATION_REQUESTED",status=result.current_status,duration_ms=None,payload_json=dumps({"plan_id":None if plan is None else plan.id},sort_keys=True),created_at_ms=n));u.audits.add(audit_event(run_id=run.id,action_id=None,event_type="RUN_CANCELLATION_REQUESTED",outcome=result.result_code,metadata={"plan_id":None if plan is None else plan.id},created_at_ms=n))
   u.command_receipts.finish_json(command_id=command.command_id,applied=result.applied,result_code=ResultCode(result.result_code),result_version=result.current_version,response_json=dumps(asdict(result),sort_keys=True),completed_at_ms=n);u.commit();return result
