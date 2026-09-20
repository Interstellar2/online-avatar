# 运行镜像：FastAPI 直接托管宿主机预构建的前端产物（web/dist）。
#
# 为什么不用多阶段 node 构建：当前网络无法拉取 node 基础镜像，
# 且前端构建与后端部署解耦更简单——前端改动只需 npm run build 后重建本镜像。
#
# 构建前请确保: cd web && npm run build

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖（利用层缓存），再拷代码
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

# 前端产物（main.py 检测到 dist 存在即自动托管）
COPY web/dist ./web/dist

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
