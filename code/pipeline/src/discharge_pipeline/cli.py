"""Command-line interface for the public discharge pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from .pipeline import DEFAULT_CHUNK_SIZE, default_prompt_dir, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the public discharge-summary pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the pipeline on a CSV bundle.")
    run_parser.add_argument("--input-dir", type=Path, required=True, help="Directory containing encounters.csv and notes.csv.")
    run_parser.add_argument("--output-dir", type=Path, default=Path("runs"), help="Directory where run folders are created.")
    run_parser.add_argument("--run-id", default=None, help="Optional explicit run id.")
    run_parser.add_argument("--prompt-dir", type=Path, default=default_prompt_dir(), help="Prompt directory.")
    run_parser.add_argument("--model", default="gpt-4.1", help="OpenAI model name.")
    run_parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="Maximum tokens per chunk.")
    run_parser.add_argument("--mock-llm", action="store_true", help="Use deterministic local mock outputs.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        run_dir = run_pipeline(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            model=args.model,
            chunk_size=args.chunk_size,
            run_id=args.run_id,
            prompt_dir=args.prompt_dir,
            mock_llm=args.mock_llm,
        )
        print(f"Wrote run outputs to {run_dir}")
        return 0
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
