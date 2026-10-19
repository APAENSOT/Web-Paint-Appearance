"""Serve the built frontend from the API process (one Cloud Run service, one origin).

Only active when ``STATIC_DIR`` is set. One origin means no CORS preflight on
any call, and the browser reuses one connection for the page and its API.

Cache rules: Vite's hashed ``/assets/*`` never change under a name, so they
are cached for a year; ``index.html`` is always revalidated so a deploy is
seen on the next load; any other public file (models, images) for an hour.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

#: Paths the API owns. A miss under these is the API's 404, never index.html.
API_PREFIXES = ("api/", "health/", "docs", "redoc", "openapi.json")

# Slim images ship no /etc/mime.types: without these a model is sent as text/plain.
mimetypes.add_type("model/gltf-binary", ".glb")
mimetypes.add_type("model/gltf+json", ".gltf")

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
SHORT = "public, max-age=3600"


def mount_spa(app: FastAPI, root: Path) -> None:
    root = root.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"STATIC_DIR {root} has no index.html; build the frontend first.")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request) -> FileResponse:
        if path.startswith(API_PREFIXES):
            raise HTTPException(status_code=404, detail="Not found.")
        target = (root / path).resolve()
        # resolve() then is_relative_to: no `..` or symlink walks out of root.
        if path and target.is_relative_to(root) and target.is_file():
            cache = IMMUTABLE if path.startswith("assets/") else (
                REVALIDATE if target == index else SHORT)
            return FileResponse(target, headers={"Cache-Control": cache})
        # Client-side route (e.g. /plant/SAP): the app shell decides.
        return FileResponse(index, headers={"Cache-Control": REVALIDATE})

    # Without this, a write to a path no route owns would match the GET above
    # by path and answer 405, which reads like "right path, wrong method".
    @app.api_route("/{path:path}", methods=["POST", "PUT", "PATCH", "DELETE"],
                   include_in_schema=False)
    def no_such_route(path: str) -> None:
        raise HTTPException(status_code=404, detail="Not found.")
