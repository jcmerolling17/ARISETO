from fastapi import APIRouter

from app.api.v1.endpoints import (
    activities,
    admin,
    auth,
    barangays,
    crops,
    expenses,
    farms,
    harvests,
    health,
    notifications,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(users.router)
api_router.include_router(barangays.router)
api_router.include_router(crops.router)
api_router.include_router(farms.router)
api_router.include_router(expenses.router)
api_router.include_router(harvests.router)
api_router.include_router(notifications.router)
api_router.include_router(activities.router)
