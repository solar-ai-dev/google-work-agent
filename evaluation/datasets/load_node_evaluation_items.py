"""Strict current Node Evaluation item loader."""

from pathlib import Path

from evaluation.contracts.evaluation_contract import load_strict_json
from evaluation.contracts.node_evaluation_item import NodeEvaluationItemV1

DEFAULT_NODE_ITEMS_PATH = Path(__file__).with_name("node_evaluation_items_v1.jsonl")


def load_node_evaluation_items(
    path: Path = DEFAULT_NODE_ITEMS_PATH,
) -> tuple[NodeEvaluationItemV1, ...]:
    rows: list[NodeEvaluationItemV1] = []
    ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"blank Node Evaluation row at line {line_number}")
        row = NodeEvaluationItemV1.model_validate(load_strict_json(line), strict=True)
        if row.runtime_item_id in ids:
            raise ValueError(f"duplicate runtime_item_id: {row.runtime_item_id}")
        ids.add(row.runtime_item_id)
        rows.append(row)
    return tuple(rows)


__all__ = ["DEFAULT_NODE_ITEMS_PATH", "load_node_evaluation_items"]
