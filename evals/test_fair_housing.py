"""Regression coverage for the synthetic fair-housing parity corpus."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from evals.fair_housing import (
    FairHousingEvaluationError,
    ResponseObservation,
    Side,
    evaluate_response_parity,
    load_redteam_pairs,
)


_DATASET_PATH = Path(__file__).with_name("datasets") / "redteam_fh.jsonl"


def _complete_observations() -> dict[str, dict[Side, ResponseObservation]]:
    pairs = load_redteam_pairs(_DATASET_PATH)
    observations: dict[str, dict[Side, ResponseObservation]] = {}
    for pair in pairs:
        observations[pair.identifier] = {
            "control": ResponseObservation(
                outcome=pair.control_expectation.outcome,
                response_elements=pair.control_expectation.required_response_elements,
                latency_class=pair.control_expectation.latency_class,
            ),
            "probe": ResponseObservation(
                outcome=pair.probe_expectation.outcome,
                response_elements=pair.probe_expectation.required_response_elements,
                latency_class=pair.probe_expectation.latency_class,
            ),
        }
    return observations


def test_redteam_dataset_covers_balanced_protected_signal_pairs() -> None:
    pairs = load_redteam_pairs(_DATASET_PATH)

    assert [pair.identifier for pair in pairs] == [
        f"redteam-fh-{number:03d}" for number in range(1, 21)
    ]
    assert Counter(pair.protected_signal for pair in pairs) == {
        "voucher_holder": 4,
        "wheelchair_access": 4,
        "service_animal": 4,
        "family_with_children": 4,
        "non_english_name": 4,
    }
    assert all(pair.control_prompt.endswith(pair.shared_request) for pair in pairs)
    assert all(pair.probe_prompt.endswith(pair.shared_request) for pair in pairs)
    assert all(pair.control_prompt != pair.probe_prompt for pair in pairs)
    assert all(pair.control_expectation == pair.probe_expectation for pair in pairs)


def test_complete_paired_observations_pass_the_parity_gate() -> None:
    pairs = load_redteam_pairs(_DATASET_PATH)

    assert evaluate_response_parity(pairs, _complete_observations()) == ()


def test_parity_gate_reports_outcome_completeness_and_latency_regressions() -> None:
    pairs = load_redteam_pairs(_DATASET_PATH)
    observations = _complete_observations()
    first_pair = pairs[0]
    observations[first_pair.identifier]["probe"] = ResponseObservation(
        outcome="human_review",
        response_elements=frozenset({"contact_path"}),
        latency_class="slow",
    )

    violations = evaluate_response_parity(pairs, observations)

    assert {(violation.pair_id, violation.code) for violation in violations} >= {
        (first_pair.identifier, "probe_outcome"),
        (first_pair.identifier, "probe_completeness"),
        (first_pair.identifier, "probe_latency_class"),
        (first_pair.identifier, "outcome_parity"),
        (first_pair.identifier, "completeness_parity"),
        (first_pair.identifier, "latency_class_parity"),
    }


def test_parity_gate_rejects_results_that_do_not_match_the_dataset() -> None:
    pairs = load_redteam_pairs(_DATASET_PATH)
    observations = _complete_observations()
    observations.pop(pairs[0].identifier)

    with pytest.raises(FairHousingEvaluationError, match="result pairs do not match"):
        evaluate_response_parity(pairs, observations)
