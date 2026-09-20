# online-avatar

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

基于 ASR → LLM → TTS 级联的实时数字人语音对话方案。

用户通过麦克风与数字人自然对话：服务端实时识别语音（服务端 VAD 自动判停），流式调用大模型生成回答，并按标点切句并行驱动语音合成——LLM 还在生成后续内容时，前面的句子已经开始合成播放，最大程度降低响应延迟。合成音频通过 WebSocket 二进制帧直推前端播放。

## 特性

- **低延迟流式流水线**：ASR 判停 → LLM 流式输出 → 标点切句 → TTS 流式合成，逐句并行推进
- **打断（Barge-in）**：随时打断当前播报，立即开始新一轮对话
- **多轮上下文**：自动维护对话历史（成对截断防拆散）
- **可插拔架构**：引擎层（ASR/LLM/TTS）与方案层（Solution）统一抽象，支持多种对话方案并存对比（级联 / omni 端到端 / 第三方实时方案）
- **全链路可测**：后端 61 个 pytest（含真实 WS 栈旅程测试）+ 前端 28 个 vitest，无需密钥即可跑通
- **一键部署**：Docker Compose 单容器交付（后端 + 前端产物 + 健康检查）

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI + uvicorn + asyncio + websockets + httpx |
| ASR | 阿里云百炼 `qwen3-asr-flash-realtime`（服务端 VAD） |
| LLM | 阿里云百炼 `qwen-plus`（OpenAI 兼容，SSE 流式） |
| TTS | 阿里云百炼 `cosyvoice-v3-flash`（流式 PCM） |
| 前端 | Vue 3 + Vite + TypeScript |
| 部署 | Docker Compose |

模型与音色均通过环境变量配置，可替换为任意兼容实现。

### 方案对比

| | cascade | echo |
|---|---|---|
| 引擎 | 阿里云百炼 ASR / LLM / TTS | 内置 mock 引擎（正弦波 beep） |
| 外部依赖 | 需 `DASHSCOPE_API_KEY` | 无 |
| 适用场景 | 真实对话体验、延迟观测 | 架构验证、CI、无网环境演示 |
| 端到端延迟 | 见下方延迟埋点 | 纯本地，仅含流水线开销 |

## 架构

```
浏览器（Vue 前端）
   │  WebSocket：二进制帧上行 PCM16 16k 麦克风音频
   │            JSON 文本帧控制消息
   │            二进制帧下行合成音频（PCM16）
   ▼
┌─────────────────────────────────────────────┐
│ /ws/avatar/{solution}  →  Solution.handle()  │
│                                             │
│ 方案层（solutions/，注册表并存多方案）          │
│   cascade: ASR → LLM → TTS 级联              │
│   echo:    内置回声引擎（无外部依赖，开箱即测）  │
│                                             │
│ 会话编排（cascade/，组合三个单一职责组件）：     │
│   SessionShell：  recv 循环 + 消息分发 + ping   │
│   TurnRunner：    LLM 流式 → 切句 → TTS 并行    │
│   SessionNotifier：协议消息构造与发送            │
│   ASR 判停 → 一轮回答（起止标记成对，可打断）    │
└─────────────────────────────────────────────┘
   │  引擎层面向 ASREngine / LLMEngine / TTSEngine 协议编程
   ▼
阿里云百炼
```

### 目录

```
app/
├── core/                  # 与方案无关的基础设施
│   ├── transport.py       #   Transport 抽象（WS/内存可替换，方案层不依赖框架）
│   ├── engines.py         #   引擎协议 + EngineError + EngineSet（统一生命周期）
│   ├── sentence.py        #   流式标点切句器
│   └── dialogue.py        #   多轮对话上下文
├── solutions/             # 方案层：每套方案一个包，register_all() 显式注册
│   ├── base.py / registry.py
│   ├── cascade/           # 级联方案（shell.py / turn.py / notifier.py / session.py）
│   └── echo/              # 回声引擎方案（复用级联装配，无需密钥）
├── ws/avatar.py           # WebSocket 入口 + Transport 适配
├── ws_protocol.py         # 前后端消息协议
└── main.py                # FastAPI 入口（托管 web/dist、/healthz）
web/                       # Vue 3 + Vite + TS 前端
tests/                     # 后端测试（pytest）
web/tests/                 # 前端测试（vitest）
```

## 快速开始

### 1. 启动后端

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env        # 填入 DASHSCOPE_API_KEY（阿里云百炼）
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2. 启动前端

```bash
cd web
npm install
npm run dev                 # http://localhost:5173（/ws、/healthz 已代理到 8000）
```

打开页面，方案选择 `cascade`，点击"开始说话"即可对话。

无 API Key 时可选择 `echo` 方案体验完整交互流程（内置回声引擎，无需任何外部服务）。

### 3. Docker 部署（生产）

```bash
cd web && npm run build     # 前端产物打进镜像
cd .. && docker compose up -d --build
# http://localhost:8000
```

## WebSocket 协议

一条连接，二进制帧与 JSON 文本帧混用。

客户端 → 服务端：

| 帧 | 说明 |
|---|---|
| 二进制帧 | 音频，PCM16 单声道 16kHz（建议 ~100ms/帧） |
| `{"type":"ping"}` | 心跳 |
| `{"type":"interrupt"}` | 打断当前播报 |
| `{"type":"text","content":"..."}` | 文字直发（跳过 ASR，调试用） |

服务端 → 客户端：

| 帧 | 说明 |
|---|---|
| 二进制帧 | 合成音频，PCM16 单声道，采样率见 `turn_started.sample_rate` |
| `{"type":"pong"}` | 心跳应答 |
| `{"type":"asr_partial","text":"..."}` | 识别中间结果 |
| `{"type":"asr_final","text":"..."}` | 判停后的最终识别结果 |
| `{"type":"llm_token","text":"..."}` | LLM 增量 token |
| `{"type":"turn_started","sample_rate":22050}` | 本轮回答开始（前端重置播放队列） |
| `{"type":"turn_finished"}` | 本轮回答结束 |
| `{"type":"error","code":"...","message":"..."}` | 错误 |

## 扩展：新增一套对话方案

项目设计目标之一是多种数字人方案并存对比。新增方案只需三步：

1. 在 `app/solutions/` 下新建包，实现 `Solution` 协议（`name` + `async handle(transport, session_id)`）；
2. 级联类方案继承 `CascadeSolutionBase`，提供引擎工厂与 system prompt 即可复用整条管线；
   端到端（omni 类）模型不拆 ASR/TTS，直接实现方案层接口（可复用 `SessionShell` 接收脚手架）；
3. 在 `app/solutions/__init__.py` 的 `register_all()` 中注册：`register("omni", lambda s: OmniSolution(s))`；
4. 前端通过 `ws://<host>/ws/avatar/omni` 访问，与 cascade 并存切换。

新增供应商引擎：实现 `ASREngine` / `LLMEngine` / `TTSEngine` 协议（均为异步上下文管理器，
连接在 `__aenter__` 建立），经 `EngineSet` 由会话统一托管生命周期。

## 测试

后端（pytest，无需任何外部服务/密钥，61 个用例）：

```bash
pytest -q
# 板块单测：config / 消息协议 / 切句器 / 对话上下文 / 引擎行为与协议符合性
#           / 级联流水线时序（mock 引擎）/ 百炼 ASR·LLM·TTS 协议逻辑（FakeWS，不联网）
# 旅程测试：真实 HTTP/WS 栈 —— 文字轮 / 音频轮 / 打断 / 多轮上下文 / 心跳 / 异常分支
```

前端（vitest + jsdom，28 个用例）：

```bash
cd web && npm run test
# 重采样纯函数 / 播放器调度 / 会话消息流状态机 / App 组件冒烟
```

## 延迟观测

cascade 方案内置延迟埋点（uvicorn 日志）：

- `[TURN-LATENCY]`：用户判停/输入 → 首音频帧下发到前端的总耗时
- `[TTS-LATENCY]`：每句 TTS 的建连 / task-started / 首音频帧 / 任务总耗时

据此评估 TTS 连接复用、单任务流式等进一步的延迟优化。

## Roadmap

- **omni 端到端方案**：接入全双工语音大模型，与级联方案同框架对比延迟与效果
- **数字人形象渲染**：在音频通路之上叠加口型视频（Live2D / 推流拉流方案）
- **TTS 连接复用 / 单任务流式**：依据延迟埋点数据决策
- **生产化**：鉴权、限流、多并发会话管理
