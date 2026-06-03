"""Helpers for tagged prompt assets."""

from __future__ import annotations

import re
from typing import Dict, Iterable


def parse_tagged_prompt(prompt_text: str, tags: Iterable[str]) -> Dict[str, str]:
    """Extract named XML-like sections from a prompt file."""

    results: Dict[str, str] = {}
    for tag in tags:
        pattern = re.compile(
            rf"<{re.escape(tag)}>(.*?)</{re.escape(tag)}>",
            flags=re.DOTALL | re.IGNORECASE,
        )
        match = pattern.search(prompt_text)
        if not match:
            raise ValueError(f"Prompt missing <{tag}> section.")
        results[tag] = match.group(1).strip()
    return results


def render_template(template: str, values: Dict[str, object]) -> str:
    """Render only known brace placeholders, leaving all other braces untouched."""

    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered
