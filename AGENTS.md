# AGENTS.md

## 项目简介

数字人对话服务（FastAPI）。当前实现 `cascade`（ASR→LLM→TTS 级联，阿里云百炼）与 `echo`（mock 引擎）两套方案，通过方案注册表并存，目标是在同一项目内对比多套数字人对话方案。

## 环境与命令

- Python ≥ 3.11，依赖装在项目内 `.venv`（`pip install -e '.[dev]'`）。
- 启动：`.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`；测试页在 `/`。
- 测试：后端 `.venv/bin/pytest -q`（69 个，mock 引擎 + FakeWS 协议单测 + TestClient 旅程测试，无需密钥）；前端 `cd web && npm run test`（vitest，35 个）。新增功能必须带测试：纯逻辑单测 + 能走真实栈的旅程测试优先走 TestClient/FakeTransport（共享假件在 `tests/fakes.py`）。
- 前端：Vue 3 + Vite + TS，位于 `web/`；`npm run dev`（代理到 8000）/ `npm run build`（产物由后端托管）。
- Docker：`docker compose up -d --build`（前端需先 `npm run build`，产物 COPY 进镜像；未用 node 多阶段——网络拉不到 node 基础镜像，见 Dockerfile 注释）。
- 配置：全部走环境变量 / `.env`（见 `.env.example`）；**密钥不进代码库**。

## 架构约定（改动时必须遵守）

- 三层分离：`core/`（基础设施与引擎协议）→ `solutions/`（方案，注册表 `registry.py`）→ `ws/`（协议适配）。注册由 `solutions/__init__.py` 的 `register_all()` 在 `main.py` 启动时显式调用，**不要**在 import 时注册。
- 引擎层协议在 `app/core/engines.py`：ASR/LLM/TTS 均为 async-iterator 风格 + 异步上下文管理器（三引擎统一，LLM 也有生命周期）。新增供应商实现不得改变该协议；`EngineError` 也定义在该模块。
- 引擎生命周期由 `EngineSet`（core/engines.py）统一托管：会话 `run()` 里 `async with EngineSet(...)`，连接在 `__aenter__` 建立。引擎构造函数不得私自建连。
- 级联会话 = 三个单一职责组件的组合：`cascade/shell.py`（recv 循环 + 消息分发）、`cascade/turn.py`（单轮 LLM/TTS 并行流水线）、`cascade/notifier.py`（协议消息构造）。`turn_started`/`turn_finished` 起止标记的成对发送由 `_turn_consumer` 保证，不要挪进 turn 内部。
- 级联类方案继承 `CascadeSolutionBase`（cascade/__init__.py），只提供引擎工厂与 system prompt；端到端（omni 类）模型不实现引擎协议，直接实现 `solutions/base.py` 的 `Solution` 协议（可复用 `SessionShell`）。
- 方案层不得直接依赖 FastAPI 的 WebSocket 对象，只面向 `core/transport.py` 的 `Transport` 协议编程（可测试性）；协议消息一律经 `SessionNotifier` 发送。
- 前后端消息类型改动需同步：`app/ws_protocol.py`、`web/src/types.ts`、`README.md` 协议表。
- WS 上音频一律用二进制帧，控制消息用 JSON 文本帧，不要引入 base64。音频编码经 URL query `?codec=opus` 协商（缺省 pcm 透传），编码方式由服务端随 `turn_started.codec` 确认；编解码只在会话收发边缘发生（`app/core/codecs.py`，进出引擎的永远是 PCM16），Opus 用 PyAV（静态捆绑 ffmpeg，无系统依赖）。

## 代码风格

- 全部 async（asyncio），禁止在事件循环里跑阻塞调用。
- 中文注释/文档字符串，解释"为什么"而非复述代码。
- 每轮对话的取消语义：interrupt → `TTSEngine.interrupt()` + 清空轮次队列 + 取消本轮 task；`turn_consumer` 需用 `Task.cancelling()` 区分"会话关闭"与"轮次打断"。
- 配置：供应商可调参数（VAD、音量等）一律进 `Settings`（config.py），引擎只接收参数；`.env` 路径已绝对化，与 CWD 无关。上行音频采样率字段名是 `input_audio_sample_rate`（勿与下行的 `tts_sample_rate` 混淆）。
- 前端 composables 按职责拆分（WS 会话/麦克风采集/音频播放），协议类型集中在 `web/src/types.ts`。
- 前端测试桩集中在 `web/tests/helpers.ts`（FakeWebSocket/FakeAudioContext），新增测试优先复用。
