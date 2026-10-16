"""Phase 3 domain routers."""

from fastapi import APIRouter

from .cloud_connections import router as cloud_connections_router
from .incidents import router as incidents_router
from .notifications import router as notifications_router
from .rca import router as rca_router
from .tenants import router as tenants_router

router = APIRouter()
router.include_router(tenants_router)
router.include_router(cloud_connections_router)
router.include_router(incidents_router)
router.include_router(notifications_router)
router.include_router(rca_router)

__all__ = [
    "cloud_connections_router",
    "incidents_router",
    "notifications_router",
    "rca_router",
    "router",
    "tenants_router",
]
