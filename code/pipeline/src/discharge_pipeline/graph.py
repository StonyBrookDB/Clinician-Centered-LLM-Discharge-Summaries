"""LangGraph workflows for summarization and downstream formatting."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, TypedDict

from langgraph.graph import END, START, StateGraph

from .models import NoteChunk, TokenUsage
from .prompt_parsing import parse_tagged_prompt, render_template


REFINE_TEMPLATE = """
Add to the summary based on the next batch of clinical notes.

Existing summary up to this point:
{existing_answer}

Next batch:
------------
{context}
------------

Given the new context, add to and/or refine the original summary. Do not use markdown formatting; plaintext only. Maintain the same structure, including the same sections with HTML-like tags, as the original prompt asked for. The entire summary must be enclosed in <summary> </summary> tags. Each section must be enclosed in HTML-like tags (<basic_info>, <hospital_course>, <discharge_instructions>, <medication_list>, <medication_changes>, <incidental_findings>), and each bullet point within sections must be enclosed in <bullet> </bullet> tags with <source> </source> tags around the comma-separated list of source IDs. Leave the <incidental_findings> section empty; it will be populated later in the pipeline.
"""

def load_prompt(prompt_dir: Path, filename: str) -> str:
    return (prompt_dir / filename).read_text(encoding="utf-8")


def _split_prompt(prompt_text: str) -> Tuple[str, str]:
    sections = parse_tagged_prompt(
        prompt_text,
        tags=("instructions", "output_formatting", "context"),
    )
    return f"{sections['instructions']}\n\n{sections['output_formatting']}".strip(), sections["context"].strip()


class SummaryState(TypedDict):
    contents: List[str]
    index: int
    summary: str


async def generate_structured_summary(
    chunks: List[NoteChunk],
    llm: Any,
    prompt_dir: Path,
) -> Tuple[str, List[str], TokenUsage]:
    """Generate an iterative structured summary over chronological chunks."""

    if not chunks:
        return "", [], TokenUsage()

    system_prompt = load_prompt(prompt_dir, "prompt.txt")
    initial_human = (
        "The first batch of clinical notes follows. Generate the initial structured discharge summary using the instructions above.\n\n"
        "{context}"
    )
    usage = TokenUsage()
    drafts: List[str] = []

    async def generate_initial(state: SummaryState) -> Dict[str, Any]:
        result = await llm.acomplete(system_prompt, render_template(initial_human, {"context": state["contents"][0]}))
        usage.add_from(result)
        return {"summary": result.content, "index": 1}

    async def refine(state: SummaryState) -> Dict[str, Any]:
        context = state["contents"][state["index"]]
        human = render_template(
            refine_template,
            {
                "existing_answer": state["summary"],
                "context": context,
            },
        )
        result = await llm.acomplete(system_prompt, human)
        usage.add_from(result)
        return {"summary": result.content, "index": state["index"] + 1}

    def should_continue(state: SummaryState) -> str:
        if state["index"] >= len(state["contents"]):
            return END
        return "refine"

    graph = StateGraph(SummaryState)
    graph.add_node("generate_initial", generate_initial)
    graph.add_node("refine", refine)
    graph.add_edge(START, "generate_initial")
    graph.add_conditional_edges("generate_initial", should_continue)
    graph.add_conditional_edges("refine", should_continue)
    app = graph.compile()

    async for step in app.astream(
        {"contents": [chunk.chunk_text for chunk in chunks], "index": 0, "summary": ""},
        stream_mode="values",
    ):
        if step.get("summary"):
            drafts.append(step["summary"])

    return (drafts[-1] if drafts else ""), drafts, usage


class IncidentalState(TypedDict):
    contents: List[str]
    index: int
    incidental: str


async def generate_incidental_findings(
    structured_summary: str,
    incidental_chunks: List[NoteChunk],
    llm: Any,
    prompt_dir: Path,
) -> Tuple[str, TokenUsage]:
    """Generate/refine incidental findings from summary plus flagged notes."""

    contents = [structured_summary] + [chunk.chunk_text for chunk in incidental_chunks]
    if not structured_summary.strip():
        return "<incidental_findings>\n</incidental_findings>", TokenUsage()

    initial_system, initial_human = _split_prompt(load_prompt(prompt_dir, "incidental_findings_prompt.txt"))
    refine_system, refine_human = _split_prompt(load_prompt(prompt_dir, "incidental_findings_refine_prompt.txt"))
    usage = TokenUsage()
    output_holder = {"incidental": ""}

    async def generate_initial(state: IncidentalState) -> Dict[str, Any]:
        result = await llm.acomplete(
            initial_system,
            render_template(initial_human, {"discharge_summary": state["contents"][0]}),
        )
        usage.add_from(result)
        return {"incidental": result.content, "index": 1}

    async def refine(state: IncidentalState) -> Dict[str, Any]:
        result = await llm.acomplete(
            refine_system,
            render_template(
                refine_human,
                {
                    "discharge_summary": structured_summary,
                    "existing_incidentals": state["incidental"],
                    "context": state["contents"][state["index"]],
                },
            ),
        )
        usage.add_from(result)
        return {"incidental": result.content, "index": state["index"] + 1}

    def should_continue(state: IncidentalState) -> str:
        if state["index"] >= len(state["contents"]):
            return END
        return "refine"

    graph = StateGraph(IncidentalState)
    graph.add_node("generate_initial", generate_initial)
    graph.add_node("refine", refine)
    graph.add_edge(START, "generate_initial")
    graph.add_conditional_edges("generate_initial", should_continue)
    graph.add_conditional_edges("refine", should_continue)
    app = graph.compile()

    async for step in app.astream(
        {"contents": contents, "index": 0, "incidental": ""},
        stream_mode="values",
    ):
        if step.get("incidental"):
            output_holder["incidental"] = step["incidental"]

    incidental_text = output_holder["incidental"].strip()
    if not incidental_text:
        incidental_text = "<incidental_findings>\n</incidental_findings>"
    if "<incidental_findings" not in incidental_text.lower():
        incidental_text = f"<incidental_findings>\n{incidental_text}\n</incidental_findings>"
    return incidental_text, usage


async def format_narrative(
    structured_summary: str,
    llm: Any,
    prompt_dir: Path,
) -> Tuple[str, TokenUsage]:
    """Convert structured bullets to narrative text."""

    system, human_template = _split_prompt(load_prompt(prompt_dir, "final_narrative_prompt.txt"))
    result = await llm.acomplete(
        system,
        render_template(human_template, {"bulleted_summary": structured_summary}),
    )
    narrative = re.sub(r"</?(?:one_liner_items|narrative_items)>", "", result.content, flags=re.IGNORECASE).strip()
    usage = TokenUsage()
    usage.add_from(result)
    return narrative, usage


def run_async(coro):
    """Run an async graph from sync CLI code."""

    return asyncio.run(coro)
