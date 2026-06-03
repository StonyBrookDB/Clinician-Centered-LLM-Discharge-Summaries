# Public Study Data Export

This folder contains a de-identified export of the study data used to reproduce selected manuscript tables and figures.

## What's Included

- `data/likert_data.csv`: physician survey ratings for each reviewed encounter.
- `data/annotations_data.csv`: annotation scores for identified summary issues.
- `data/reviewer_metadata.csv`: reviewer ID and reviewer role only.
- `data/encounter_metadata.csv`: encounter ID and length of stay only.
- `reproduce_results.py`: script to regenerate the public analysis outputs.
- `analysis/`: regenerated tables, figures, and Markdown captions.

Encounter and reviewer identifiers have been replaced with integer IDs. Reviewer roles and encounter length of stay are retained. Names, comments, timestamps, quoted summary text, and other encounter metadata are not included.

In the exported data, summary A is the human-authored discharge summary and summary B is the LLM-generated discharge summary. Overall preference is coded as `0` for the human-authored summary and `1` for the LLM-generated summary. A Likert score of `-1` means that the question was not answered; for example, hospitalist reviewers did not answer the PCP-only transition-of-care questions.

## Reproduce The Results

From this folder, install the small set of required Python packages:

```bash
python -m pip install -r requirements.txt
```

Then run:

```bash
python reproduce_results.py
```

The script writes fresh outputs to `analysis/`.

## Generated Outputs

- `analysis/table1_mean_survey_ratings_by_question.csv`
- `analysis/table1_mean_survey_ratings_by_question.md`
- `analysis/table_s6_role_delta_by_specialty.csv`
- `analysis/table_s6_role_delta_by_specialty.md`
- `analysis/figure1_annotation_role_statistics.csv`
- `analysis/figure1_annotation_role_statistics.md`
- `analysis/figure1_annotation_summary_type_statistics.csv`
- `analysis/figure1_annotation_summary_type_statistics.md`
- `analysis/figure1_annotation_harm_distribution.jpg`
- `analysis/figure1_annotation_harm_distribution.md`
- `analysis/figure2_los_shared_rating_trends.png`
- `analysis/figure2_los_shared_rating_trends.md`
- `analysis/figure3_role_delta_shared.png`
- `analysis/figure3_role_delta_shared.md`

The Markdown files include the table or figure captions used for the public export.
