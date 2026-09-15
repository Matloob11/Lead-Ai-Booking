from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import get_settings
from .db import init_db

_REPO_PANEL = Path(__file__).resolve().parents[2] / "panel"
PANEL_DIR = Path(os.environ.get("PANEL_DIR") or (_REPO_PANEL if _REPO_PANEL.is_dir() else "/panel"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="A7 Agent Daily Reports", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health():
    settings = get_settings()
    return {
        "ok": True,
        "service": "agent-reports",
        "webhook_configured": bool(settings.webhook_base()),
        "openai_configured": bool(settings.openai_api_key),
        "dept_ids": settings.dept_id_list(),
        "messenger_user_ids": settings.messenger_user_id_list(),
        "tz": settings.agent_report_tz,
        "cron": f"{settings.agent_report_cron_minute} {settings.agent_report_cron_hour} * * *",
        "panel_dir": str(PANEL_DIR),
    }


def _panel_index() -> Response:
    index = PANEL_DIR / "index.html"
    if not index.is_file():
        return JSONResponse({"ok": True, "panel": "missing", "panel_dir": str(PANEL_DIR)})
    return FileResponse(index)


@app.api_route("/", methods=["GET", "POST", "HEAD"])
async def panel_index(_request: Request):
    # Bitrix local apps POST the placement payload to the handler URL. The
    # WhatsApp panel nginx maps 405→200 the same way — accept POST, ignore body.
    return _panel_index()


_assets = PANEL_DIR / "assets"
if _assets.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")
