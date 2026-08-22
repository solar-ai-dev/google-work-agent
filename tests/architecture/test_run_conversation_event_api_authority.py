"""Architecture gates for B-API-2 canonical API ownership."""
from __future__ import annotations
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTES = (
    ROOT / "src/google_work_agent/api/routes/runs.py",
    ROOT / "src/google_work_agent/api/routes/conversations.py",
    ROOT / "src/google_work_agent/api/routes/events.py",
)
USE_CASE_ROOT = ROOT / "src/google_work_agent/application/use_cases"
LANGGRAPH_RESUME = ROOT / "src/google_work_agent/adapters/langgraph/resume_authority.py"
OWNERS = ("run", "conversation", "message", "recovery")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8")); result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module: result.add(node.module)
    return result


def _function(path: Path, name: str) -> ast.FunctionDef:
    tree=ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name==name: return node
    raise AssertionError(f"{path}: endpoint {name} missing")


def _method(path: Path, class_name: str, method_name: str) -> ast.FunctionDef:
    tree=ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node,ast.ClassDef) or node.name!=class_name: continue
        for item in node.body:
            if isinstance(item,ast.FunctionDef) and item.name==method_name: return item
    raise AssertionError(f"{path}: {class_name}.{method_name} missing")


def _constructs_handler(call: ast.Call, handler: str) -> bool:
    text=ast.unparse(call.func)
    return text==handler or text.startswith(handler+".")


def _invokes_handler(path: Path, endpoint: str, handler: str) -> bool:
    function=_function(path,endpoint);bound=set()
    for node in ast.walk(function):
        if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call) and _constructs_handler(node.value,handler):
            bound.update(target.id for target in node.targets if isinstance(target,ast.Name))
    for node in ast.walk(function):
        if not isinstance(node,ast.Call): continue
        if isinstance(node.func,ast.Name) and node.func.id in bound: return True
        if isinstance(node.func,ast.Call) and _constructs_handler(node.func,handler): return True
        if isinstance(node.func,ast.Attribute) and node.func.attr in {"handle","__call__"}:
            if isinstance(node.func.value,ast.Name) and node.func.value.id in bound: return True
            if isinstance(node.func.value,ast.Call) and _constructs_handler(node.func.value,handler): return True
    return False


def test_route_endpoints_invoke_their_exact_canonical_handlers() -> None:
    cases={
        ROOT/"src/google_work_agent/api/routes/runs.py":{
            "start_run":"StartRunHandler","get_run_snapshot":"GetRunSnapshotHandler","get_run_context":"GetExecutionContextHandler","cancel_run":"RequestCancelHandler","resume_run":"ResumeRunHandler","confirm_run":"ResumeRunHandler","resolve_recovery":"ResolveMismatchRecoveryHandler"},
        ROOT/"src/google_work_agent/api/routes/conversations.py":{
            "create_conversation":"CreateConversationHandler","list_conversations":"ListConversationsHandler","get_conversation":"GetConversationHandler","get_conversation_history":"GetConversationHistoryHandler","get_latest_conversation_run":"GetLatestRunHandler"},
        ROOT/"src/google_work_agent/api/routes/events.py":{"stream_events":"GetEventReplayHandler"},
    }
    for path,endpoints in cases.items():
        for endpoint,handler in endpoints.items():
            assert _invokes_handler(path,endpoint,handler),f"{path}:{endpoint} does not invoke {handler}"


def test_owned_routes_do_not_call_broad_legacy_semantic_services() -> None:
    forbidden=(".query_service().",".start_run_service()(",".cancel_run_service()(",".resume_run_service()(",".resolve_recovery_service()(",".create_conversation_service()(","application.queries import","application.start_run import","application.write_actions import")
    for path in ROUTES:
        source=path.read_text(encoding="utf-8")
        for token in forbidden: assert token not in source,f"{path}: forbidden route authority {token}"


def test_owned_routes_do_not_traverse_repositories_or_mutate_domain_directly() -> None:
    forbidden=("with dependencies.",".runs.",".plans.",".actions.",".approvals.",".command_receipts.",".commit(","sqlite3","adapters.persistence")
    for path in ROUTES:
        source=path.read_text(encoding="utf-8")
        for token in forbidden: assert token not in source,f"{path}: route owns persistence/domain {token}"


def test_canonical_handlers_do_not_reverse_depend_on_api_or_provider_concretes() -> None:
    forbidden_prefixes=("fastapi","google_work_agent.api","google_work_agent.adapters.persistence.sqlite","google_work_agent.adapters.connectors.google","googleapiclient","google.oauth2")
    for owner in OWNERS:
        for path in (USE_CASE_ROOT/owner).glob("*.py"):
            for imported in _imports(path): assert not imported.startswith(forbidden_prefixes),f"{path}: reverse/concrete dependency {imported}"


def test_canonical_handlers_do_not_delegate_to_broad_legacy_authorities() -> None:
    forbidden={"google_work_agent.application.queries","google_work_agent.application.start_run","google_work_agent.application.conversation_lifecycle","google_work_agent.application.run_lifecycle","google_work_agent.application.write_actions","google_work_agent.application.write_cancellation","google_work_agent.application.write_recovery"}
    for owner in OWNERS:
        for path in (USE_CASE_ROOT/owner).glob("*.py"): assert not (_imports(path)&forbidden),f"{path}: canonical handler delegates to legacy authority"


def test_resume_handler_owns_all_substantive_resume_transitions_and_commit() -> None:
    path=USE_CASE_ROOT/"run/resume_run.py";tree=ast.parse(path.read_text(encoding="utf-8"));calls={ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node,ast.Call)}
    assert any(name.endswith("runs.resume_confirmation") for name in calls)
    assert any(name.endswith("runs.resume_after_reauth") for name in calls)
    assert any(name.endswith("runs.require_recovery") for name in calls)
    assert any(name.endswith("runs.resolve_recovery") for name in calls)
    assert any(name.endswith("commit") for name in calls)
    assert not any("workflow_runtime.resume" in name for name in calls)
    assert not any(name.startswith("google_work_agent.adapters.langgraph") for name in _imports(path))


def test_reauth_langgraph_resume_is_checkpoint_transport_only() -> None:
    method=_method(LANGGRAPH_RESUME,"LangGraphWorkflowRuntime","_resume_after_reauth_transition")
    calls={ast.unparse(node.func) for node in ast.walk(method) if isinstance(node,ast.Call)}
    forbidden=("_latest_unknown_action","_has_executed_action","_mark_stalled_claims_as_unknown","recover_unknown","recover_executed","_write_recovery","runs.","actions.","approvals.")
    for call in calls:
        assert not any(token in call for token in forbidden),f"reauth adapter owns semantic decision: {call}"
    assert any(name.endswith("resolve_resume_authority") for name in calls)
    assert any(name.endswith("_graph.update_state") for name in calls)
    assert any(name.endswith("_graph.invoke") for name in calls)


def test_safe_checkpoint_resume_has_no_terminal_blocked_registration() -> None:
    source=(USE_CASE_ROOT/"run/resume_run.py").read_text(encoding="utf-8")
    assert '"SAFE_CHECKPOINT_RESUME": RunStatus.BLOCKED' not in source


def test_event_route_keeps_transport_but_not_replay_fallback_semantics() -> None:
    source=(ROOT/"src/google_work_agent/api/routes/events.py").read_text(encoding="utf-8")
    assert "StreamingResponse" in source and "_format_sse" in source and ".subscribe(" in source and "keepalive" in source
    assert ".replay(" not in source and "SnapshotRequiredReplayError" not in source and "InvalidReplayCursorError" not in source and "build_snapshot_required_event" not in source
    assert "GetEventReplayHandler" in source
