from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from gitshield import __version__
from gitshield.web.automation import AutoReviewer
from gitshield.web.config import settings
from gitshield.web.db import Database
from gitshield.web.github import GitHubClient, GitHubError
from gitshield.web.routes import (
    automation,
    ci,
    dependency_batch,
    draft_issues,
    fix_prs,
    gamification,
    memory,
    metrics,
    notifications,
    pulls,
    repos,
    status,
)
from gitshield.web.security import ApiTokenMiddleware, LocalOnlyMiddleware

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = Database(settings.db_path)
    app.state.db.fail_interrupted_reviews()
    app.state.gh = GitHubClient()
    app.state.watcher = AutoReviewer(app.state.db, app.state.gh, settings.auto_review_interval)
    app.state.watcher.start()
    yield
    await app.state.watcher.stop()
    await app.state.gh.aclose()
    app.state.db.close()


app = FastAPI(title="GitShield", version=__version__, lifespan=lifespan)
# Added first so it runs inside LocalOnlyMiddleware: host and CSRF checks answer before the token.
app.add_middleware(ApiTokenMiddleware)
app.add_middleware(LocalOnlyMiddleware)


@app.exception_handler(GitHubError)
async def github_error_handler(_: Request, exc: GitHubError) -> JSONResponse:
    status = exc.status_code if 400 <= exc.status_code < 600 else 502
    return JSONResponse({"detail": f"GitHub: {exc.message}"}, status_code=status)



app.include_router(status.router)
app.include_router(repos.router)
app.include_router(pulls.router)
app.include_router(gamification.router)
app.include_router(ci.router)
app.include_router(fix_prs.router)
app.include_router(memory.router)
app.include_router(dependency_batch.router)
app.include_router(metrics.router)
app.include_router(notifications.router)
app.include_router(automation.router)
app.include_router(draft_issues.router)


# ---- Frontend -------------------------------------------------------------------------

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = (FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and FRONTEND_DIST in candidate.parents:
            return FileResponse(candidate)
        # index.html references hashed assets; never cache it so new builds load immediately.
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})
else:
    SETUP_PAGE = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>GitShield · kurulum</title>
<style>body{font:15px/1.6 system-ui,sans-serif;max-width:620px;margin:12vh auto;padding:0 20px;color:#17171c;background:#f6f6f3}
code,pre{font-family:ui-monospace,Consolas,monospace;background:#fff;border:1px solid #e8e7e2;border-radius:8px}
pre{padding:12px 14px}code{padding:1px 6px}h1{font-size:22px}</style></head><body>
<h1>🛡️ GitShield arayüzü henüz derlenmemiş</h1>
<p>API çalışıyor (<a href="/api/status">/api/status</a>) ama <code>web/dist</code> bulunamadı. Arayüzü bir kez derle:</p>
<pre>cd web
npm install
npm run build</pre>
<p>Ardından <code>gitshield web</code>'i yeniden başlat. Geliştirme için <code>npm run dev</code> ile
<a href="http://localhost:5173">localhost:5173</a> da kullanılabilir.</p></body></html>"""

    @app.get("/", include_in_schema=False)
    async def setup_page():
        return HTMLResponse(SETUP_PAGE, status_code=503)

