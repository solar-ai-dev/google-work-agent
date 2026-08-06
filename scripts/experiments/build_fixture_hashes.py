from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "experiments" / "datasets" / "google_workspace" / "fixtures"


def canonical_hash(data: object) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    results = []
    for path in sorted(FIXTURES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        expected = data.get("fixture_content_hash", {}).get("value")
        actual = canonical_hash({k: v for k, v in data.items() if k != "fixture_content_hash"})
        results.append(
            {
                "fixture_snapshot_id": data.get("fixture_snapshot_id"),
                "path": path.relative_to(ROOT).as_posix(),
                "hash_contract_status": data.get("fixture_content_hash", {}).get("status", "TBD"),
                "expected": expected,
                "actual": actual,
                "match": expected == actual,
            }
        )
    print(json.dumps({"status": "PASS" if all(r["match"] for r in results) else "FAIL", "fixtures": results}, ensure_ascii=False, indent=2))
    return 0 if all(r["match"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
