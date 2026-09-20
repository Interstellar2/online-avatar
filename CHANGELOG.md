# Changelog

本项目的所有重要变更都会记录在此文件中。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 可插拔方案架构：三层分离（`core/` 基础设施与引擎协议 → `solutions/` 方案注册表 → `ws/` 协议适配），支持在同一项目内对比多套数字人对话方案。
- `cascade` 级联方案：ASR → LLM → TTS 级联实现（阿里云百炼）。
- `echo` mock 方案：无需外部密钥即可运行的 mock 引擎，用于本地开发与测试。
- WebSocket 协议：音频走二进制帧（PCM16），控制消息走 JSON 文本帧；消息类型定义在 `app/ws_protocol.py`，与 `web/src/types.ts` 同步。
- Vue 3 前端（`web/`）：测试页、麦克风采集与音频播放，composables 按职责拆分。
- 测试体系：后端 pytest（mock 引擎 + TestClient 旅程测试）、前端 vitest（FakeWebSocket / FakeAudioContext 测试桩）。
- Docker 支持：`Dockerfile` 与 `docker-compose.yml`。

### Changed

- 引擎层协议统一为 async-iterator 风格 + 异步上下文管理器（`app/core/engines.py`）。
- 方案层通过 `core/transport.py` 的 `Transport` 协议抽象传输层，不直接依赖 FastAPI WebSocket 对象。

### Fixed

- 每轮对话的取消语义：interrupt → `TTSEngine.interrupt()` + 取消本轮 task；`turn_consumer` 用 `Task.cancelling()` 区分"会话关闭"与"轮次打断"。

## [0.1.0] - 未发布

- 初始版本，内容同 [Unreleased]。

[Unreleased]: https://github.com/your-org/online-avatar/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-org/online-avatar/releases/tag/v0.1.0
