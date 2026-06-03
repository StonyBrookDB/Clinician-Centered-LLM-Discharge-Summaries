"""Public pipeline orchestration."""

from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .chunking import build_chunks, write_chunks_jsonl
from .data import import_csv_bundle, list_encounter_ids, load_source_metadata
from .graph import (
    format_narrative,
    generate_incidental_findings,
    generate_structured_summary,
    run_async,
)
from .llm import MockLLMClient, OpenAILLMClient
from .models import EncounterRunResult, PipelinePaths
from .parsing import build_citations, merge_incidental_into_summary, parse_summary_sections


DEFAULT_CHUNK_SIZE = 50_000


def default_prompt_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "prompts"


def make_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _copy_prompt_snapshot(prompt_dir: Path, run_dir: Path) -> None:
    snapshot_dir = run_dir / "prompts_used"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for prompt_file in sorted(prompt_dir.glob("*.txt")):
        shutil.copy2(prompt_file, snapshot_dir / prompt_file.name)


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    model: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    run_id: Optional[str] = None,
    prompt_dir: Optional[Path] = None,
    mock_llm: bool = False,
) -> Path:
    """Run the full public pipeline and return the run directory."""

    run_dir = output_dir / (run_id or make_run_id())
    run_dir.mkdir(parents=True, exist_ok=False)
    resolved_prompt_dir = (prompt_dir or default_prompt_dir()).resolve()
    database_path = run_dir / "pipeline.sqlite"
    paths = PipelinePaths(
        input_dir=input_dir.resolve(),
        prompt_dir=resolved_prompt_dir,
        run_dir=run_dir.resolve(),
        database_path=database_path.resolve(),
    )

    connection = import_csv_bundle(paths.input_dir, paths.database_path)
    llm = MockLLMClient() if mock_llm else OpenAILLMClient(model_name=model)
    model_name = llm.model_name

    encounter_ids = list_encounter_ids(connection)
    clinical_chunks: Dict[str, Any] = {}
    incidental_chunks: Dict[str, Any] = {}
    all_usage_rows: List[Dict[str, Any]] = []
    run_results: Dict[str, Dict[str, Any]] = {}

    for encounter_id in encounter_ids:
        clinical = build_chunks(connection, encounter_id, chunk_size, incidental=False)
        incidental = build_chunks(connection, encounter_id, chunk_size, incidental=True)
        clinical_chunks[encounter_id] = clinical
        incidental_chunks[encounter_id] = incidental

        structured, drafts, summary_usage = run_async(
            generate_structured_summary(
                clinical,
                llm,
                paths.prompt_dir,
            )
        )
        incidental_block, incidental_usage = run_async(
            generate_incidental_findings(structured, incidental, llm, paths.prompt_dir)
        )
        merged_structured = merge_incidental_into_summary(structured, incidental_block)
        narrative, narrative_usage = run_async(
            format_narrative(merged_structured, llm, paths.prompt_dir)
        )
        parsed_summary = parse_summary_sections(merged_structured)
        parsed_summary["metadata"] = {
            "encounter_id": encounter_id,
            "model": model_name,
            "chunk_size": chunk_size,
            "num_chunks": len(clinical),
        }
        incidental_json = {"incidental_findings": parsed_summary.get("incidental_findings", [])}
        citations = build_citations(parsed_summary, load_source_metadata(connection, encounter_id))

        encounter_dir = run_dir / str(encounter_id)
        encounter_dir.mkdir(parents=True, exist_ok=True)
        _write_text(encounter_dir / "structured_summary.xml", merged_structured)
        _write_json(encounter_dir / "structured_summary.json", parsed_summary)
        _write_text(encounter_dir / "narrative_summary.txt", narrative)
        _write_json(encounter_dir / "incidental_findings.json", incidental_json)
        _write_json(encounter_dir / "citations.json", citations)
        _write_json(encounter_dir / "drafts.json", {"drafts": drafts})

        usage_rows = [
            summary_usage.as_row("structured_summary", encounter_id, model_name),
            incidental_usage.as_row("incidental_findings", encounter_id, model_name),
            narrative_usage.as_row("narrative", encounter_id, model_name),
        ]
        all_usage_rows.extend(usage_rows)
        run_results[encounter_id] = EncounterRunResult(
            encounter_id=encounter_id,
            structured_summary=merged_structured,
            structured_json=parsed_summary,
            narrative_summary=narrative,
            incidental_findings=incidental_json,
            citations=citations,
            usage_rows=usage_rows,
        ).__dict__

    write_chunks_jsonl(run_dir / "chunks.jsonl", clinical_chunks, incidental_chunks)
    _write_json(
        run_dir / "run_config.json",
        {
            "input_dir": str(paths.input_dir),
            "prompt_dir": str(paths.prompt_dir),
            "model": model_name,
            "chunk_size": chunk_size,
            "mock_llm": mock_llm,
            "encounter_ids": encounter_ids,
        },
    )
    _write_json(run_dir / "run_results.json", run_results)
    with (run_dir / "usage.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["encounter_id", "stage", "model", "input_tokens", "output_tokens"],
        )
        writer.writeheader()
        writer.writerows(all_usage_rows)
    _copy_prompt_snapshot(paths.prompt_dir, run_dir)
    connection.close()
    return run_dir
