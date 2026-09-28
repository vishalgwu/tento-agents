"""Integrity and boundary coverage for the human-authored injection corpus."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Final, TypedDict, cast

import pytest

from brain.guardrails.injection import (
    AgentCapability,
    PromptContext,
    PromptContextError,
    PromptInjectionPattern,
    prepare_prompt_values,
    scan_prompt_injection,
)


class InjectionCase(TypedDict):
    """The fixed JSONL contract for one adversarial ingress attempt."""

    id: str
    entry_point: str
    content: str
    expected_patterns: list[str]


_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
_DATASET_PATH: Final = _REPOSITORY_ROOT / "evals" / "datasets" / "injection_v1.jsonl"
_ENTRY_POINTS: Final = frozenset(
    {
        "resident_text",
        "vendor_sms_reply",
        "pdf_text_layer",
        "image_caption",
        "marketplace_listing",
    }
)
_REQUIRED_KEYS: Final = frozenset({"id", "entry_point", "content", "expected_patterns"})


def _load_cases() -> tuple[InjectionCase, ...]:
    cases: list[InjectionCase] = []
    for line_number, raw_line in enumerate(
        _DATASET_PATH.read_text(encoding="utf-8").splitlines(), start=1
    ):
        assert raw_line.strip(), f"line {line_number} must not be blank"
        decoded = cast(dict[str, object], json.loads(raw_line))
        assert set(decoded) == _REQUIRED_KEYS, (
            f"line {line_number} has an invalid schema"
        )
        identifier = decoded["id"]
        entry_point = decoded["entry_point"]
        content = decoded["content"]
        expected_patterns = decoded["expected_patterns"]
        assert isinstance(identifier, str) and identifier
        assert entry_point in _ENTRY_POINTS
        assert isinstance(content, str) and content.strip()
        assert isinstance(expected_patterns, list) and all(
            isinstance(pattern, str)
            and pattern in {candidate.value for candidate in PromptInjectionPattern}
            for pattern in expected_patterns
        )
        assert len(expected_patterns) == len(set(expected_patterns))
        cases.append(
            {
                "id": identifier,
                "entry_point": entry_point,
                "content": content,
                "expected_patterns": cast(list[str], expected_patterns),
            }
        )
    return tuple(cases)


def test_injection_dataset_covers_all_ingress_paths_with_stable_attempts() -> None:
    cases = _load_cases()

    assert len(cases) == 40
    assert [case["id"] for case in cases] == [
        f"injection-{number:03d}" for number in range(1, 41)
    ]
    assert Counter(case["entry_point"] for case in cases) == {
        entry_point: 8 for entry_point in _ENTRY_POINTS
    }
    assert len({case["content"] for case in cases}) == len(cases)
    assert sum(not case["expected_patterns"] for case in cases) == 5


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["id"])
def test_every_untrusted_ingress_is_labelled_and_cannot_reach_write_tools(
    case: InjectionCase,
) -> None:
    context = PromptContext.from_untrusted(
        {"content": case["content"]},
        source=case["entry_point"],
        capability=AgentCapability.NO_WRITE_TOOLS,
    )

    prepared = prepare_prompt_values(context)["content"]
    assert isinstance(prepared, str)
    assert prepared.startswith(f'<untrusted_content source="{case["entry_point"]}" ')
    assert prepared.endswith("\n</untrusted_content>")
    assert tuple(
        pattern.value for pattern in scan_prompt_injection(case["content"]).patterns
    ) == tuple(case["expected_patterns"])

    with pytest.raises(PromptContextError, match="write tools"):
        prepare_prompt_values(
            PromptContext.from_untrusted(
                {"content": case["content"]},
                source=case["entry_point"],
                capability=AgentCapability.WRITE_TOOLS,
            )
        )
