"""Export the registered API contracts plus middleware security/error contracts."""

from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "services/api/src"), str(ROOT / "services/brain/src")]
from api.main import create_app  # noqa: E402

spec = create_app().openapi()
spec["servers"] = [{"url": "/v1"}]
spec["paths"] = {
    path.removeprefix("/v1"): value for path, value in spec["paths"].items()
}
spec["security"] = [{"bearerAuth": []}]
components = spec.setdefault("components", {})
components["securitySchemes"] = {
    "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
}
components.setdefault("schemas", {})["Problem"] = {
    "type": "object",
    "required": ["type", "title", "status", "detail"],
    "properties": {
        "type": {"type": "string"},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "detail": {"type": "string"},
        "instance": {"type": "string"},
    },
}
for methods in spec["paths"].values():
    for method, operation in methods.items():
        if method not in {"get", "post", "put", "patch", "delete"}:
            continue
        if method in {"post", "put", "patch"}:
            operation.setdefault("parameters", []).append(
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string", "minLength": 1, "maxLength": 255},
                }
            )
        for status in (
            "400",
            "401",
            "403",
            "404",
            "409",
            "422",
            "429",
            "500",
            "503",
            "504",
        ):
            operation.setdefault("responses", {})[status] = {
                "description": "Safe problem response; see RFC 9457.",
                "content": {
                    "application/problem+json": {
                        "schema": {"$ref": "#/components/schemas/Problem"}
                    }
                },
            }
(ROOT / "docs/openapi.yaml").write_text(
    yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8"
)
print("Exported docs/openapi.yaml from registered API routes")
