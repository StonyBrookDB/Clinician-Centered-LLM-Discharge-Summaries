"""Shared data models for the public discharge pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PipelinePaths:
    """Resolved paths used by one pipeline run."""

    input_dir: Path
    prompt_dir: Path
    run_dir: Path
    database_path: Path


@dataclass
class TokenUsage:
    """Simple token-usage accumulator."""

    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.input_tokens += int(input_tokens or 0)
        self.output_tokens += int(output_tokens or 0)

    def add_from(self, result: "LLMResult") -> None:
        self.add(result.input_tokens, result.output_tokens)

    def as_row(self, stage: str, encounter_id: str, model: str) -> Dict[str, Any]:
        return {
            "encounter_id": encounter_id,
            "stage": stage,
            "model": model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass
class LLMResult:
    """Normalized LLM response."""

    content: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class NoteChunk:
    """A chunk of model-visible note context."""

    encounter_id: str
    chunk_position: int
    chunk_text: str
    num_tokens: int
    num_included_notes: int
    stay_day_start: Optional[int] = None
    stay_day_end: Optional[int] = None
    source_ids: List[str] = field(default_factory=list)


@dataclass
class EncounterRunResult:
    """Artifacts generated for one encounter."""

    encounter_id: str
    structured_summary: str
    structured_json: Dict[str, Any]
    narrative_summary: str
    incidental_findings: Dict[str, Any]
    citations: Dict[str, Any]
    usage_rows: List[Dict[str, Any]]
