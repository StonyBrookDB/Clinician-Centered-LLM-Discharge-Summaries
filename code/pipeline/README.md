# Public Discharge Pipeline

This directory is a self-contained public export of the LangChain/LangGraph discharge-summary pipeline. It imports a CSV bundle into SQLite, chunks notes chronologically, generates an iterative structured summary, extracts incidental findings from flagged notes, formats a final narrative, and writes text/JSON outputs.

The included demo data is fully synthetic. Do not place protected health information, credentials, private databases, RTF/Word files, or generated reviewer artifacts in this directory.

## Install

From this directory:

```bash
python -m venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

For live OpenAI runs, copy `.env.example` to `.env` and set `OPENAI_API_KEY`.

## Run The Synthetic Demo

The mock LLM path requires no network access and is intended for testing installation and output structure:

```bash
PYTHONPATH=src python -m discharge_pipeline.cli run \
  --input-dir examples/synthetic_demo \
  --output-dir runs \
  --run-id synthetic_demo \
  --mock-llm
```

Outputs are written under `runs/synthetic_demo/`. For the included single encounter, generated files are under `runs/synthetic_demo/synthetic-001/`.

## Run With OpenAI

```bash
PYTHONPATH=src python -m discharge_pipeline.cli run \
  --input-dir path/to/your/csv_bundle \
  --output-dir runs \
  --model gpt-4.1
```

Useful options:

- `--chunk-size 50000` controls maximum tokens per chunk.
- `--prompt-dir path/to/prompts` lets you test edited prompt assets.
- `--run-id name` writes to a stable output folder and fails if it already exists.

## Pipeline Shape

```text
PUBLIC EXPORT PIPELINE

CSV bundle
  |
  |-- encounters.csv
  |-- notes.csv
  |-- note_types.csv optional
  v
SQLite import
  |
  |-- validates required columns
  |-- creates opaque source_id for each note
  |-- stores encounters, notes, note_types
  v
Build chunks
  |
  +------------------------------+
  |                              |
  v                              v
Clinical chunks                 Incidental-note chunks
include_for_summary=true        include_for_incidental=true
chronological                   chronological
source_id citations             source_id citations
  |                              |
  v                              |
STRUCTURED SUMMARY LANGGRAPH     |
  |                              |
  |  START                       |
  |    |                         |
  |    v                         |
  |  generate_initial            |
  |    |                         |
  |    v                         |
  |  index >= len(contents)?     |
  |    |                         |
  |    +-- yes --> END           |
  |    |                         |
  |    +-- no --> refine         |
  |                 |            |
  |                 v            |
  |              index >= len(contents)?
  |                 |            |
  |                 +-- yes --> END
  |                 |            |
  |                 +-- no ------+
  |                              |
  v                              |
structured_summary draft         |
  |                              |
  +------------------------------+
  v
INCIDENTAL FINDINGS LANGGRAPH
  |
  |  contents = structured summary + incidental-note chunks
  |
  |  START
  |    |
  |    v
  |  generate_initial
  |    |
  |    v
  |  index >= len(contents)?
  |    |
  |    +-- yes --> END
  |    |
  |    +-- no --> refine
  |                 |
  |                 v
  |              index >= len(contents)?
  |                 |
  |                 +-- yes --> END
  |                 |
  |                 +-- no ------+
  |
  v
incidental_findings block
  |
  v
Merge incidental_findings into structured summary
  |
  +-----------------------------+-----------------------------+-----------------------------+
  |                             |                             |                             |
  v                             v                             v                             v
structured_summary.xml          structured_summary.json       narrative formatting          citations.json
final XML-like summary          parsed sections/bullets       plain async LLM call          source_id provenance
                                                              |
                                                              v
                                                        narrative_summary.txt

Run-level outputs:
  |
  |-- pipeline.sqlite
  |-- chunks.jsonl
  |-- run_config.json
  |-- run_results.json
  |-- usage.csv
  |-- prompts_used/
  |
Encounter-level outputs:
  |
  |-- structured_summary.xml
  |-- structured_summary.json
  |-- narrative_summary.txt
  |-- incidental_findings.json
  |-- citations.json
  |-- drafts.json
```

## Input CSV Bundle

Each input directory must contain `encounters.csv` and `notes.csv`. It may also contain `note_types.csv`.

Required `encounters.csv` columns:

- `encounter_id`
- `age`
- `sex`
- `admission_datetime`

Required `notes.csv` columns:

- `encounter_id`
- `note_id`
- `note_type`
- `publish_datetime`
- `note_text`

Optional `notes.csv` columns:

- `include_for_summary`: defaults to true unless the note type says otherwise.
- `include_for_incidental`: defaults to false unless the note type says otherwise.
- `is_reference_summary`: defaults to false; true rows are excluded from model input.

Use non-identifying `encounter_id` and `note_id` values. The pipeline derives opaque `source_id` values from those fields for model-visible citations.

Optional `note_types.csv` columns:

- `note_type`
- `include_for_summary`
- `include_for_incidental`

The public export intentionally has no built-in study-specific note-type exclusions. If your dataset needs exclusions, express them explicitly with `include_for_summary=false` or `include_for_incidental=false`.

## Outputs

Run-level outputs:

- `pipeline.sqlite`: internal SQLite database generated from CSV inputs.
- `chunks.jsonl`: clinical and incidental chunk text plus metadata.
- `run_config.json`: run settings and encounter IDs.
- `run_results.json`: aggregate machine-readable result object.
- `usage.csv`: token usage by encounter and stage when provided by the model.
- `prompts_used/`: snapshot of prompt files used for the run.

Encounter-level outputs:

- `structured_summary.xml`: final XML-like bulleted summary.
- `structured_summary.json`: parsed sections, bullets, citations, and metadata.
- `narrative_summary.txt`: final narrative version.
- `incidental_findings.json`: parsed incidental findings section.
- `citations.json`: cited `source_id` metadata without original filenames.
- `drafts.json`: intermediate structured drafts.

Run directories generated from real data contain clinical note text in `pipeline.sqlite`, `chunks.jsonl`, and model outputs. Do not publish or share run directories unless they have been reviewed and cleared outside this package.

## Prompt Assets

The prompt files in `prompts/` were copied from the research pipeline:

- `prompt.txt`
- `incidental_findings_prompt.txt`
- `incidental_findings_refine_prompt.txt`
- `final_narrative_prompt.txt`

## Extending

Use the CSV flags rather than adding dataset-specific exclusions to code. If you add new output formats, keep them outside the model-visible prompt context unless needed.
