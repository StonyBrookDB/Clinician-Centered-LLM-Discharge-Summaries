"""LLM adapters for live OpenAI use and offline deterministic tests."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Protocol

from .models import LLMResult


class LLMClient(Protocol):
    model_name: str

    async def acomplete(self, system: str, human: str) -> LLMResult:
        """Return a completion for the supplied system/human messages."""


@dataclass
class OpenAILLMClient:
    """Generic OpenAI chat model through LangChain."""

    model_name: str
    temperature: float = 0.2

    def __post_init__(self) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required unless --mock-llm is used.")
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI

        self._human_message = HumanMessage
        self._system_message = SystemMessage
        self._llm = ChatOpenAI(model=self.model_name, temperature=self.temperature)

    async def acomplete(self, system: str, human: str) -> LLMResult:
        response = await self._llm.ainvoke(
            [self._system_message(content=system), self._human_message(content=human)]
        )
        usage = getattr(response, "usage_metadata", None) or {}
        return LLMResult(
            content=getattr(response, "content", str(response)),
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
        )


@dataclass
class MockLLMClient:
    """Deterministic local model used for tests and offline demos."""

    model_name: str = "mock-llm"

    async def acomplete(self, system: str, human: str) -> LLMResult:
        lower = f"{system}\n{human}".lower()
        source_ids = _extract_source_ids(human) or ["src_demo"]
        primary_source = source_ids[0]
        last_source = source_ids[-1]

        human_lower = human.lower()
        system_lower = system.lower()

        if "structured summary appears below:" in human_lower:
            content = (
                "Synthetic adult patient admitted for chest discomfort and observed "
                "with improvement. Discharge planning included medication review, "
                "follow-up, and attention to incidental imaging findings."
            )
        elif (
            "existing incidental" in human_lower
            or ("discharge summary:" in human_lower and "radiology" in system_lower and "incidental" in system_lower)
        ):
            content = (
                "<incidental_findings>\n"
                f"<bullet>Small synthetic pulmonary nodule noted on imaging. "
                f"<source>{last_source}</source></bullet>\n"
                "</incidental_findings>"
            )
        elif "planned updates" in lower or "intended_changes" in lower:
            content = f"Add concise updates supported by {last_source}."
        else:
            joined_sources = ", ".join(source_ids[:3])
            content = (
                "<summary>\n"
                "<basic_info>\n"
                f"<bullet>Synthetic adult patient admitted for chest discomfort. <source>{primary_source}</source></bullet>\n"
                "</basic_info>\n"
                "<hospital_course>\n"
                f"<bullet>Symptoms improved with observation and supportive care. <source>{joined_sources}</source></bullet>\n"
                "</hospital_course>\n"
                "<discharge_instructions>\n"
                f"<bullet>Follow up with primary care after discharge. <source>{last_source}</source></bullet>\n"
                "</discharge_instructions>\n"
                "<medication_list>\n"
                f"<bullet>Continue home medication list as clinically appropriate. <source>{primary_source}</source></bullet>\n"
                "</medication_list>\n"
                "<medication_changes>\n"
                f"<bullet>No synthetic medication changes were identified. <source>{last_source}</source></bullet>\n"
                "</medication_changes>\n"
                "<incidental_findings>\n"
                "</incidental_findings>\n"
                "</summary>"
            )
        return LLMResult(
            content=content,
            input_tokens=max(1, len(system.split()) + len(human.split())),
            output_tokens=max(1, len(content.split())),
        )


def _extract_source_ids(text: str) -> list[str]:
    source_ids = re.findall(r"<source_id>(.*?)</source_id>", text, flags=re.IGNORECASE | re.DOTALL)
    source_ids.extend(re.findall(r"<file_name>(.*?)</file_name>", text, flags=re.IGNORECASE | re.DOTALL))
    return list(dict.fromkeys(source_ids))
