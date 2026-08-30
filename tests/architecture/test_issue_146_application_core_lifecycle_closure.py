from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
LEDGER = ROOT / "implementation-inventory/ledger.md"
CURRENT_MAP = ROOT / "implementation-inventory/canonical-current-implementation-map.md"
SOURCE = ROOT / "src/google_work_agent"


def _owned_ledger_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\| (CAP-APP-(?:00[1-9]|0[1-4][0-9]|050)) \|", line)
        if match:
            rows[match.group(1)] = [part.strip() for part in line.strip("|").split("|")]
    return rows


def test_issue_146_owns_exactly_fifty_ledger_and_map_rows() -> None:
    expected = {f"CAP-APP-{index:03d}" for index in range(1, 51)}
    rows = _owned_ledger_rows()
    assert set(rows) == expected
    map_text = CURRENT_MAP.read_text(encoding="utf-8")
    assert {
        identifier
        for identifier in expected
        if re.search(rf"^\| {identifier} \|", map_text, re.MULTILINE)
    } == expected


def test_issue_146_exact_sources_tests_symbols_and_production_callers_exist() -> None:
    production = {
        path: path.read_text(encoding="utf-8")
        for path in SOURCE.rglob("*.py")
    }
    for identifier, row in _owned_ledger_rows().items():
        directory, filename, symbols, test_path = row[8], row[9], row[10], row[11]
        owner = SOURCE / directory / filename
        assert owner.is_file(), f"{identifier}: missing owner {owner}"
        assert (ROOT / test_path).is_file(), f"{identifier}: missing test {test_path}"
        owner_text = owner.read_text(encoding="utf-8")
        handler_symbols = re.findall(r"\b[A-Z][A-Za-z0-9]+Handler\b", symbols)
        assert handler_symbols, f"{identifier}: handler symbol missing from Ledger"
        for symbol in handler_symbols:
            assert re.search(rf"\bclass {symbol}\b", owner_text), (
                f"{identifier}: {symbol} is absent from exact owner"
            )
            caller_count = sum(
                len(re.findall(rf"\b{symbol}\b", text))
                for path, text in production.items()
                if path != owner
            )
            assert caller_count > 0, f"{identifier}: {symbol} has no production caller"


def test_issue_146_run_budget_has_one_semantic_authority_and_no_v1_residual() -> None:
    source_text = "\n".join(
        path.read_text(encoding="utf-8") for path in SOURCE.rglob("*.py")
    )
    assert "RunBudgetV1" not in source_text
    assert "validate_run_budget_v1" not in source_text
    assert 'budget_json="{}"' not in source_text

    contracts = (
        SOURCE / "application/orchestration/contracts.py"
    ).read_text(encoding="utf-8")
    forbidden_reexports = (
        "BudgetDecision",
        "BudgetProfile",
        "approve_additional_acquisition",
        "check_llm_call_budget",
        "validate_run_budget_v2",
    )
    assert all(name not in contracts for name in forbidden_reexports)

    guard = (
        SOURCE / "application/use_cases/run/guard_run_budget.py"
    ).read_text(encoding="utf-8")
    assert guard.count("class GuardRunBudgetHandler") == 1
    dispatch = (
        SOURCE / "application/orchestration/provider_dispatch_budget.py"
    ).read_text(encoding="utf-8")
    assert "GuardRunBudgetHandler()(" in dispatch


def test_issue_146_application_does_not_import_concrete_adapters() -> None:
    violations: list[str] = []
    for path in (SOURCE / "application").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "google_work_agent.adapters" in text:
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_issue_146_sqlite_queries_use_a_read_only_uow_boundary() -> None:
    unit_of_work = (
        SOURCE / "adapters/persistence/sqlite/unit_of_work.py"
    ).read_text(encoding="utf-8")
    assert "def sqlite_read_unit_of_work_factory(" in unit_of_work
    assert 'connection.execute("PRAGMA query_only = ON;")' in unit_of_work
    assert 'connection.execute("BEGIN;")' in unit_of_work

    run_routes = (SOURCE / "api/routes/runs.py").read_text(encoding="utf-8")
    assert run_routes.count(
        "unit_of_work_factory=dependencies.read_unit_of_work_factory"
    ) == 2
