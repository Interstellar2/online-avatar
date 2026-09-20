# 贡献指南

感谢你对 online-avatar 的关注！本项目是一个 FastAPI 数字人对话服务，通过可插拔方案架构支持多套数字人对话实现。提交贡献前请先阅读本指南与 [AGENTS.md](AGENTS.md)。

## 环境搭建

- Python ≥ 3.11，依赖统一安装在项目内 `.venv`：

  ```bash
  python3.11 -m venv .venv
  .venv/bin/pip install -e '.[dev]'
  ```

- 前端（Vue 3 + Vite + TS，位于 `web/`）：

  ```bash
  cd web && npm install
  ```

- 配置全部走环境变量 / `.env`（参考 `.env.example`）。**密钥不进代码库**，提交前请确认没有混入任何密钥。

## 启动与测试

- 启动后端：`.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`，测试页在 `/`。
- 前端开发：`cd web && npm run dev`（代理到 8000）。
- 后端测试：`.venv/bin/pytest -q`（mock 引擎 + TestClient 旅程测试，无需密钥）。
- 前端测试：`cd web && npm run test`（vitest）。
- 前端构建：`cd web && npm run build`。

## 架构约定（改动时必须遵守）

- 三层分离：`core/`（基础设施与引擎协议）→ `solutions/`（方案，注册表 `registry.py`）→ `ws/`（协议适配）。
- 引擎层协议在 `app/core/engines.py`：ASR/LLM/TTS 均为 async-iterator 风格 + 异步上下文管理器。新增供应商实现不得改变该协议。
- 端到端（omni 类）模型不实现引擎协议，直接实现 `solutions/base.py` 的 `Solution` 协议。
- 方案层不得直接依赖 FastAPI 的 WebSocket 对象，只面向 `core/transport.py` 的 `Transport` 协议编程（可测试性）。
- 前后端消息类型改动需同步：`app/ws_protocol.py`、`web/src/types.ts`、`README.md` 协议表。
- WS 上传输音频一律用二进制帧（PCM16），控制消息用 JSON 文本帧，不要引入 base64。
- 代码风格：全部 async（asyncio），禁止在事件循环里跑阻塞调用；中文注释/文档字符串，解释"为什么"而非复述代码。
- 前端 composables 按职责拆分（WS 会话/麦克风采集/音频播放），测试桩集中在 `web/tests/helpers.ts`，新增测试优先复用。

## 测试要求

**新增功能必须带测试**，优先：

1. 纯逻辑单测（不依赖网络与密钥）；
2. 能走真实栈的旅程测试（后端用 TestClient / FakeTransport，前端复用 `web/tests/helpers.ts`）。

## 提交规范

- 提交信息使用中文或英文均可，建议格式：`<类型>: <简述>`，类型如 `feat` / `fix` / `refactor` / `test` / `docs` / `chore`。
- 一个 PR 只做一件事；破坏性变更需在 PR 描述中显式说明。
- 改动涉及 `AGENTS.md` 中提到的文件/结构/流程时，需同步更新 `AGENTS.md`。
- PR 需通过 CI（后端 pytest、前端 vitest + vue-tsc + build）后才会被合并。
