"""FastAPI app: API, live events, and the built Angular UI from the wheel."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.api.assist import router as assist_router
from linkit_all.api.events import EventBus
from linkit_all.api.routes import router
from linkit_all.api.runner import PipelineRunner
from linkit_all.api.security import LocalOnly
from linkit_all.api.suggest import router as suggest_router
from linkit_all.apply.browser import UserBrowser
from linkit_all.apply.vault import vault_for
from linkit_all.core.config import Settings, get_settings
from linkit_all.core.db import init_db
from linkit_all.core.lo_install import LibreOfficeInstaller
from linkit_all.core.log import setup_logging
from linkit_all.core.scheduler import apply_schedule, make_scheduler, register_runner
from linkit_all.core.search import SearchConfig, load_search
from linkit_all.matching.trash import sweep

STATIC = Path(__file__).parent.parent / "static" / "browser"  # Angular build output
EXTENSION_ADDRESS = Path(__file__).parent.parent / "extension" / "app.json"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.bus.bind(asyncio.get_running_loop())
        app.state.vault.unlock_from_keyring()
        sink = logger.add(app.state.bus.log_sink, level="INFO",
                          filter=lambda r: (r["name"] or "").startswith("linkit_all"))  # fmt: skip
        register_runner(app.state.runner, app.state.user_browser)
        app.state.scheduler.start()
        apply_schedule(app.state.scheduler, load_search(app.state.db) or SearchConfig())
        yield
        app.state.scheduler.shutdown(wait=False)
        register_runner(None)
        app.state.runner.cancel()
        await app.state.user_browser.close()
        logger.remove(sink)

    app = FastAPI(
        title="LinKit All", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    app.state.settings = settings
    app.state.db = init_db(settings.db_path)
    app.state.vault = vault_for(settings, app.state.db)
    app.state.bus = EventBus()
    app.state.user_browser = UserBrowser()
    app.state.lo_installer = LibreOfficeInstaller(settings)
    app.state.runner = PipelineRunner(app.state.db, settings, app.state.bus, app.state.vault)
    app.state.scheduler = make_scheduler(app.state.db.kw["bind"])
    app.add_middleware(LocalOnly, extra_origins=settings.dev_origins)
    app.include_router(router)
    app.include_router(suggest_router)
    app.include_router(assist_router)

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """Static files, else index.html so Angular's router handles deep links."""
        if path.startswith("api/"):
            raise HTTPException(404)
        # index.html must be revalidated, or browsers keep an old build for hours (no Cache-Control
        # means a guessed lifetime); the hashed JS/CSS names change per build, so they cache fine
        fresh = {"Cache-Control": "no-cache"}
        file = (STATIC / path).resolve()
        if path and file.is_file() and file.is_relative_to(STATIC.resolve()):
            return FileResponse(file, headers=fresh if file.suffix == ".html" else None)
        index = STATIC / "index.html"
        if not index.is_file():
            raise HTTPException(404, "UI not built: run `npm run build` in frontend/")
        return FileResponse(index, headers=fresh)

    return app


def _tell_extension(port: int) -> None:
    """LinkIt Fill reads this from its own folder, so nobody has to type the port."""
    try:
        EXTENSION_ADDRESS.write_text(json.dumps({"port": port}), "utf-8")
    except OSError as e:  # the extension then tries the default port
        logger.warning("could not tell LinkIt Fill the port: {}", e)


def _sweep_trash(db: sessionmaker[Session], settings: Settings) -> None:
    """Start-up pass, so a change of rules needs no new search before old jobs disappear."""
    from linkit_all.pipeline import _get_embedder

    try:
        sweep(db, load_search(db) or SearchConfig(),
              lambda texts: asyncio.run(_get_embedder(settings))(texts))  # fmt: skip
    except Exception:
        logger.exception("could not update the hidden jobs")


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import threading
    import webbrowser

    import uvicorn

    settings = get_settings()
    setup_logging(settings)
    if open_browser:
        threading.Timer(1.5, webbrowser.open, [f"http://{host}:{port}/"]).start()
    app = create_app(settings)
    _tell_extension(port)
    threading.Thread(target=_sweep_trash, args=(app.state.db, settings), daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
