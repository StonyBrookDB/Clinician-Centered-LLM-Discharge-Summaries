"""Parsing and citation helpers for structured summaries."""

from __future__ import annotations

import re
from typing import Any, Dict, List


SECTION_PATTERNS = {
    "basic_info": r"<basic_info>(.*?)</basic_info>",
    "hospital_course": r"<hospital_course>(.*?)</hospital_course>",
    "discharge_instructions": r"<discharge_instructions>(.*?)</discharge_instructions>",
    "medication_list": r"<medication_list>(.*?)</medication_list>",
    "medication_changes": r"<medication_changes>(.*?)</medication_changes>",
    "incidental_findings": r"<incidental_findings>(.*?)</incidental_findings>",
}


def parse_bullets(section_content: str) -> List[Dict[str, Any]]:
    """Parse <bullet> elements and source citations."""

    bullets: List[Dict[str, Any]] = []
    for bullet_content in re.findall(r"<bullet>(.*?)</bullet>", section_content or "", re.DOTALL | re.IGNORECASE):
        source_match = re.search(r"<source>(.*?)</source>", bullet_content, re.DOTALL | re.IGNORECASE)
        sources: List[str] = []
        if source_match:
            sources = [
                item.strip()
                for item in source_match.group(1).replace("\n", ",").split(",")
                if item.strip()
            ]
        text = re.sub(r"<source>.*?</source>", "", bullet_content, flags=re.DOTALL | re.IGNORECASE).strip()
        bullets.append({"text": text, "sources": sources})
    return bullets


def parse_summary_sections(summary_text: str) -> Dict[str, Any]:
    """Parse the XML-like summary into JSON-friendly sections."""

    summary_match = re.search(r"<summary>(.*?)</summary>", summary_text or "", re.DOTALL | re.IGNORECASE)
    content = summary_match.group(1) if summary_match else (summary_text or "")
    parsed: Dict[str, Any] = {}
    for section_name, pattern in SECTION_PATTERNS.items():
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        parsed[section_name] = parse_bullets(match.group(1) if match else "")
    return parsed


def merge_incidental_into_summary(summary: str, incidental_block: str) -> str:
    """Replace or append the incidental findings section."""

    if not incidental_block.strip():
        incidental_block = "<incidental_findings>\n</incidental_findings>"
    pattern = re.compile(r"<incidental_findings>.*?</incidental_findings>", re.DOTALL | re.IGNORECASE)
    if pattern.search(summary or ""):
        return pattern.sub(incidental_block, summary)
    return (summary or "").rstrip() + "\n" + incidental_block


def build_citations(parsed_summary: Dict[str, Any], source_metadata: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Create a citation map without exposing original filenames."""

    cited = set()
    by_section: Dict[str, List[str]] = {}
    for section, bullets in parsed_summary.items():
        section_sources: List[str] = []
        if isinstance(bullets, list):
            for bullet in bullets:
                for source_id in bullet.get("sources", []):
                    cited.add(source_id)
                    section_sources.append(source_id)
        by_section[section] = sorted(set(section_sources))
    return {
        "sources": {source_id: source_metadata.get(source_id, {"source_id": source_id}) for source_id in sorted(cited)},
        "by_section": by_section,
    }

