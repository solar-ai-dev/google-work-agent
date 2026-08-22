"""Regression tests for canonical persisted Run resume authority."""
from __future__ import annotations

from dataclasses import dataclass
from json import dumps
from types import SimpleNamespace

from google_work_agent.application.run_contracts import ResumeRunCommand
from google_work_agent.application.use_cases.run.resume_run import ResumeRunHandler
from google_work_agent.domain import CommandResult, ResultCode, RunStatus
from google_work_agent.ports import CommandReceiptRecord, CommandReceiptStatus, RunRecord


class _Sink:
    def __init__(self) -> None: self.items=[]
    def add(self, item) -> None: self.items.append(item)


class _Receipts:
    def __init__(self) -> None: self.items={}
    def get_by_command_id(self, command_id): return self.items.get(command_id)
    def add_received(self, *, command_id, command_type, request_hash, aggregate_type, aggregate_id, created_at_ms):
        self.items[command_id]=CommandReceiptRecord(command_id,command_type,request_hash,aggregate_type,aggregate_id,CommandReceiptStatus.RECEIVED,None,None,None,None,created_at_ms,None)
    def finish_json(self, *, command_id, applied, result_code, result_version, response_json, completed_at_ms):
        old=self.items[command_id]
        self.items[command_id]=CommandReceiptRecord(old.command_id,old.command_type,old.request_hash,old.aggregate_type,old.aggregate_id,CommandReceiptStatus.APPLIED if applied else CommandReceiptStatus.REJECTED,result_code,result_version,None,response_json,old.created_at_ms,completed_at_ms)


class _Runs:
    def __init__(self, status: RunStatus, version: int=4) -> None:
        self.record=RunRecord("run-1","conv-1",status,version,1,None);self.calls=[]
    def get_by_id(self, run_id): return self.record if run_id==self.record.id else None
    def _move(self, name, target):
        self.calls.append(name);self.record=RunRecord(self.record.id,self.record.conversation_id,target,self.record.version+1,self.record.started_at_ms,None)
        return CommandResult(True,ResultCode.TRANSITION_APPLIED,target,self.record.version,(),None)
    def resume_confirmation(self, run_id, *, expected_version, resume_status, finished_at_ms=None): return self._move("resume_confirmation",resume_status)
    def resume_after_reauth(self, run_id, *, expected_version, resume_status, finished_at_ms=None): return self._move("resume_after_reauth",resume_status)
    def resolve_recovery(self, run_id, *, expected_version, recovery_next_status, finished_at_ms=None): return self._move("resolve_recovery",recovery_next_status)


class _Uow:
    def __init__(self, status):
        self.runs=_Runs(status);self.command_receipts=_Receipts();self.traces=_Sink();self.audits=_Sink();self.plans=SimpleNamespace(list_by_run=lambda run_id: []);self.actions=SimpleNamespace(list_by_plan=lambda plan_id: []);self.commits=0
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def commit(self): self.commits+=1
    def rollback(self): pass


@dataclass
class _Harness:
    uow:_Uow
    authority:dict[str,object]|None
    enqueues:list[dict[str,object]]
    def handler(self):
        return ResumeRunHandler(unit_of_work_factory=lambda:self.uow,now_ms=lambda:100,enqueue_resume=lambda **kwargs:self.enqueues.append(kwargs),resolve_resume_authority=lambda **kwargs:self.authority)


def _command(kind:str, *, command_id:str="cmd-1", request_hash:str="hash-1", version:int=4):
    return ResumeRunCommand(command_id,request_hash,"run-1",version,kind,"v1")


def test_confirmation_resume_applies_domain_transition_before_enqueue() -> None:
    h=_Harness(_Uow(RunStatus.WAITING_CONFIRMATION),{"resume_status":"PLANNING","interrupt_id":"int-1"},[])
    result=h.handler()(_command("CONFIRMATION"),request_id="req",resume_payload={"interrupt_id":"int-1"})
    assert result.applied and result.run_status=="PLANNING" and result.run_version==5
    assert h.uow.runs.calls==["resume_confirmation"]
    assert h.uow.commits==1 and len(h.uow.traces.items)==1 and len(h.uow.audits.items)==1
    assert len(h.enqueues)==1


def test_reauth_resume_applies_safe_checkpoint_transition() -> None:
    h=_Harness(_Uow(RunStatus.REAUTH_REQUIRED),{"resume_status":"WAITING_APPROVAL"},[])
    result=h.handler()(_command("REAUTH_COMPLETED"),request_id="req")
    assert result.applied and result.run_status=="WAITING_APPROVAL" and result.run_version==5
    assert h.uow.runs.calls==["resume_after_reauth"] and len(h.enqueues)==1


def test_recovery_recheck_moves_to_verifying_without_new_attempt_or_approval() -> None:
    h=_Harness(_Uow(RunStatus.RECOVERY_REQUIRED),None,[])
    result=h.handler()(_command("RECOVERY_RECHECK"),request_id="req")
    assert result.applied and result.run_status=="VERIFYING"
    assert h.uow.runs.calls==["resolve_recovery"] and len(h.enqueues)==1
    assert not hasattr(h.uow,"execution_attempts") and not hasattr(h.uow,"approvals")


def test_ordinary_safe_resume_does_not_invent_domain_transition() -> None:
    h=_Harness(_Uow(RunStatus.BLOCKED),None,[])
    result=h.handler()(_command("SAFE_CHECKPOINT_RESUME"),request_id="req")
    assert result.applied and result.run_status=="BLOCKED" and result.run_version==4
    assert h.uow.runs.calls==[] and len(h.enqueues)==1


def test_invalid_status_or_confirmation_authority_does_not_transition_or_enqueue() -> None:
    h=_Harness(_Uow(RunStatus.ANALYZING),{"resume_status":"PLANNING","interrupt_id":"int-1"},[])
    result=h.handler()(_command("CONFIRMATION"),request_id="req",resume_payload={"interrupt_id":"int-1"})
    assert not result.applied and result.result_code==ResultCode.STATE_CONFLICT.value
    assert h.uow.runs.calls==[] and h.enqueues==[]


def test_same_hash_replay_returns_prior_result_without_second_mutation_or_enqueue() -> None:
    h=_Harness(_Uow(RunStatus.REAUTH_REQUIRED),{"resume_status":"WAITING_APPROVAL"},[]);handler=h.handler();command=_command("REAUTH_COMPLETED")
    first=handler(command,request_id="req")
    second=handler(command,request_id="req")
    assert first.applied and second.applied and second.request_replayed
    assert h.uow.runs.calls==["resume_after_reauth"] and len(h.enqueues)==1


def test_hash_mismatch_is_conflict_with_zero_second_mutation_and_enqueue() -> None:
    h=_Harness(_Uow(RunStatus.REAUTH_REQUIRED),{"resume_status":"WAITING_APPROVAL"},[]);handler=h.handler()
    first=handler(_command("REAUTH_COMPLETED"),request_id="req")
    second=handler(_command("REAUTH_COMPLETED",request_hash="different"),request_id="req")
    assert first.applied and not second.applied and second.result_code==ResultCode.DUPLICATE_COMMAND.value
    assert h.uow.runs.calls==["resume_after_reauth"] and len(h.enqueues)==1
