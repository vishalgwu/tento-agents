"""Versioned standard token-price estimates, separate from provider billing."""

from decimal import Decimal, ROUND_CEILING

PRICE_VERSION = "openai-standard-2026-10-25"
PRICE_SOURCE = "https://developers.openai.com/api/docs/models/gpt-4.1-mini"
# USD per million tokens. Restrict aliases explicitly; never guess unknown rates.
_RATES = {
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("0.10"), Decimal("1.60")),
    "gpt-4.1-mini-2025-04-14": (Decimal("0.40"), Decimal("0.10"), Decimal("1.60")),
}


def estimate_microusd(
    model: str, *, input_tokens: int, cached_tokens: int, output_tokens: int
) -> int | None:
    """Round each estimate up to a microdollar; unknown prices remain unknown.

    OpenAI prompt_tokens includes cached tokens. Subtract them before applying
    the uncached rate to avoid double billing. Excludes hosting, tools and tax.
    """
    if min(input_tokens, cached_tokens, output_tokens) < 0:
        raise ValueError("token counts must be non-negative")
    if cached_tokens > input_tokens:
        raise ValueError("cached tokens cannot exceed total input")
    rates = _RATES.get(model)
    if rates is None:
        return None
    uncached_rate, cached_rate, output_rate = rates
    # $ / million tokens equals microdollars / token.
    value = (
        (input_tokens - cached_tokens) * uncached_rate
        + cached_tokens * cached_rate
        + output_tokens * output_rate
    )
    return int(value.to_integral_value(rounding=ROUND_CEILING))
