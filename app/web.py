import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import uvicorn

load_dotenv()

BASE_DIR = Path(os.getenv("BASE_DIR", "/home/sweetbear/rtmp"))
VIDEOS_DIR = BASE_DIR / "videos"
TEMP_DIR = BASE_DIR / "temp"
LOGS_DIR = BASE_DIR / "logs"

WEB_USERNAME = os.getenv("WEB_USERNAME", "admin")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8010"))

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="RTMP Recorder Web")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("WEB_SECRET_KEY", "change-this-secret-key"),
)


def is_logged_in(request: Request) -> bool:
    return bool(request.session.get("logged_in"))


def require_login(request: Request):
    if not is_logged_in(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"

    size_kb = size_bytes / 1024
    if size_kb < 1024:
        return f"{size_kb:.2f} KB"

    size_mb = size_kb / 1024
    if size_mb < 1024:
        return f"{size_mb:.2f} MB"

    size_gb = size_mb / 1024
    return f"{size_gb:.2f} GB"


def format_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=BEIJING_TZ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def safe_file_path(filename: str) -> Path:
    """
    防止路径穿越。
    只允许访问 videos 目录下的普通文件。
    """
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = VIDEOS_DIR / filename

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return file_path


def get_video_files():
    files = []

    for file in VIDEOS_DIR.iterdir():
        if not file.is_file():
            continue

        stat = file.stat()

        files.append(
            {
                "name": file.name,
                "quoted_name": quote(file.name),
                "size": format_size(stat.st_size),
                "size_bytes": stat.st_size,
                "mtime": format_time(stat.st_mtime),
            }
        )

    files.sort(key=lambda item: item["mtime"], reverse=True)
    return files


def get_temp_files():
    files = []

    for file in TEMP_DIR.iterdir():
        if not file.is_file():
            continue

        stat = file.stat()

        files.append(
            {
                "name": file.name,
                "size": format_size(stat.st_size),
                "mtime": format_time(stat.st_mtime),
            }
        )

    files.sort(key=lambda item: item["mtime"], reverse=True)
    return files


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not is_logged_in(request):
        return RedirectResponse(url="/login", status_code=302)

    videos = get_video_files()
    temp_files = get_temp_files()

    total_size_bytes = sum(item["size_bytes"] for item in videos)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "videos": videos,
            "temp_files": temp_files,
            "video_count": len(videos),
            "temp_count": len(temp_files),
            "total_size": format_size(total_size_bytes),
        },
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_logged_in(request):
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": "",
        },
    )


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username == WEB_USERNAME and password == WEB_PASSWORD:
        request.session["logged_in"] = True
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": "用户名或密码错误",
        },
        status_code=401,
    )


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@app.get("/download/{filename}")
async def download_file(request: Request, filename: str):
    require_login(request)

    file_path = safe_file_path(filename)

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream",
    )


@app.post("/delete/{filename}")
async def delete_file(request: Request, filename: str):
    require_login(request)

    file_path = safe_file_path(filename)
    file_path.unlink()

    return RedirectResponse(url="/", status_code=302)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "videos_dir": str(VIDEOS_DIR),
        "temp_dir": str(TEMP_DIR),
    }


if __name__ == "__main__":
    uvicorn.run(
        "web:app",
        host=WEB_HOST,
        port=WEB_PORT,
        reload=False,
    )
