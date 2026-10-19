"""API v1 router assembly."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    auth, batches, comparison, dashboard, film_standards, filmthickness, history, img_overview, landing, mappings,
    measurements, meta, overview, reserved, standards, uploads, workbooks,
)
from app.api.v1 import color_appearance
from app.api.v1 import pairing
from app.api.v1 import point_profiles
from app.api.v1 import monthly_detail
from app.api.v1 import analysis_report
from app.api.v1 import analysis_assistant
from app.api.v1 import point_walk

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(meta.router)
router.include_router(measurements.router)
router.include_router(uploads.router)
router.include_router(batches.router)
router.include_router(dashboard.router)
router.include_router(mappings.router)
router.include_router(workbooks.router)
router.include_router(history.router)
router.include_router(filmthickness.router)
router.include_router(film_standards.router)
router.include_router(comparison.router)
router.include_router(overview.router)
router.include_router(img_overview.router)
router.include_router(img_overview.colors_router)
router.include_router(landing.router)
router.include_router(standards.router)
router.include_router(color_appearance.router)
router.include_router(point_profiles.router)
router.include_router(monthly_detail.router)
router.include_router(pairing.router)
router.include_router(analysis_report.router)
router.include_router(analysis_assistant.router)
router.include_router(point_walk.router)
router.include_router(reserved.router)

__all__ = ["router"]
