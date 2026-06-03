"""Helpers for loading encounter assets and note manifests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional

from eval_v2.services import file_encryption
from eval_v2.config import DATA_DIR

RAW_DATA_DIR = DATA_DIR / "raw"


@dataclass
class ClinicalNote:
    position: int
    file_name: str
    path: Path
    cited_by_ai: bool = False
    pdf_path: Optional[Path] = field(default=None)
    relative_day: Optional[int] = field(default=None)
    note_type: Optional[str] = field(default=None)
    publish_ts_raw: Optional[str] = field(default=None)

    @property
    def display_name(self) -> str:
        base_name = self.file_name.replace("_", " ").replace(".rtf", "")
        if self.relative_day is not None:
            return f"{base_name} (Day {self.relative_day})"
        return base_name

    @property
    def has_html(self) -> bool:
        """HTML is always available via on-the-fly RTF conversion."""
        return self.path.exists() and self.file_name.endswith(".rtf")

    @property
    def has_pdf(self) -> bool:
        return self.pdf_path is not None and self.pdf_path.exists()

    def read_bytes(self) -> bytes:
        return file_encryption.get_bytes(self.path)

    def read_text(self, encoding: str = "utf-8", errors: str = "ignore") -> str:
        return self.read_bytes().decode(encoding, errors=errors)


@dataclass
class EncounterDocuments:
    encounter_number: str
    encounter_dir: Path
    inpatient_summary_rtf: Optional[Path]
    inpatient_summary_pdf: Optional[Path]
    human_summary_rtf: Optional[Path]
    human_summary_pdf: Optional[Path]
    ai_summary_txt: Optional[Path]
    clinical_notes: List[ClinicalNote]


def load_encounter_documents(encounter_number: int | str, base_dir: Path = RAW_DATA_DIR) -> EncounterDocuments:
    """Load manifest-driven assets for an encounter."""
    encounter_number = str(encounter_number)
    encounter_dir = (base_dir / encounter_number).resolve()

    if not encounter_dir.exists():
        raise FileNotFoundError(f"Encounter directory not found: {encounter_dir}")

    inpatient_summary_rtf = _optional_path(encounter_dir / "inpatient_clinical_summary.rtf")
    inpatient_summary_pdf = _optional_path(encounter_dir / "inpatient_clinical_summary.pdf")
    human_summary_rtf = _optional_path(encounter_dir / "summary_A.rtf")
    human_summary_pdf = _optional_path(encounter_dir / "summary_A.pdf")
    ai_summary_txt = _optional_path(encounter_dir / "summary_b_narrative.txt")
    if ai_summary_txt is None:
        ai_summary_txt = _optional_path(encounter_dir / "summary_B.txt")

    notes_dir = encounter_dir / "rtfs"
    manifest_path = notes_dir / "manifest.json"
    cited_notes_path = notes_dir / "cited.json"
    clinical_notes: list[ClinicalNote] = []
    cited_names: set[str] = set()

    if cited_notes_path.exists():
        try:
            cited_payload = json.loads(file_encryption.get_bytes(cited_notes_path).decode("utf-8"))
            if isinstance(cited_payload, list):
                cited_names = {str(item) for item in cited_payload}
            elif isinstance(cited_payload, dict):
                if isinstance(cited_payload.get("cited_notes"), list):
                    cited_names = {str(item) for item in cited_payload["cited_notes"]}
                else:
                    cited_names = {str(value) for value in cited_payload.values() if isinstance(value, str)}
        except (json.JSONDecodeError, TypeError):
            cited_names = set()

    relative_dates_path = notes_dir / "relative_dates.json"
    relative_dates: dict[str, int] = {}
    if relative_dates_path.exists():
        try:
            relative_dates_payload = json.loads(file_encryption.get_bytes(relative_dates_path).decode("utf-8"))
            if isinstance(relative_dates_payload, dict):
                relative_dates = {str(k): int(v) for k, v in relative_dates_payload.items() if isinstance(v, (int, float))}
        except (json.JSONDecodeError, TypeError, ValueError):
            relative_dates = {}

    note_types_path = notes_dir / "note_types.json"
    note_types: dict[str, str] = {}
    if note_types_path.exists():
        try:
            note_types_payload = json.loads(file_encryption.get_bytes(note_types_path).decode("utf-8"))
            if isinstance(note_types_payload, dict):
                note_types = {
                    str(k): v
                    for k, v in note_types_payload.items()
                    if isinstance(v, str) and v.strip()
                }
        except (json.JSONDecodeError, TypeError):
            note_types = {}

    publish_dates_path = notes_dir / "note_publish_dates.json"
    publish_dates: dict[str, str] = {}
    if publish_dates_path.exists():
        try:
            publish_dates_payload = json.loads(file_encryption.get_bytes(publish_dates_path).decode("utf-8"))
            if isinstance(publish_dates_payload, dict):
                publish_dates = {
                    str(k): v
                    for k, v in publish_dates_payload.items()
                    if isinstance(v, str) and v.strip()
                }
        except (json.JSONDecodeError, TypeError):
            publish_dates = {}

    if manifest_path.exists():
        manifest = json.loads(file_encryption.get_bytes(manifest_path).decode("utf-8"))
        for key, value in _iter_manifest(manifest):
            note_path = notes_dir / value
            pdf_path = _optional_path(note_path.with_suffix(".pdf"))

            clinical_notes.append(
                ClinicalNote(
                    position=key,
                    file_name=value,
                    path=note_path,
                    cited_by_ai=value in cited_names,
                    pdf_path=pdf_path,
                    relative_day=relative_dates.get(value),
                    note_type=note_types.get(value),
                    publish_ts_raw=publish_dates.get(value),
                )
            )
    else:
        # Fallback: alphabetical listing
        for idx, note_path in enumerate(sorted(notes_dir.glob("*.rtf"))):
            pdf_path = _optional_path(note_path.with_suffix(".pdf"))

            clinical_notes.append(
                ClinicalNote(
                    position=idx,
                    file_name=note_path.name,
                    path=note_path,
                    cited_by_ai=note_path.name in cited_names,
                    pdf_path=pdf_path,
                    relative_day=relative_dates.get(note_path.name),
                    note_type=note_types.get(note_path.name),
                    publish_ts_raw=publish_dates.get(note_path.name),
                )
            )

    clinical_notes.sort(key=lambda note: note.position)

    return EncounterDocuments(
        encounter_number=encounter_number,
        encounter_dir=encounter_dir,
        inpatient_summary_rtf=inpatient_summary_rtf,
        inpatient_summary_pdf=inpatient_summary_pdf,
        human_summary_rtf=human_summary_rtf,
        human_summary_pdf=human_summary_pdf,
        ai_summary_txt=ai_summary_txt,
        clinical_notes=clinical_notes,
    )


def _iter_manifest(manifest: dict) -> Iterable[tuple[int, str]]:
    """Yield manifest entries as (position, file_name) pairs."""
    for raw_position, file_name in manifest.items():
        try:
            position = int(raw_position)
        except (TypeError, ValueError):
            continue
        yield position, file_name


def _optional_path(path: Path) -> Optional[Path]:
    """Return the path if it exists, else None."""
    return path if path.exists() else None
