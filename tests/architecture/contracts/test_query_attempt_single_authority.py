import ast
from pathlib import Path


def test_query_attempt_v1_has_one_schema_authority() -> None:
    root = Path(__file__).resolve().parents[3]
    source_root = root / "src/google_work_agent"
    definitions: list[Path] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.ClassDef) and node.name in {"QueryAttempt", "QueryAttemptV1"}
            for node in ast.walk(tree)
        ):
            definitions.append(path)

    assert definitions == [source_root / "application/agents/retrieval/contracts/query_attempt.py"]
