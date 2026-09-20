"""online-avatar 入口：数字人对话服务。

运行: uvicorn app.main:app --host 0.0.0.0 --port 8000
前端: 开发模式在 web/ 下 `npm run dev`（Vite 代理 /ws 到 8000）；
      生产模式由本服务直接托管 web/dist（需先 `npm run build`）。
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.solutions import register_all
from app.ws.avatar import router as avatar_router

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DIST_DIR = WEB_DIR / "dist"

# 显式完成方案注册（幂等），import 顺序不再影响注册表内容
register_all()

app = FastAPI(title="online-avatar", version="0.1.0")
app.include_router(avatar_router)


@app.get("/healthz")
async def healthz() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "default_solution": settings.default_solution,
        "dashscope_configured": bool(settings.dashscope_api_key),
    }


if DIST_DIR.exists():
    # 生产：托管前端构建产物（注册在 API 路由之后，不影响 /ws 与 /healthz）
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="web")
else:

    @app.get("/")
    async def index_hint() -> JSONResponse:
        return JSONResponse(
            {
                "hint": "前端未构建。开发模式: cd web && npm run dev；"
                "或先执行 cd web && npm run build 后由本服务托管。"
            }
        )


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
