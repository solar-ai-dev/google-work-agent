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
LANGGRAPH_RESUME = ROOT / "src/google_work_agent/adapters/langgraph/main/resume_checkpoint.py"
OWNERS = ("run", "conversation", "message", "recovery")

_REAUTH_FORBIDDEN_MEMBERS = {
    "_latest_unknown_action",
    "_has_executed_action",
    "_mark_stalled_claims_as_unknown",
    "recover_unknown",
    "recover_executed",
    "_write_recovery",
    "resume_reauth_execution",
    "_resume_reauth_execution",
    "_transition_run",
    "_transition_action",
    "_transition_approval",
    "prepare_write_retry",
    "claim_execution",
    "approve_action",
    "create_approval",
    "retry",
    "resend",
}
_REAUTH_FORBIDDEN_OWNERS = {"runs", "actions", "approvals"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _function(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path}: endpoint {name} missing")


def _class_methods(source: str, class_name: str) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                item.name: item
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    raise AssertionError(f"class {class_name} missing")


def _method(path: Path, class_name: str, method_name: str) -> ast.FunctionDef:
    methods = _class_methods(path.read_text(encoding="utf-8"), class_name)
    try:
        return methods[method_name]
    except KeyError as exc:
        raise AssertionError(f"{path}: {class_name}.{method_name} missing") from exc


def _constructs_handler(call: ast.Call, handler: str) -> bool:
    text = ast.unparse(call.func)
    return text == handler or text.startswith(handler + ".")


def _invokes_handler(path: Path, endpoint: str, handler: str) -> bool:
    function = _function(path, endpoint)
    bound = set()
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and _constructs_handler(node.value, handler)
        ):
            bound.update(target.id for target in node.targets if isinstance(target, ast.Name))
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if _constructs_handler(node, handler):
            return True
        if isinstance(node.func, ast.Name) and node.func.id in bound:
            return True
        if isinstance(node.func, ast.Call) and _constructs_handler(node.func, handler):
            return True
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"handle", "__call__"}:
            if isinstance(node.func.value, ast.Name) and node.func.value.id in bound:
                return True
            if isinstance(node.func.value, ast.Call) and _constructs_handler(
                node.func.value, handler
            ):
                return True
    return False


def _attribute_members(node: ast.AST) -> tuple[str, ...]:
    members: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        members.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        members.append(current.id)
    return tuple(reversed(members))


def _self_local_calls(method: ast.AST, local_names: set[str]) -> set[str]:
    calls: set[str] = set()
    for node in ast.walk(method):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if (
            isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr in local_names
        ):
            calls.add(node.func.attr)
    return calls


def _reachable_class_methods(
    source: str, class_name: str, entry_method: str
) -> dict[str, ast.FunctionDef]:
    methods = _class_methods(source, class_name)
    if entry_method not in methods:
        raise AssertionError(f"{class_name}.{entry_method} missing")
    local_names = set(methods)
    visited: set[str] = set()
    pending = [entry_method]
    reachable: dict[str, ast.FunctionDef] = {}
    while pending:
        method_name = pending.pop()
        if method_name in visited:
            continue
        visited.add(method_name)
        method = methods[method_name]
        reachable[method_name] = method
        pending.extend(sorted(_self_local_calls(method, local_names) - visited))
    return reachable


def _reauth_semantic_authority_violations(
    source: str, class_name: str, entry_method: str
) -> set[str]:
    violations: set[str] = set()
    for method_name, method in _reachable_class_methods(source, class_name, entry_method).items():
        for node in ast.walk(method):
            if not isinstance(node, (ast.Call, ast.Attribute)):
                continue
            target = node.func if isinstance(node, ast.Call) else node
            if not isinstance(target, ast.Attribute):
                continue
            members = _attribute_members(target)
            if any(member in _REAUTH_FORBIDDEN_MEMBERS for member in members) or any(
                member in _REAUTH_FORBIDDEN_OWNERS for member in members
            ):
                violations.add(f"{method_name}: {ast.unparse(target)}")
    return violations


def test_route_endpoints_invoke_their_exact_canonical_handlers() -> None:
    cases = {
        ROOT / "src/google_work_agent/api/routes/runs.py": {
            "start_run": "StartRunHandler",
            "get_run_snapshot": "GetRunSnapshotHandler",
            "get_run_context": "GetExecutionContextHandler",
            "cancel_run": "RequestCancelHandler",
            "resume_run": "ResumeRunHandler",
            "confirm_run": "ConfirmRunHandler",
            "resolve_recovery": "ResolveRecoveryHandler",
        },
        ROOT / "src/google_work_agent/api/routes/conversations.py": {
            "create_conversation": "dependencies.create_conversation_handler",
            "list_conversations": "dependencies.list_conversations_handler",
            "get_conversation": "GetConversationHandler",
            "get_conversation_history": "dependencies.get_conversation_history_handler",
            "get_latest_conversation_run": "GetLatestRunHandler",
        },
        ROOT / "src/google_work_agent/api/routes/events.py": {
            "stream_events": "GetEventReplayHandler"
        },
    }
    for path, endpoints in cases.items():
        for endpoint, handler in endpoints.items():
            assert _invokes_handler(path, endpoint, handler), (
                f"{path}:{endpoint} does not invoke {handler}"
            )


def test_owned_routes_do_not_call_broad_legacy_semantic_services() -> None:
    forbidden = (
        ".query_service().",
        ".start_run_service()(",
        ".cancel_run_service()(",
        ".resume_run_service()(",
        ".resolve_recovery_service()(",
        ".create_conversation_service()(",
        "application.queries import",
        "application.start_run import",
        "application.write_actions import",
    )
    for path in ROUTES:
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path}: forbidden route authority {token}"


def test_recovery_production_callers_do_not_bind_legacy_mismatch_authority() -> None:
    for path in (
        ROOT / "src/google_work_agent/api/routes/runs.py",
        ROOT / "src/google_work_agent/launcher/dev.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "ResolveMismatchRecovery" not in source


def test_recovery_has_one_canonical_writer_and_no_legacy_concrete_authority() -> None:
    canonical = {
        ROOT / "src/google_work_agent/application/use_cases/recovery/require_recovery.py",
        ROOT / "src/google_work_agent/application/use_cases/recovery/resolve_recovery.py",
    }
    for path in ROOT.joinpath("src/google_work_agent/application").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "ResolveMismatchRecovery" not in source, path
        if path not in canonical:
            assert ".require_recovery(" not in source, path
            assert ".resolve_recovery(" not in source, path
            assert ".store_context(" not in source, path
            assert ".clear_context(" not in source, path
    assert not (
        ROOT
        / "src/google_work_agent/application/use_cases/recovery/resolve_mismatch_recovery.py"
    ).exists()


def test_migrated_query_handlers_have_no_sqlite_or_legacy_query_bridge() -> None:
    handlers = (
        ROOT / "src/google_work_agent/application/use_cases/run/get_run_snapshot.py",
        ROOT / "src/google_work_agent/application/use_cases/run/get_execution_context.py",
        ROOT / "src/google_work_agent/application/use_cases/run/get_event_replay.py",
        ROOT / "src/google_work_agent/application/use_cases/conversation/get_conversation.py",
        ROOT / "src/google_work_agent/application/use_cases/conversation/get_latest_run.py",
        ROOT / "src/google_work_agent/application/use_cases/conversation/get_conversation_history.py",
    )
    forbidden = ("sqlite3", "database_path", "connection_factory", ".execute(", "from_legacy")
    for path in handlers:
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path}: legacy query boundary {token}"


def test_owned_routes_do_not_traverse_repositories_or_mutate_domain_directly() -> None:
    forbidden_owners = {"runs", "plans", "actions", "approvals", "command_receipts"}
    for path in ROUTES:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert "sqlite3" not in _imports(path)
        assert not any(
            imported.startswith("google_work_agent.adapters.persistence")
            for imported in _imports(path)
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "commit", f"{path}: route commits persistence directly"
            if not isinstance(node, ast.Attribute):
                continue
            segments = ast.unparse(node).split(".")
            assert not (
                len(segments) >= 3
                and segments[0] == "dependencies"
                and segments[1] in forbidden_owners
            ), f"{path}: route traverses repository owner {segments[1]}"


def test_canonical_handlers_do_not_reverse_depend_on_api_or_provider_concretes() -> None:
    forbidden_prefixes = (
        "fastapi",
        "google_work_agent.api",
        "google_work_agent.adapters.persistence.sqlite",
        "google_work_agent.adapters.connectors.google",
        "googleapiclient",
        "google.oauth2",
    )
    for owner in OWNERS:
        for path in (USE_CASE_ROOT / owner).glob("*.py"):
            for imported in _imports(path):
                assert not imported.startswith(forbidden_prefixes), (
                    f"{path}: reverse/concrete dependency {imported}"
                )


def test_canonical_handlers_do_not_delegate_to_broad_legacy_authorities() -> None:
    forbidden = {
        "google_work_agent.application.queries",
        "google_work_agent.application.start_run",
        "google_work_agent.application.run_lifecycle",
        "google_work_agent.application.write_actions",
        "google_work_agent.application.write_cancellation",
        "google_work_agent.application.write_recovery",
    }
    for owner in OWNERS:
        for path in (USE_CASE_ROOT / owner).glob("*.py"):
            assert not (_imports(path) & forbidden), (
                f"{path}: canonical handler delegates to legacy authority"
            )


def test_conversation_message_slice_has_one_production_authority() -> None:
    assert not (ROOT / "src/google_work_agent/application/conversation_lifecycle.py").exists()
    assert not (USE_CASE_ROOT / "message/list_messages.py").exists()
    assert (USE_CASE_ROOT / "message/list_conversation_messages.py").exists()
    broad_ports = (ROOT / "src/google_work_agent/ports/repositories.py").read_text(encoding="utf-8")
    assert not (ROOT / "src/google_work_agent/adapters/persistence/repositories.py").exists()
    assert "class ConversationRepository" not in broad_ports
    assert "class MessageRepository" not in broad_ports


def test_resume_handlers_own_their_exact_transitions_and_commit() -> None:
    path = USE_CASE_ROOT / "run/resume_run.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not any(name.endswith("runs.resume_confirmation") for name in calls)
    assert any(name.endswith("runs.resume_after_reauth") for name in calls)
    assert any(name.endswith("RequireRecoveryHandler.apply_in_unit_of_work") for name in calls)
    assert not any(name.endswith("runs.require_recovery") for name in calls)
    assert any(name.endswith("ResolveRecoveryHandler.recheck_in_unit_of_work") for name in calls)
    assert not any(name.endswith("runs.resolve_recovery") for name in calls)
    assert any(name.endswith("commit") for name in calls)
    assert not any("workflow_runtime.resume" in name for name in calls)
    assert not any(
        name.startswith("google_work_agent.adapters.langgraph") for name in _imports(path)
    )

    confirmation_path = USE_CASE_ROOT / "run/resume_confirmation.py"
    confirmation_tree = ast.parse(confirmation_path.read_text(encoding="utf-8"))
    confirmation_calls = {
        ast.unparse(node.func) for node in ast.walk(confirmation_tree) if isinstance(node, ast.Call)
    }
    assert any(name.endswith("transition_resume_confirmation") for name in confirmation_calls)
    assert any(name.endswith("workflow_handoffs.stage_pending") for name in confirmation_calls)
    assert any(name.endswith("commit") for name in confirmation_calls)


def test_reauth_langgraph_resume_is_checkpoint_transport_only() -> None:
    source = LANGGRAPH_RESUME.read_text(encoding="utf-8")
    violations = _reauth_semantic_authority_violations(
        source,
        "ResumeCheckpointMixin",
        "_resume_after_reauth_transition",
    )
    assert not violations, "reauth adapter owns transitive semantic authority: " + "; ".join(
        sorted(violations)
    )

    reachable = _reachable_class_methods(
        source,
        "ResumeCheckpointMixin",
        "_resume_after_reauth_transition",
    )
    calls = {
        ast.unparse(node.func)
        for method in reachable.values()
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
    }
    assert any(name.endswith("resolve_resume_authority") for name in calls)
    assert any(name.endswith("_graph.update_state") for name in calls)
    assert any(name.endswith("_graph.invoke") for name in calls)


def test_reauth_transitive_authority_analyzer_allows_checkpoint_only_helper_chain() -> None:
    source = """
class Runtime:
    def entry(self):
        return self.helper_a()

    def helper_a(self):
        self._graph.get_state(self._config)
        return self.helper_b()

    def helper_b(self):
        self._validate_checkpoint()
        if False:
            return self.helper_a()
        return self._graph.invoke(None, config=self._config)
"""
    assert _reauth_semantic_authority_violations(source, "Runtime", "entry") == set()
    assert set(_reachable_class_methods(source, "Runtime", "entry")) == {
        "entry",
        "helper_a",
        "helper_b",
    }


def test_reauth_transitive_authority_analyzer_rejects_indirected_recovery_authority() -> None:
    source = """
class Runtime:
    def entry(self):
        return self.helper_a()

    def helper_a(self):
        return self.helper_b()

    def helper_b(self):
        return self._write_recovery.recover_unknown("action-id")
"""
    violations = _reauth_semantic_authority_violations(source, "Runtime", "entry")
    assert any(
        "helper_b: self._write_recovery.recover_unknown" in violation for violation in violations
    )


def test_safe_checkpoint_resume_has_no_terminal_blocked_registration() -> None:
    source = (USE_CASE_ROOT / "run/resume_run.py").read_text(encoding="utf-8")
    assert '"SAFE_CHECKPOINT_RESUME": RunStatus.BLOCKED' not in source


def test_event_route_keeps_transport_but_not_replay_fallback_semantics() -> None:
    source = (ROOT / "src/google_work_agent/api/routes/events.py").read_text(encoding="utf-8")
    assert (
        "StreamingResponse" in source
        and "_format_sse" in source
        and ".subscribe(" in source
        and "keepalive" in source
    )
    assert ".replay(" not in source
    assert "SnapshotRequiredReplayError" not in source
    assert "InvalidReplayCursorError" not in source
    assert "build_snapshot_required_event" not in source
    assert "GetEventReplayHandler" in source
