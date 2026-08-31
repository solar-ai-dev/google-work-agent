from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--dataset-root", default="experiments")
    args = parser.parse_args()
    result = {
        "status": "BLOCKED",
        "runner_interface": "IMPLEMENTED",
        "config": args.config,
        "dataset_root": str(Path(args.dataset_root)),
        "reason": (
            "Application Port, FakeGoogleGateway, or FakeLLMProvider is not "
            "implemented in this repository snapshot."
        ),
        "result_schema": {
            "evaluation_item_id": "string",
            "status": "PASS|FAIL|BLOCKED",
            "metrics": {},
            "errors": [],
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
