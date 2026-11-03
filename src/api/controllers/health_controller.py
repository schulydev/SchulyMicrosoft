from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from mediatorx import Mediator

from src.api.controller import controller
from src.api.dependencies import get_mediator
from src.application.queries.get_readiness_query import GetReadinessQuery

router = APIRouter()


@controller(router)
class HealthController:
    mediator: Mediator = Depends(get_mediator)

    @router.get("/health/live", include_in_schema=False)
    async def health_live(self):
        return {"status": "ok"}

    @router.get("/health/ready", include_in_schema=False)
    async def health_ready(self):
        if await self.mediator.send(GetReadinessQuery()):
            return {"status": "ready"}
        return JSONResponse({"status": "starting"}, status_code=503)

    @router.get("/", include_in_schema=False)
    async def root(self):
        return {"service": "SchulyMicrosoft", "status": "ok"}
