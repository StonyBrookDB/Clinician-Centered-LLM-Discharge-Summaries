"""Regenerate publication analysis tables and figures from exported study CSVs.

Run from this directory or from the repository root:

    python reproduce_results.py

The script reads ``data/likert_data.csv`` and ``data/annotations_data.csv`` in
the same directory, then writes CSV, Markdown, and figure outputs under
``analysis/``.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")

from matplotlib.colors import LinearSegmentedColormap
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import mannwhitneyu, spearmanr, wilcoxon


EXPORT_DIR = Path(__file__).resolve().parent
DATA_DIR = EXPORT_DIR / "data"
OUTPUT_DIR = EXPORT_DIR / "analysis"
TABLE1_OUTPUT_PATH = OUTPUT_DIR / "table1_mean_survey_ratings_by_question.csv"
TABLE_S6_OUTPUT_PATH = OUTPUT_DIR / "table_s6_role_delta_by_specialty.csv"
FIG1_STATS_OUTPUT_PATH = OUTPUT_DIR / "figure1_annotation_role_statistics.csv"
FIG1_SUMMARY_STATS_OUTPUT_PATH = OUTPUT_DIR / "figure1_annotation_summary_type_statistics.csv"
FIG1_OUTPUT_PATH = OUTPUT_DIR / "figure1_annotation_harm_distribution.jpg"
FIG2_OUTPUT_PATH = OUTPUT_DIR / "figure2_los_shared_rating_trends.png"
FIG3_OUTPUT_PATH = OUTPUT_DIR / "figure3_role_delta_shared.png"

TEXT_COLOR = "#1E2933"
HUMAN_COLOR = "#7A8794"
AI_COLOR = "#168AAD"
PCP_COLOR = "#2A9D8F"
HOSPITALIST_COLOR = "#6D597A"
GRID_COLOR = "#D6DEE6"
BLUE_CMAP = LinearSegmentedColormap.from_list(
    "readable_blues",
    plt.get_cmap("Blues")(np.linspace(0.12, 0.70, 256)),
)


@dataclass(frozen=True)
class Metric:
    label: str
    human_col: str
    ai_col: str
    pcp_only: bool = False


METRICS = (
    Metric("Overall quality", "human_quality", "ai_quality"),
    Metric("Concise/readable", "human_clarity", "ai_clarity"),
    Metric("Factuality", "human_factuality", "ai_factuality"),
    Metric("Completeness", "human_completeness", "ai_completeness"),
    Metric("Easy to understand", "human_easy_understand", "ai_easy_understand", True),
    Metric("Easy to verbalize", "human_easy_verbalize", "ai_easy_verbalize", True),
    Metric("Easy to follow up", "human_easy_follow_up", "ai_easy_follow_up", True),
)
SHARED_METRICS = tuple(metric for metric in METRICS if not metric.pcp_only)

OUTPUT_COLUMNS = (
    "Question",
    "Evaluators",
    "Mean human-summary score",
    "Mean AI-summary score",
    "Mean score difference",
    "P value",
)

MARKDOWN_COLUMNS = (
    "Question (n)",
    "Evaluators",
    "Human-Authored Summary Mean Likert Score",
    "LLM-Generated Summary Mean Likert Score",
    "Mean Score Difference between LLM-Generated & Human-Authored Summaries",
    "P-Value",
)

TABLE_CAPTION = (
    "Table 1. Mean survey results of physician reviewer ratings for human-authored "
    "vs. LLM-generated discharge summaries, based on a 1-5 Likert rating scale."
)
TABLE_S6_CAPTION = (
    "Table S6. Mean difference in scores between LLM-generated vs. human-authored "
    "summaries, stratified by question and reviewer specialty (N = 60)."
)
FIGURE1_STATS_CAPTION = (
    "Figure 1 supplemental statistics. Annotation harm scores and issue counts compared "
    "between PCP and hospitalist reviewers."
)
FIGURE1_SUMMARY_STATS_CAPTION = (
    "Figure 1 supplemental statistics. Annotation harm scores compared between "
    "human-authored and LLM-generated summaries."
)
FIGURE1_CAPTION = (
    "Figure 1. Heat map of physician reviewer annotated error counts and harm ratings "
    "by summary type. Each cell counts error annotations with the corresponding "
    "potential-severity and harm-likelihood ratings on the 0-7 scales."
)
FIGURE2_CAPTION = (
    "Figure 2. Scatterplot comparing mean survey ratings to length of stay for both "
    "human-authored and LLM-generated discharge summaries (n = 60). Individual "
    "values of n above each data point indicate the number of encounters available "
    "to calculate the average."
)
FIGURE3_CAPTION = (
    "Figure 3. Difference in LLM-generated vs. human-authored survey scores by "
    "provider type and survey question (n = 120). Outliers are shown as individual "
    "points but excluded from mean, IQR and range calculations."
)

SUMMARY_TYPE_DISPLAY = {
    "Human": "Human-Authored Summary",
    "AI": "LLM-Generated Summary",
}

TABLE_S6_METRIC_LABELS = {
    "Overall quality": "Quality",
    "Concise/readable": "Conciseness/Readability",
    "Factuality": "Factuality",
    "Completeness": "Completeness",
}

TABLE_S6_COLUMNS = (
    "Metric",
    "Mean score [SD] difference between LLM-generated vs. human-authored summary (PCPs)",
    "Mean score [SD] difference between LLM-generated vs. human-authored summary (Hospitalists)",
    "P Value",
)

FIGURE1_STATS_COLUMNS = (
    "Analysis",
    "Unit",
    "PCP n",
    "PCP mean",
    "PCP SD",
    "Hospitalist n",
    "Hospitalist mean",
    "Hospitalist SD",
    "Statistical test",
    "P value",
)

FIGURE1_SUMMARY_STATS_COLUMNS = (
    "Analysis",
    "Unit",
    "Human-authored n",
    "Human-authored mean",
    "Human-authored SD",
    "LLM-generated n",
    "LLM-generated mean",
    "LLM-generated SD",
    "Statistical test",
    "P value",
)


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values)


def _pvalue(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "NA"
    if value < 0.001:
        return f"{value:.2e}"
    return f"{value:.3f}"


def _load_likert() -> list[dict[str, str]]:
    path = DATA_DIR / "likert_data.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        required = {"encounter_id", "reviewer_role", "los_days"}
        for metric in METRICS:
            required.add(metric.human_col)
            required.add(metric.ai_col)
        missing = required.difference(fieldnames)
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(f"{path} is missing required columns: {missing_list}")
        return list(reader)


def _load_annotations() -> list[dict[str, str]]:
    path = DATA_DIR / "annotations_data.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        required = {
            "encounter_id",
            "reviewer_id",
            "reviewer_role",
            "summary_label",
            "issue_type",
            "harm_potential",
            "harm_likelihood",
        }
        missing = required.difference(fieldnames)
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(f"{path} is missing required columns: {missing_list}")
        return list(reader)


def _rating_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for metric in METRICS:
        values: list[tuple[float, float]] = []
        for row in rows:
            if metric.pcp_only and row["reviewer_role"].strip().lower() != "pcp":
                continue
            human = float(row[metric.human_col])
            ai = float(row[metric.ai_col])
            if 1 <= human <= 5 and 1 <= ai <= 5:
                values.append((human, ai))

        if not values:
            continue

        human_values = [human for human, _ in values]
        ai_values = [ai for _, ai in values]
        deltas = [ai - human for human, ai in values]
        p = 1.0 if all(delta == 0 for delta in deltas) else float(
            wilcoxon(ai_values, human_values, alternative="greater").pvalue
        )
        delta_mean = _mean(deltas)
        out.append(
            {
                "n": str(len(values)),
                "Question": metric.label,
                "Evaluators": "PCP" if metric.pcp_only else "Both",
                "Mean human-summary score": f"{_mean(human_values):.2f}",
                "Mean AI-summary score": f"{_mean(ai_values):.2f}",
                "Mean score difference": f"+{delta_mean:.2f}",
                "P value": _pvalue(p),
            }
        )
    return out


def _markdown_cell(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _markdown_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        evaluators = "PCPs" if row["Evaluators"] == "PCP" else "Hospitalists, PCPs"
        out.append(
            {
                "Question (n)": f"{row['Question']}<br> (n={row['n']})",
                "Evaluators": evaluators,
                "Human-Authored Summary Mean Likert Score": row["Mean human-summary score"],
                "LLM-Generated Summary Mean Likert Score": row["Mean AI-summary score"],
                "Mean Score Difference between LLM-Generated & Human-Authored Summaries": row[
                    "Mean score difference"
                ].removeprefix("+"),
                "P-Value": row["P value"].upper(),
            }
        )
    return out


def _write_markdown_table(path: Path, rows: list[dict[str, str]]) -> None:
    markdown_rows = _markdown_rows(rows)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("| " + " | ".join(_markdown_cell(column) for column in MARKDOWN_COLUMNS) + " |\n")
        handle.write("| " + " | ".join("---" for _ in MARKDOWN_COLUMNS) + " |\n")
        for row in markdown_rows:
            handle.write("| " + " | ".join(_markdown_cell(row[column]) for column in MARKDOWN_COLUMNS) + " |\n")
        handle.write(f"\n**{TABLE_CAPTION}**\n")


def _write_csv_and_markdown(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    _write_markdown_table(path.with_suffix(".md"), rows)


def _write_simple_csv(path: Path, columns: Iterable[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_simple_markdown_table(
    path: Path,
    columns: Iterable[str],
    rows: list[dict[str, str]],
    caption: str,
) -> None:
    columns = tuple(columns)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("| " + " | ".join(_markdown_cell(column) for column in columns) + " |\n")
        handle.write("| " + " | ".join("---" for _ in columns) + " |\n")
        for row in rows:
            handle.write("| " + " | ".join(_markdown_cell(row[column]) for column in columns) + " |\n")
        handle.write(f"\n**{caption}**\n")


def _write_simple_csv_and_markdown(
    path: Path,
    columns: Iterable[str],
    rows: list[dict[str, str]],
    caption: str,
) -> None:
    _write_simple_csv(path, columns, rows)
    _write_simple_markdown_table(path.with_suffix(".md"), columns, rows, caption)


def _set_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "axes.edgecolor": "#94A3B8",
            "axes.labelcolor": TEXT_COLOR,
            "xtick.color": TEXT_COLOR,
            "ytick.color": TEXT_COLOR,
            "text.color": TEXT_COLOR,
        }
    )


def _summary_type(summary_label: str) -> str:
    normalized = summary_label.strip().upper()
    if normalized == "A":
        return "Human"
    if normalized == "B":
        return "AI"
    lowered = summary_label.strip().lower()
    if lowered in {"human", "human summary", "human-authored summary"}:
        return "Human"
    if lowered in {"ai", "ai summary", "llm", "llm-generated summary"}:
        return "AI"
    raise ValueError(f"Unexpected annotation summary_label value: {summary_label!r}")


def _harm_score(row: dict[str, str], column: str) -> int:
    try:
        value = int(float(row[column]))
    except ValueError as exc:
        raise ValueError(f"Invalid {column} value in annotations_data.csv: {row[column]!r}") from exc
    if value < 0 or value > 7:
        raise ValueError(f"Expected {column} value from 0 through 7, got {value!r}")
    return value


def _plot_annotation_harm_distribution(rows: list[dict[str, str]], path: Path) -> None:
    _set_plot_style()
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.4), sharex=True, sharey=True)
    matrices: dict[str, np.ndarray] = {}
    annotation_counts: dict[str, int] = {}
    vmax = 1

    for summary_type in ("Human", "AI"):
        matrix = np.zeros((8, 8), dtype=int)
        subset = [row for row in rows if _summary_type(row["summary_label"]) == summary_type]
        annotation_counts[summary_type] = len(subset)
        for row in subset:
            potential = _harm_score(row, "harm_potential")
            likelihood = _harm_score(row, "harm_likelihood")
            matrix[potential, likelihood] += 1
        matrices[summary_type] = matrix
        vmax = max(vmax, int(matrix.max()))

    image = None
    for ax, summary_type in zip(axes, ("Human", "AI")):
        matrix = matrices[summary_type]
        masked = np.ma.masked_where(matrix == 0, matrix)
        image = ax.imshow(masked, origin="lower", cmap=BLUE_CMAP, vmin=1, vmax=vmax)
        for potential in range(8):
            for likelihood in range(8):
                value = int(matrix[potential, likelihood])
                if value:
                    ax.text(likelihood, potential, str(value), ha="center", va="center", fontsize=8)
        ax.set_title(f"{SUMMARY_TYPE_DISPLAY[summary_type]} (N={annotation_counts[summary_type]})")
        ax.set_xlabel("Likelihood of harm")
        ax.set_xticks(range(8))
        ax.set_yticks(range(8))
        ax.spines[["top", "right", "left", "bottom"]].set_visible(False)

    axes[0].set_ylabel("Potential severity")
    if image is not None:
        fig.colorbar(image, ax=axes.ravel().tolist(), shrink=0.82, label="Annotation count")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _format_stat(value: float, digits: int = 3) -> str:
    if math.isnan(value):
        return "NA"
    return f"{value:.{digits}f}"


def _annotation_harm_role_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for score_col, label in (
        ("harm_potential", "Harm potential score"),
        ("harm_likelihood", "Harm likelihood score"),
    ):
        values: dict[str, list[float]] = {"PCP": [], "Hospitalist": []}
        for row in rows:
            role = _reviewer_role(row["reviewer_role"])
            values[role].append(float(_harm_score(row, score_col)))
        pcp = values["PCP"]
        hospitalist = values["Hospitalist"]
        p = (
            float(mannwhitneyu(pcp, hospitalist, alternative="two-sided", method="asymptotic").pvalue)
            if pcp and hospitalist
            else math.nan
        )
        out.append(
            {
                "Analysis": label,
                "Unit": "Annotation",
                "PCP n": str(len(pcp)),
                "PCP mean": _format_stat(_mean(pcp), 2),
                "PCP SD": _format_stat(_sd(pcp), 2),
                "Hospitalist n": str(len(hospitalist)),
                "Hospitalist mean": _format_stat(_mean(hospitalist), 2),
                "Hospitalist SD": _format_stat(_sd(hospitalist), 2),
                "Statistical test": "Mann-Whitney U, two-sided",
                "P value": _pvalue(p),
            }
        )
    return out


def _annotation_harm_summary_type_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for score_col, label in (
        ("harm_potential", "Harm potential score"),
        ("harm_likelihood", "Harm likelihood score"),
    ):
        values: dict[str, list[float]] = {"Human": [], "AI": []}
        for row in rows:
            summary_type = _summary_type(row["summary_label"])
            values[summary_type].append(float(_harm_score(row, score_col)))
        human = values["Human"]
        ai = values["AI"]
        p = (
            float(mannwhitneyu(human, ai, alternative="two-sided", method="asymptotic").pvalue)
            if human and ai
            else math.nan
        )
        out.append(
            {
                "Analysis": label,
                "Unit": "Annotation",
                "Human-authored n": str(len(human)),
                "Human-authored mean": _format_stat(_mean(human), 2),
                "Human-authored SD": _format_stat(_sd(human), 2),
                "LLM-generated n": str(len(ai)),
                "LLM-generated mean": _format_stat(_mean(ai), 2),
                "LLM-generated SD": _format_stat(_sd(ai), 2),
                "Statistical test": "Mann-Whitney U, two-sided",
                "P value": _pvalue(p),
            }
        )
    return out


def _annotation_issue_count_role_rows(
    annotation_rows: list[dict[str, str]],
    likert_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    review_index: dict[str, dict[str, str]] = {}
    for row in likert_rows:
        review_index.setdefault(row["encounter_id"], {})[_reviewer_role(row["reviewer_role"])] = row["reviewer_id"]

    annotation_counts: dict[tuple[str, str, str], int] = {}
    for row in annotation_rows:
        issue_type = row["issue_type"].strip().lower()
        if issue_type not in {"inaccuracy", "omission"}:
            continue
        key = (row["encounter_id"], row["reviewer_id"], issue_type)
        annotation_counts[key] = annotation_counts.get(key, 0) + 1

    out: list[dict[str, str]] = []
    for issue_type, label in (("inaccuracy", "Inaccuracy count"), ("omission", "Omission count")):
        pcp_counts: list[float] = []
        hospitalist_counts: list[float] = []
        for encounter_id in sorted(review_index, key=lambda value: int(float(value))):
            reviewers = review_index[encounter_id]
            if "PCP" not in reviewers or "Hospitalist" not in reviewers:
                continue
            pcp_counts.append(float(annotation_counts.get((encounter_id, reviewers["PCP"], issue_type), 0)))
            hospitalist_counts.append(
                float(annotation_counts.get((encounter_id, reviewers["Hospitalist"], issue_type), 0))
            )

        differences = [pcp - hospitalist for pcp, hospitalist in zip(pcp_counts, hospitalist_counts)]
        p = 1.0 if all(abs(difference) < 1e-12 for difference in differences) else float(
            wilcoxon(pcp_counts, hospitalist_counts, alternative="two-sided", zero_method="wilcox").pvalue
        )
        out.append(
            {
                "Analysis": label,
                "Unit": "Encounter-review",
                "PCP n": str(len(pcp_counts)),
                "PCP mean": _format_stat(_mean(pcp_counts), 3),
                "PCP SD": _format_stat(_sd(pcp_counts), 3),
                "Hospitalist n": str(len(hospitalist_counts)),
                "Hospitalist mean": _format_stat(_mean(hospitalist_counts), 3),
                "Hospitalist SD": _format_stat(_sd(hospitalist_counts), 3),
                "Statistical test": "Wilcoxon signed-rank, two-sided",
                "P value": _pvalue(p),
            }
        )
    return out


def _annotation_role_stat_rows(
    annotation_rows: list[dict[str, str]],
    likert_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    return _annotation_harm_role_rows(annotation_rows) + _annotation_issue_count_role_rows(
        annotation_rows,
        likert_rows,
    )


def _valid_rating(value: str) -> float | None:
    try:
        rating = float(value)
    except ValueError:
        return None
    if 1 <= rating <= 5:
        return rating
    return None


def _los_rating_summary(rows: list[dict[str, str]]) -> list[dict[str, float | int | str]]:
    by_los: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        try:
            los = int(float(row["los_days"]))
        except ValueError as exc:
            raise ValueError(f"Invalid los_days value in likert_data.csv: {row['los_days']!r}") from exc
        by_los.setdefault(los, []).append(row)

    out: list[dict[str, float | int | str]] = []
    for los in sorted(by_los):
        group = by_los[los]
        encounter_n = len({row["encounter_id"] for row in group})
        for summary_type, columns in (
            ("Human", [metric.human_col for metric in SHARED_METRICS]),
            ("AI", [metric.ai_col for metric in SHARED_METRICS]),
        ):
            values: list[float] = []
            for row in group:
                for column in columns:
                    rating = _valid_rating(row[column])
                    if rating is not None:
                        values.append(rating)
            if values:
                out.append(
                    {
                        "los": los,
                        "summary_type": summary_type,
                        "encounter_n": encounter_n,
                        "review_n": len(group),
                        "mean_likert_rating": _mean(values),
                    }
                )
    return out


def _los_spearman_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for summary_type, columns in (
        ("Human", [metric.human_col for metric in SHARED_METRICS]),
        ("AI", [metric.ai_col for metric in SHARED_METRICS]),
    ):
        encounter_values: dict[str, dict[str, int | list[float]]] = {}
        for row in rows:
            ratings = [rating for column in columns if (rating := _valid_rating(row[column])) is not None]
            if not ratings:
                continue
            try:
                los = int(float(row["los_days"]))
            except ValueError as exc:
                raise ValueError(f"Invalid los_days value in likert_data.csv: {row['los_days']!r}") from exc
            entry = encounter_values.setdefault(row["encounter_id"], {"los": los, "review_means": []})
            entry["review_means"].append(_mean(ratings))  # type: ignore[union-attr]

        los_values = [float(entry["los"]) for entry in encounter_values.values()]
        mean_values = [_mean(entry["review_means"]) for entry in encounter_values.values()]  # type: ignore[arg-type]
        rho, pvalue = spearmanr(los_values, mean_values) if len(encounter_values) >= 2 else (math.nan, math.nan)
        review_summary_n = sum(len(entry["review_means"]) for entry in encounter_values.values())  # type: ignore[arg-type]
        out.append(
            {
                "Summary type": SUMMARY_TYPE_DISPLAY[summary_type],
                "n": str(len(encounter_values)),
                "Review summaries": str(review_summary_n),
                "Spearman rho": "NA" if math.isnan(float(rho)) else f"{float(rho):.3f}",
                "P value": _pvalue(float(pvalue)),
            }
        )
    return out


def _los_spearman_markdown(rows: list[dict[str, str]]) -> str:
    stats = _los_spearman_rows(rows)
    columns = ("Summary type", "n", "Review summaries", "Spearman rho", "P value")
    lines = [
        "",
        "Length-of-stay association tests use two-sided Spearman rank correlation at the encounter level.",
        "",
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in stats:
        lines.append("| " + " | ".join(_markdown_cell(row[column]) for column in columns) + " |")
    return "\n".join(lines) + "\n"


def _plot_los_shared_rating_trends(rows: list[dict[str, str]], path: Path) -> None:
    _set_plot_style()
    summary = _los_rating_summary(rows)
    fig, ax = plt.subplots(figsize=(8.6, 4.8))

    for summary_type, color in (("Human", HUMAN_COLOR), ("AI", AI_COLOR)):
        subset = [row for row in summary if row["summary_type"] == summary_type]
        if not subset:
            continue
        x = np.array([float(row["los"]) for row in subset])
        y = np.array([float(row["mean_likert_rating"]) for row in subset])
        encounter_n = np.array([int(row["encounter_n"]) for row in subset])
        review_n = np.array([int(row["review_n"]) for row in subset])
        label = SUMMARY_TYPE_DISPLAY[summary_type]
        ax.scatter(
            x,
            y,
            s=encounter_n * 28,
            color=color,
            alpha=0.65,
            label=label,
        )
        for row in subset:
            ax.annotate(
                f"n={int(row['encounter_n'])}",
                xy=(float(row["los"]), float(row["mean_likert_rating"])),
                xytext=(0, 5),
                textcoords="offset points",
                color=color,
                fontsize=6.2,
                ha="center",
                va="bottom",
                alpha=0.95,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.72, "pad": 0.35},
            )
        if len(set(x.tolist())) > 1:
            weights = np.sqrt(review_n.astype(float))
            slope, intercept = np.polyfit(x, y, deg=1, w=weights)
            trend_x = np.linspace(float(x.min()), float(x.max()), 100)
            ax.plot(
                trend_x,
                slope * trend_x + intercept,
                color=color,
                linestyle="--",
                linewidth=1.4,
                alpha=0.85,
                label=f"{label} trend",
            )

    ax.set_xlabel("Length of stay (days)")
    ax.set_ylabel("Mean Likert rating (1-5)")
    ax.set_ylim(1, 5.25)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300)
    plt.close(fig)


def _reviewer_role(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "pcp":
        return "PCP"
    if normalized in {"hospitalist", "hospital", "hosp"}:
        return "Hospitalist"
    raise ValueError(f"Unexpected reviewer_role value in likert_data.csv: {value!r}")


def _sd(values: list[float]) -> float:
    return float(np.std(np.array(values, dtype=float), ddof=1)) if len(values) >= 2 else math.nan


def _format_mean_sd(values: list[float]) -> str:
    return f"{_mean(values):.2f} [{_sd(values):.2f}]"


def _table_s6_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for metric in SHARED_METRICS:
        deltas_by_encounter: dict[str, dict[str, float]] = {}
        for row in rows:
            role = _reviewer_role(row["reviewer_role"])
            human = _valid_rating(row[metric.human_col])
            ai = _valid_rating(row[metric.ai_col])
            if human is None or ai is None:
                continue
            deltas_by_encounter.setdefault(row["encounter_id"], {})[role] = ai - human

        paired = [
            role_deltas
            for role_deltas in deltas_by_encounter.values()
            if "PCP" in role_deltas and "Hospitalist" in role_deltas
        ]
        pcp = [role_deltas["PCP"] for role_deltas in paired]
        hospitalist = [role_deltas["Hospitalist"] for role_deltas in paired]
        differences = [pcp_delta - hospitalist_delta for pcp_delta, hospitalist_delta in zip(pcp, hospitalist)]
        p = 1.0 if all(abs(difference) < 1e-12 for difference in differences) else float(
            wilcoxon(pcp, hospitalist, alternative="greater").pvalue
        )
        out.append(
            {
                "Metric": TABLE_S6_METRIC_LABELS[metric.label],
                "Mean score [SD] difference between LLM-generated vs. human-authored summary (PCPs)": _format_mean_sd(
                    pcp
                ),
                "Mean score [SD] difference between LLM-generated vs. human-authored summary (Hospitalists)": _format_mean_sd(
                    hospitalist
                ),
                "P Value": f"{p:.4f}",
            }
        )
    return out


def _boxplot_stats(values: list[float]) -> dict[str, float | list[float]]:
    data = np.array(values, dtype=float)
    if data.size == 0:
        return {"mean": math.nan, "med": math.nan, "q1": math.nan, "q3": math.nan, "whislo": math.nan, "whishi": math.nan, "fliers": []}

    q1, q3 = np.percentile(data, [25, 75])
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    non_outliers = data[(data >= lower) & (data <= upper)]
    fliers = data[(data < lower) | (data > upper)]
    if non_outliers.size == 0:
        non_outliers = data
        fliers = np.array([], dtype=float)

    clean_q1, clean_q3 = np.percentile(non_outliers, [25, 75])
    return {
        "mean": float(non_outliers.mean()),
        "med": float(np.median(non_outliers)),
        "q1": float(clean_q1),
        "q3": float(clean_q3),
        "whislo": float(non_outliers.min()),
        "whishi": float(non_outliers.max()),
        "fliers": [float(value) for value in fliers],
    }


def _plot_role_delta_shared(rows: list[dict[str, str]], path: Path) -> None:
    _set_plot_style()
    series_by_role: dict[str, list[list[float]]] = {"Hospitalist": [], "PCP": []}

    for metric in SHARED_METRICS:
        by_role: dict[str, list[float]] = {"Hospitalist": [], "PCP": []}
        for row in rows:
            human = _valid_rating(row[metric.human_col])
            ai = _valid_rating(row[metric.ai_col])
            if human is None or ai is None:
                continue
            by_role[_reviewer_role(row["reviewer_role"])].append(ai - human)
        for role in ("Hospitalist", "PCP"):
            series_by_role[role].append(by_role[role])

    xticklabels = [metric.label for metric in SHARED_METRICS]
    x = np.arange(len(xticklabels))
    fig, ax = plt.subplots(figsize=(8.6, 4.8))
    box_width = 0.28
    positions = {
        "Hospitalist": x - box_width / 1.6,
        "PCP": x + box_width / 1.6,
    }

    for role, color in (("Hospitalist", HOSPITALIST_COLOR), ("PCP", PCP_COLOR)):
        stats = [_boxplot_stats(values) for values in series_by_role[role]]
        box = ax.bxp(
            stats,
            positions=positions[role],
            widths=box_width,
            patch_artist=True,
            manage_ticks=False,
            showmeans=True,
            meanline=True,
            showfliers=True,
            boxprops={"facecolor": color, "edgecolor": color, "alpha": 0.68},
            meanprops={"color": "white", "linewidth": 1.7, "linestyle": "-"},
            medianprops={"color": "none", "linewidth": 0},
            whiskerprops={"color": color, "linewidth": 1.2},
            capprops={"color": color, "linewidth": 1.2},
            flierprops={
                "marker": "o",
                "markerfacecolor": color,
                "markeredgecolor": color,
                "markersize": 3.2,
                "alpha": 0.42,
            },
        )
        for mean in box["means"]:
            mean.set_zorder(3)

    all_values = [value for series_list in series_by_role.values() for series in series_list for value in series]
    y_min = min(all_values) if all_values else -2
    y_max = max(all_values) if all_values else 4
    ax.axhline(0, color=GRID_COLOR, linewidth=0.9, zorder=0)
    ax.set_ylabel("Difference in LLM-Generated vs.\nHuman-Authored Summary Survey Scores")
    ax.set_xticks(x)
    ax.set_xticklabels(xticklabels, rotation=20, ha="right")
    ax.set_ylim(min(-2.35, y_min - 0.35), max(4.35, y_max + 0.35))
    ax.legend(
        handles=[
            plt.Rectangle((0, 0), 1, 1, facecolor=HOSPITALIST_COLOR, edgecolor=HOSPITALIST_COLOR, alpha=0.68, label="Hospitalist"),
            plt.Rectangle((0, 0), 1, 1, facecolor=PCP_COLOR, edgecolor=PCP_COLOR, alpha=0.68, label="PCP"),
        ],
        frameon=False,
    )
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300)
    plt.close(fig)


def _write_figure_markdown(image_path: Path, caption: str, extra_markdown: str = "") -> None:
    markdown_path = image_path.with_suffix(".md")
    with markdown_path.open("w", encoding="utf-8") as handle:
        handle.write(f"![{caption}]({image_path.name})\n\n")
        handle.write(f"**{caption}**\n")
        if extra_markdown:
            handle.write(extra_markdown)


def main() -> None:
    likert_rows = _load_likert()
    annotation_rows = _load_annotations()
    rows = _rating_rows(likert_rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv_and_markdown(TABLE1_OUTPUT_PATH, rows)
    print(f"Wrote {len(rows)} rows to {TABLE1_OUTPUT_PATH}")
    print(f"Wrote Markdown table to {TABLE1_OUTPUT_PATH.with_suffix('.md')}")
    table_s6_rows = _table_s6_rows(likert_rows)
    _write_simple_csv_and_markdown(TABLE_S6_OUTPUT_PATH, TABLE_S6_COLUMNS, table_s6_rows, TABLE_S6_CAPTION)
    print(f"Wrote {len(table_s6_rows)} rows to {TABLE_S6_OUTPUT_PATH}")
    print(f"Wrote Markdown table to {TABLE_S6_OUTPUT_PATH.with_suffix('.md')}")
    figure1_stats_rows = _annotation_role_stat_rows(annotation_rows, likert_rows)
    _write_simple_csv_and_markdown(
        FIG1_STATS_OUTPUT_PATH,
        FIGURE1_STATS_COLUMNS,
        figure1_stats_rows,
        FIGURE1_STATS_CAPTION,
    )
    print(f"Wrote {len(figure1_stats_rows)} rows to {FIG1_STATS_OUTPUT_PATH}")
    print(f"Wrote Markdown table to {FIG1_STATS_OUTPUT_PATH.with_suffix('.md')}")
    figure1_summary_stats_rows = _annotation_harm_summary_type_rows(annotation_rows)
    _write_simple_csv_and_markdown(
        FIG1_SUMMARY_STATS_OUTPUT_PATH,
        FIGURE1_SUMMARY_STATS_COLUMNS,
        figure1_summary_stats_rows,
        FIGURE1_SUMMARY_STATS_CAPTION,
    )
    print(f"Wrote {len(figure1_summary_stats_rows)} rows to {FIG1_SUMMARY_STATS_OUTPUT_PATH}")
    print(f"Wrote Markdown table to {FIG1_SUMMARY_STATS_OUTPUT_PATH.with_suffix('.md')}")
    _plot_annotation_harm_distribution(annotation_rows, FIG1_OUTPUT_PATH)
    _write_figure_markdown(FIG1_OUTPUT_PATH, FIGURE1_CAPTION)
    print(f"Wrote Figure 1 to {FIG1_OUTPUT_PATH}")
    print(f"Wrote Figure 1 Markdown to {FIG1_OUTPUT_PATH.with_suffix('.md')}")
    _plot_los_shared_rating_trends(likert_rows, FIG2_OUTPUT_PATH)
    _write_figure_markdown(FIG2_OUTPUT_PATH, FIGURE2_CAPTION, _los_spearman_markdown(likert_rows))
    print(f"Wrote Figure 2 to {FIG2_OUTPUT_PATH}")
    print(f"Wrote Figure 2 Markdown to {FIG2_OUTPUT_PATH.with_suffix('.md')}")
    _plot_role_delta_shared(likert_rows, FIG3_OUTPUT_PATH)
    _write_figure_markdown(FIG3_OUTPUT_PATH, FIGURE3_CAPTION)
    print(f"Wrote Figure 3 to {FIG3_OUTPUT_PATH}")
    print(f"Wrote Figure 3 Markdown to {FIG3_OUTPUT_PATH.with_suffix('.md')}")


if __name__ == "__main__":
    main()
