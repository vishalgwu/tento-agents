"""Protect percentile semantics and the explicit paid-benchmark boundary."""

import math

import pytest

from evals.model_benchmark import percentile


def test_nearest_rank_includes_tail_and_does_not_invent_empty_results() -> None:
    values = [float(index) for index in range(1, 21)]
    assert percentile(values, 0.95) == 19
    assert percentile(values, 0.5) == 10
    assert percentile(values, 1) == 20
    assert percentile([], 0.95) is None
    for invalid in (math.inf, math.nan, -1):
        with pytest.raises(ValueError):
            percentile([invalid], 0.95)
    with pytest.raises(ValueError):
        percentile(values, 0)
