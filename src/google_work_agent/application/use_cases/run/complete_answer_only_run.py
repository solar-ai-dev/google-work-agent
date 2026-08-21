"""Complete an answer-only Run and persist its assistant Message atomically."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from json import dumps
from google_work_agent.domain.enums import ResultCode, RunStatus
from google_work_agent.ports.models import AnswerOnlyResponse, AuditEventRecord, CommandReceiptStatus, MessageRecord, TraceEventRecord
from google_work_agent.ports.repositories import UnitOfWork
@dataclass(frozen=True, slots=True)
class CompleteAnswerOnlyRunCommand:
    command_id:str; conversation_id:str; run_id:str; assistant_message:str; expected_version:int; request_hash:str
CompleteAnswerOnlyRunResult = AnswerOnlyResponse
class CompleteAnswerOnlyRunHandler:
    def __init__(self,*,unit_of_work_factory:Callable[[],UnitOfWork],now_ms:Callable[[],int],message_id_factory:Callable[[],str])->None:self._f=unit_of_work_factory;self._n=now_ms;self._m=message_id_factory
    def __call__(self,command:CompleteAnswerOnlyRunCommand)->CompleteAnswerOnlyRunResult:
        with self._f() as u:
            e=u.command_receipts.get_by_command_id(command.command_id)
            if e is not None:
                if e.request_hash!=command.request_hash:
                    r=u.runs.get_by_id(command.run_id)
                    if r is None: raise LookupError(f"run not found: {command.run_id}")
                    return AnswerOnlyResponse(False,ResultCode.DUPLICATE_COMMAND,r.status,r.version,(),"command_id already exists with a different request_hash")
                if e.response is not None and e.status is not CommandReceiptStatus.RECEIVED:return e.response
                r=u.runs.get_by_id(command.run_id)
                if r is None: raise LookupError(f"run not found during receipt recovery: {command.run_id}")
                if r.status is RunStatus.COMPLETED:
                    m=u.messages.find_assistant_message(run_id=command.run_id,content=command.assistant_message)
                    if m is not None:
                        response=AnswerOnlyResponse(True,ResultCode.TRANSITION_APPLIED,r.status,r.version,(),assistant_message_id=m.id);u.command_receipts.finish(command_id=command.command_id,response=response,completed_at_ms=self._n());u.commit();return response
                response=AnswerOnlyResponse(False,ResultCode.STATE_CONFLICT,r.status,r.version,(),"receipt is pending and aggregate state is not safely recoverable");u.command_receipts.finish(command_id=command.command_id,response=response,completed_at_ms=self._n());u.commit();return response
            n=self._n();u.command_receipts.add_received(command_id=command.command_id,command_type="CompleteAnswerOnlyRun",request_hash=command.request_hash,aggregate_type="Run",aggregate_id=command.run_id,created_at_ms=n)
            c=u.conversations.get_by_id(command.conversation_id)
            if c is None: raise LookupError(f"conversation not found: {command.conversation_id}")
            rr=u.runs.get_by_id(command.run_id)
            if rr is None or rr.conversation_id!=command.conversation_id: raise LookupError("run does not belong to conversation")
            d=u.runs.complete_answer_only_run(command.run_id,expected_version=command.expected_version,finished_at_ms=n)
            response=AnswerOnlyResponse(d.applied,d.result_code,d.current_status,d.current_version,d.next_allowed_commands,d.conflict_detail)
            if d.applied:
                mid=self._m();u.messages.add(MessageRecord(mid,command.conversation_id,command.run_id,"ASSISTANT",command.assistant_message,n));u.conversations.touch(command.conversation_id,updated_at_ms=n)
                response=AnswerOnlyResponse(True,d.result_code,d.current_status,d.current_version,d.next_allowed_commands,d.conflict_detail,mid)
                u.traces.add(TraceEventRecord(command.run_id,None,"COMMAND_APPLIED",d.current_status.value,None,dumps({"command_id":command.command_id,"command_type":"CompleteAnswerOnlyRun","message_id":mid},sort_keys=True),n));u.audits.add(AuditEventRecord(c.account_id,command.run_id,None,"AGENT","complete_answer_only_run",None,"RUN_COMPLETED",d.result_code.value,dumps({"command_id":command.command_id,"message_id":mid,"mode":"ANSWER_ONLY"},sort_keys=True),n))
            u.command_receipts.finish(command_id=command.command_id,response=response,completed_at_ms=n);u.commit();return response
