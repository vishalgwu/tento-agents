"""Opt-in, bounded live benchmark of the application's actual intake gateway.

No production DB access or mutations. Synthetic text remains local; reports
contain identifiers and measurements, never prompts, outputs or credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import subprocess
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from typing import cast

from dotenv import load_dotenv
from openai import AsyncOpenAI

from brain.agents.intake import IntakeRequest, normalize_intake
from brain.gateway.client import (
    CallContext,
    GatewayClient,
    LlmCallRecord,
    ModelRoute,
    ModelProvider,
    OpenAIProvider,
    PromptTemplate,
    PromptVersion,
    ProviderCompletion,
    RenderedPrompt,
)
from brain.gateway.config import openai_routes
from brain.gateway.pricing import PRICE_SOURCE, PRICE_VERSION

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/datasets/intake_v1.jsonl"


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; empty samples are unknown, never zero latency."""
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    if not values:
        return None
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("measurements must be finite and non-negative")
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


class BenchmarkAudit:
    """Same audit protocol as production, with isolated in-memory storage."""

    def __init__(self) -> None:
        self.records: list[LlmCallRecord] = []

    async def ensure_prompt_version(
        self, *, context: CallContext, prompt: PromptTemplate
    ) -> PromptVersion:
        return PromptVersion(
            uuid4(),
            prompt.name,
            prompt.version,
            prompt.content_sha256,
            prompt.template_uri,
        )

    async def write_llm_call(self, record: LlmCallRecord) -> None:
        self.records.append(record)


class MeasuredProvider(OpenAIProvider):
    def __init__(self, client: AsyncOpenAI) -> None:
        super().__init__(client, streaming=True)
        self.measurements: list[ProviderCompletion] = []

    async def invoke(
        self, *, route: ModelRoute, prompt: RenderedPrompt
    ) -> ProviderCompletion:
        completion = await super().invoke(route=route, prompt=prompt)
        self.measurements.append(completion)
        return completion


async def benchmark(samples: int) -> dict[str, object]:
    if not 1 <= samples <= 100:
        raise ValueError("samples must be in [1, 100]")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ValueError("OPENAI_API_KEY is required")
    cases = [json.loads(line) for line in DATASET.read_text().splitlines()]
    audit = BenchmarkAudit()
    observations = []
    routes = openai_routes(os.environ)
    # No provider SDK retries: retries remain visible in GatewayClient receipts.
    async with AsyncOpenAI(api_key=key, max_retries=0, timeout=15) as client:
        provider = MeasuredProvider(client)
        for index in range(samples):
            case = cases[index % len(cases)]
            gateway = GatewayClient(
                context=CallContext(uuid4(), uuid4(), uuid4()),
                providers={"openai": cast(ModelProvider, provider)},
                tier_routes=routes,
                audit=audit,
                timeout_seconds=15,
            )
            started = time.perf_counter()
            result = await normalize_intake(
                IntakeRequest(
                    resident_report=case["report"],
                    access_permission=case["access_permission"],
                    pets_present=case["pets_present"],
                ),
                gateway=gateway,
            )
            facts = result.facts
            correct = bool(
                facts
                and facts.intent.value == case["intent"]
                and facts.access_permission == case["access_permission"]
                and facts.pets_present == case["pets_present"]
            )
            observations.append(
                {
                    "case_id": case["id"],
                    "correct": correct,
                    "completed": facts is not None,
                    "repair_attempted": result.repair_attempted,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            )
        completions = provider.measurements
    elapsed = [float(row["elapsed_ms"]) for row in observations]
    ttft = [
        float(item.first_token_ms)
        for item in completions
        if item.first_token_ms is not None
    ]
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    source = hashlib.sha256()
    paths = list((ROOT / "services/brain/src/brain").rglob("*.py"))
    paths += list((ROOT / "services/brain/src/brain/prompts").glob("*.j2"))
    for path in sorted(paths):
        source.update(path.relative_to(ROOT).as_posix().encode())
        source.update(path.read_bytes())
    return {
        "scope": "synthetic intake-agent benchmark; not end-to-end repair time or production SLO",
        "created_at": datetime.now(UTC).isoformat(),
        "git_sha": revision,
        "source_sha256": source.hexdigest(),
        "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "concurrency": 1,
        "samples": samples,
        "unique_cases": len({row["case_id"] for row in observations}),
        "routes": {tier.value: asdict(route) for tier, route in routes.items()},
        "accuracy": sum(bool(row["correct"]) for row in observations) / samples,
        "completion_rate": sum(bool(row["completed"]) for row in observations)
        / samples,
        "p50_intake_ms": percentile(elapsed, 0.5),
        "p95_intake_ms": percentile(elapsed, 0.95),
        "max_intake_ms": max(elapsed),
        "first_case_ms": elapsed[0],
        "schema_valid_completions": sum(bool(row["completed"]) for row in observations),
        "p50_provider_ttft_ms": percentile(ttft, 0.5),
        "p95_provider_ttft_ms": percentile(ttft, 0.95),
        "provider_attempts": len(audit.records),
        "measured_streams": len(completions),
        "priced_streams": sum(item.pricing_version is not None for item in completions),
        "estimated_cost_microusd": sum(item.cost_microusd for item in completions),
        "input_tokens": sum(item.input_tokens for item in completions),
        "cached_input_tokens": sum(item.cached_input_tokens for item in completions),
        "output_tokens": sum(item.output_tokens for item in completions),
        "price_version": PRICE_VERSION,
        "price_source": PRICE_SOURCE,
        "observations": observations,
        "limitations": [
            "Small synthetic development set, not a held-out production evaluation.",
            "TTFT measures first non-empty provider content at the worker, not browser-visible text.",
            "Costs estimate completed streams with final usage only; interrupted attempts may also be billed.",
            "Repeated cases are correlated; no population reliability or repair-time improvement is inferred.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Allow bounded paid model calls"
    )
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "output/benchmarks/intake.json"
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; this benchmark consumes provider tokens")
    load_dotenv(ROOT / ".env", override=False)
    try:
        report = asyncio.run(benchmark(args.samples))
    except Exception as error:
        raise SystemExit(
            f"Benchmark failed ({type(error).__name__}); no secrets or raw provider errors displayed"
        ) from None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Saved synthetic intake measurements: {args.output}")


if __name__ == "__main__":
    main()
