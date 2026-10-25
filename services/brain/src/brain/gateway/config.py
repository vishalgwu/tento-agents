"""Deployment-owned task tier configuration; no model-controlled routing."""

from collections.abc import Mapping

from brain.gateway.client import ModelRoute, ModelTier


def openai_routes(environment: Mapping[str, str]) -> dict[ModelTier, ModelRoute]:
    """Default to the proven model; enable independent pinned tier overrides.

    An omitted temperature preserves provider defaults for models which do not
    support sampling controls. An explicit value is validated by ModelRoute.
    """
    default = environment.get("OPENAI_MODEL", "").strip()
    if not default:
        raise ValueError("OPENAI_MODEL is required")
    raw_temperature = environment.get("OPENAI_TEMPERATURE", "").strip()
    temperature = float(raw_temperature) if raw_temperature else None
    routes = {}
    for tier in ModelTier:
        name = environment.get(f"OPENAI_MODEL_{tier.value.upper()}", "").strip()
        model = name or default
        routes[tier] = ModelRoute(
            provider="openai",
            model_name=model,
            model_version=model,
            max_output_tokens=int(environment.get("OPENAI_MAX_OUTPUT_TOKENS", "1024")),
            temperature=temperature,
        )
    return routes
