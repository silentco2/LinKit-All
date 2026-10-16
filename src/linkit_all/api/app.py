"""FastAPI app: API, live events, and the built Angular UI from the wheel."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from loguru import logger

from linkit_all.api.events import EventBus
from linkit_all.api.routes import router
from linkit_all.api.runner import PipelineRunner
from linkit_all.api.security import LocalOnly
from linkit_all.apply.vault import vault_for
from linkit_all.core.config import Settings, get_settings
from linkit_all.core.db import init_db
from linkit_all.core.log import setup_logging

STATIC = Path(__file__).parent.parent / "static" / "browser"  # Angular build output


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.bus.bind(asyncio.get_running_loop())
        app.state.vault.unlock_from_keyring()
        sink = logger.add(app.state.bus.log_sink, level="INFO",
                          filter=lambda r: (r["name"] or "").startswith("linkit_all"))  # fmt: skip
        yield
        app.state.runner.cancel()
        logger.remove(sink)

    app = FastAPI(
        title="LinKit All", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    app.state.settings = settings
    app.state.db = init_db(settings.db_path)
    app.state.vault = vault_for(settings, app.state.db)
    app.state.bus = EventBus()
    app.state.runner = PipelineRunner(app.state.db, settings, app.state.bus)
    app.add_middleware(LocalOnly, extra_origins=settings.dev_origins)
    app.include_router(router)

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """Static files, else index.html so Angular's router handles deep links."""
        if path.startswith("api/"):
            raise HTTPException(404)
        file = (STATIC / path).resolve()
        if path and file.is_file() and file.is_relative_to(STATIC.resolve()):
            return FileResponse(file)
        index = STATIC / "index.html"
        if not index.is_file():
            raise HTTPException(404, "UI not built: run `npm run build` in frontend/")
        return FileResponse(index)

    return app


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import threading
    import webbrowser

    import uvicorn

    settings = get_settings()
    setup_logging(settings)
    if open_browser:
        threading.Timer(1.5, webbrowser.open, [f"http://{host}:{port}/"]).start()
    uvicorn.run(create_app(settings), host=host, port=port, log_level="warning")
