"""Explicit migration job; never runs during normal API startup.

Use MIGRATION_DATABASE_URL for an administrator connection, then
python -m api.migrate. Existing manual installs may use --adopt-through 0003
only after verifying those migrations were already applied and backing up.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]


async def migrate(adopt_through: str | None = None) -> None:
    value = os.environ.get("MIGRATION_DATABASE_URL", "").strip()
    if not value:
        raise ValueError(
            "MIGRATION_DATABASE_URL must be configured for this explicit job"
        )
    connection = await asyncpg.connect(
        value.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    try:
        await connection.execute("SELECT pg_advisory_lock(724126398)")
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations (name text PRIMARY KEY, sha256 char(64) NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        folder = Path(__file__).resolve().parents[4] / "infra" / "migrations"
        for path in sorted(folder.glob("*.sql")):
            content = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(content.encode()).hexdigest()
            saved = await connection.fetchval(
                "SELECT sha256 FROM public.schema_migrations WHERE name=$1", path.name
            )
            if saved:
                if saved != digest:
                    raise ValueError(
                        f"Previously applied migration changed: {path.name}"
                    )
                continue
            if adopt_through and path.name.split("_", 1)[0] <= adopt_through:
                await connection.execute(
                    "INSERT INTO public.schema_migrations(name,sha256) VALUES($1,$2)",
                    path.name,
                    digest,
                )
                print(f"Adopted existing {path.name}")
                continue
            # Each source migration includes BEGIN/COMMIT. Record its ledger entry
            # inside that transaction so a crash cannot leave an unrecorded apply.
            marker = content.rfind("COMMIT;")
            if marker < 0:
                raise ValueError(
                    f"Migration has no transaction terminator: {path.name}"
                )
            escaped_name = path.name.replace("'", "''")
            ledger = f"INSERT INTO public.schema_migrations(name,sha256) VALUES('{escaped_name}','{digest}');\n"
            await connection.execute(content[:marker] + ledger + content[marker:])
            print(f"Applied {path.name}")
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--adopt-through", choices=["0001", "0002", "0003", "0004", "0005"]
    )
    args = parser.parse_args()
    asyncio.run(migrate(args.adopt_through))


if __name__ == "__main__":
    main()
