"""Generate real demo recordings and score the actual isolated FTS retriever."""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from brain.demo import DATA_ROOT, execute_demo, retrieve_demo

ROOT = Path(__file__).resolve().parents[1]


async def record() -> None:
    cases = json.loads((DATA_ROOT / "cases.json").read_text(encoding="utf-8"))
    scenarios = []
    rankings = []
    for case in cases:
        ranking = retrieve_demo(case["query"])
        expected = set(case["expected_doc_ids"])
        rankings.append(
            {
                "case_id": case["case_id"],
                "ranking": ranking,
                "expected": sorted(expected),
                "precision_at_3": len(expected.intersection(ranking[:3])) / 3,
                "recall_at_3": len(expected.intersection(ranking[:3])) / len(expected)
                if expected
                else None,
                "recall_at_5": len(expected.intersection(ranking[:5])) / len(expected)
                if expected
                else None,
            }
        )
        result = await execute_demo(case["query"], actor_org_id=uuid4())
        scenarios.append(
            {
                "id": case["case_id"],
                "query": case["query"],
                "expected_behavior": case["expected_behavior"],
                "expected_doc_ids": case["expected_doc_ids"],
                "result": result,
            }
        )
        print(
            f"Recorded {case['case_id']}: {result['status']}; {len(result['model_calls'])} actual model calls",
            flush=True,
        )
    answerable = [row for row in rankings if row["recall_at_3"] is not None]
    artifact = {
        "synthetic": True,
        "recorded_at": datetime.now(UTC).isoformat(),
        "scope": "15 development scenarios over five fictional documents; SQLite FTS5/BM25, not the production PostgreSQL index",
        "manifest_sha256": hashlib.sha256(
            (DATA_ROOT / "manifest.json").read_bytes()
        ).hexdigest(),
        "scenarios": scenarios,
    }
    (ROOT / "apps/web/lib/demo-recordings.json").write_text(
        json.dumps(artifact, indent=2) + "\n", encoding="utf-8"
    )
    report = {
        "scope": artifact["scope"],
        "recorded_at": artifact["recorded_at"],
        "answerable_cases": len(answerable),
        "case_count": len(cases),
        "macro_precision_at_3": sum(float(row["precision_at_3"]) for row in answerable)
        / len(answerable),
        "macro_recall_at_3": sum(float(row["recall_at_3"]) for row in answerable)
        / len(answerable),
        "macro_recall_at_5": sum(float(row["recall_at_5"]) for row in answerable)
        / len(answerable),
        "rankings": rankings,
        "unanswerable_source_cases": sum(not row["expected"] for row in rankings),
        "no_match_accuracy": sum(
            not row["ranking"] for row in rankings if not row["expected"]
        )
        / max(1, sum(not row["expected"] for row in rankings)),
        "limitations": [
            "Small supplied development set, not held out.",
            "Retrieval relevance does not authorize a legal answer or an operational write.",
            "No semantic faithfulness or production quality claim is inferred.",
        ],
    }
    out = ROOT / "output/benchmarks/part2-demo-retrieval.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required to generate real model-call recordings")
    load_dotenv(ROOT / ".env")
    try:
        asyncio.run(record())
    except Exception as error:
        raise SystemExit(
            f"Demo recording failed ({type(error).__name__}); no secret values displayed"
        ) from None
