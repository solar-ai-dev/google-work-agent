from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "src/google_work_agent"
LEDGER = ROOT / "implementation-inventory/ledger.md"
CURRENT_MAP = ROOT / "implementation-inventory/canonical-current-implementation-map.md"


def _owned_ledger_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\| (CAP-APP-(?:05[1-9]|06[0-9]|070)) \|", line)
        if match:
            rows[match.group(1)] = [part.strip() for part in line.strip("|").split("|")]
    return rows


def test_issue_147_owns_exactly_twenty_ledger_and_map_rows() -> None:
    expected = {f"CAP-APP-{index:03d}" for index in range(51, 71)}
    assert set(_owned_ledger_rows()) == expected
    map_text = CURRENT_MAP.read_text(encoding="utf-8")
    assert {
        identifier
        for identifier in expected
        if re.search(rf"^\| {identifier} \|", map_text, re.MULTILINE)
    } == expected


def test_issue_147_exact_owners_tests_symbols_and_callers_exist() -> None:
    production = {
        path: path.read_text(encoding="utf-8") for path in SOURCE.rglob("*.py")
    }
    for identifier, row in _owned_ledger_rows().items():
        directory, filename, symbols, test_path = row[8], row[9], row[10], row[11]
        owner = SOURCE / directory / filename
        assert owner.is_file(), f"{identifier}: missing owner {owner}"
        assert (ROOT / test_path).is_file(), f"{identifier}: missing test {test_path}"
        owner_text = owner.read_text(encoding="utf-8")
        handlers = re.findall(r"\b[A-Z][A-Za-z0-9]+Handler\b", symbols)
        assert handlers, f"{identifier}: Ledger has no handler symbol"
        for handler in handlers:
            assert re.search(rf"\bclass {handler}\b", owner_text)
            assert any(
                re.search(rf"\b{handler}\b", text)
                for path, text in production.items()
                if path != owner
            ), f"{identifier}: {handler} has no production caller"


def test_issue_147_has_one_write_dispatch_chain_and_no_broad_facade() -> None:
    execution_phase = (
        SOURCE / "application/use_cases/execution_attempt/execution_phase.py"
    ).read_text(encoding="utf-8")
    begin = execution_phase.index("begun = self._begin_execution_attempt(")
    dispatch = execution_phase.index("dispatch_result = self._connector_execution.dispatch_write(")
    classify = execution_phase.index("decision = self._classify_dispatch_result(")
    settlement = min(
        execution_phase.index("self._store_write_success("),
        execution_phase.index("self._mark_write_failed("),
        execution_phase.index("self._mark_write_unknown("),
    )
    assert begin < dispatch < classify < settlement
    assert execution_phase.count(".dispatch_write(") == 1
    assert 'command_id=f"begin-execution-attempt:{attempt_id}"' in execution_phase

    dispatch_owner = (
        SOURCE
        / "application/use_cases/execution_attempt/dispatch_connector_write.py"
    ).read_text(encoding="utf-8")
    assert dispatch_owner.count("._connector_write_port.execute_write(") == 1
    assert ".commit(" not in dispatch_owner

    models = (
        SOURCE / "application/use_cases/execution_attempt/write_dispatch_models.py"
    ).read_text(encoding="utf-8")
    projection = (
        SOURCE / "application/use_cases/execution_attempt/connector_write_projection.py"
    ).read_text(encoding="utf-8")
    assert "WriteResultMaterializer" not in models
    assert "def execute_write(" not in projection
    assert "fetch_verification_snapshot" not in projection
    assert "search_recovery_candidates" not in projection


def test_issue_147_write_replay_and_recovery_never_create_a_second_write() -> None:
    claim_validation = (
        SOURCE
        / "adapters/connectors/google/workspace/mcp_server/validate_claim_context.py"
    ).read_text(encoding="utf-8")
    nonce_check = claim_validation.index("if nonce in runtime_state.used_nonces:")
    nonce_consume = claim_validation.index("runtime_state.used_nonces.add(nonce)")
    assert nonce_check < nonce_consume

    recovery_root = SOURCE / "application/use_cases/recovery"
    recovery_text = "\n".join(
        path.read_text(encoding="utf-8") for path in recovery_root.rglob("*.py")
    )
    assert "ConnectorWritePort" not in recovery_text
    assert ".execute_write(" not in recovery_text
    assert "DispatchConnectorWriteHandler" not in recovery_text

    verification_root = SOURCE / "application/use_cases/verification"
    verification_text = "\n".join(
        path.read_text(encoding="utf-8") for path in verification_root.rglob("*.py")
    )
    assert "ConnectorWritePort" not in verification_text
    assert ".execute_write(" not in verification_text


def test_issue_147_keeps_domain_and_adapter_boundaries_singular() -> None:
    application_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (SOURCE / "application").rglob("*.py")
    )
    assert "google_work_agent.adapters" not in application_text

    connector_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (SOURCE / "adapters/connectors").rglob("*.py")
    )
    assert "execution_attempts.update_if_version_and_status" not in connector_text
    assert "actions.update_if_version_and_status" not in connector_text

    projection = (
        SOURCE / "application/use_cases/recovery/project_recovery_options.py"
    ).read_text(encoding="utf-8")
    resolution = (
        SOURCE / "application/use_cases/recovery/resolve_recovery.py"
    ).read_text(encoding="utf-8")
    assert "project_allowed_recovery_resolutions" in projection
    assert "allowed_recovery_resolutions(" in resolution

    resource_model = (
        SOURCE / "domain/resource_ref/model.py"
    ).read_text(encoding="utf-8")
    resource_ref_fields = resource_model.split("class ResourceRef:", 1)[1]
    assert "source:" not in resource_ref_fields


def test_issue_147_reconciliation_is_startup_only() -> None:
    launcher = (SOURCE / "launcher/dev.py").read_text(encoding="utf-8")
    loop = (
        SOURCE / "adapters/system/workflow_handoff_reconciliation_loop.py"
    ).read_text(encoding="utf-8")
    assert "production_runtime.reconcile_inflight_executions(" in launcher
    assert "ReconcileInflightExecutionsHandler" not in loop
    assert "reconcile_inflight_executions" not in loop
