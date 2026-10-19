"""Emit the OpenAPI artifact the frontend is generated from.

Writes `backend/openapi.json` and copies it to `docs/openapi.json`
(`05-PHASE-PLAN.md` picks the backend copy as the generated one). Both are
committed, and a test fails if either drifts from the running application.

The spec must not depend on the machine that produced it, so this builds the
app with fixed settings rather than the developer's environment: no database
URL is needed because generating a schema touches no data.

    cd backend && python scripts/emit_openapi.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

BACKEND_SPEC = BACKEND_ROOT / "openapi.json"
DOCS_SPEC = REPO_ROOT / "docs" / "openapi.json"


def build_spec() -> dict:
    settings = Settings(
        env="development",
        app_database_url="",
        auth_dev_bypass=False,
        api_docs_enabled=True,
    )
    return create_app(settings).openapi()


def main() -> int:
    spec = build_spec()
    text = json.dumps(spec, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    BACKEND_SPEC.write_text(text, encoding="utf-8")
    shutil.copyfile(BACKEND_SPEC, DOCS_SPEC)
    print(f"wrote {BACKEND_SPEC.relative_to(REPO_ROOT)} ({len(spec['paths'])} paths)")
    print(f"copied to {DOCS_SPEC.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
