from fastapi import APIRouter

from app.api.v1.endpoints import admin, auth, barangays, farms, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(barangays.router)
api_router.include_router(farms.router)
