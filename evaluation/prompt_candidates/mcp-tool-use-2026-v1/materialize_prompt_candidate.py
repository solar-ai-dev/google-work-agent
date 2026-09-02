"""CLI for the canonical Evaluation-owned Prompt candidate materializer."""

from __future__ import annotations

import argparse
from pathlib import Path

from evaluation.prompt_candidate import materialize_prompt_candidate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository-root", type=Path)
    args = parser.parse_args()

    candidate_dir = Path(__file__).resolve().parent
    repository_root = (
        args.repository_root.resolve()
        if args.repository_root is not None
        else candidate_dir.parents[2]
    )
    materialize_prompt_candidate(
        candidate_path=candidate_dir / "candidate.json",
        repository_root=repository_root,
        output_dir=args.output,
    )


if __name__ == "__main__":
    main()
