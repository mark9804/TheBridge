# TheBridge

「初次见面，指挥官。」

TheBridge 是~~又~~一个碧蓝航线游戏自动化工具，旨在通过更好的架构设计实现更加智能与健壮的自动化游戏行为。

[`thebridge-core`](packages/core/README.md) 参考 [Cordis](https://github.com/cordiverse/cordis) 与 [Koishi](https://github.com/koishijs/koishi) 的设计思路，是面向 Android 游戏的可插拔视觉自动化元框架。它只负责状态图、插件生命周期、事件和资源预检；设备控制、OCR、视觉模型及具体游戏任务由插件提供。

## 开发启动

后端：

```bash
uv sync
uv run thebridge check
uv run thebridge serve
```

仅在需要连接设备时启用 ADB 插件：

```bash
THEBRIDGE_PLUGINS=builtin.android-adb \
THEBRIDGE_SERIAL=<adb-serial> \
uv run thebridge serve
```

ADB 插件使用系统 `adb`，也可通过 `THEBRIDGE_ADB` 指定路径。

前端：

```bash
cd web
pnpm install
pnpm dev
```

开发时 Vite 将 `/api` 转发到 `http://127.0.0.1:8000`。生产构建后，后端会直接托管 `web/dist`：

```bash
cd web && pnpm build
cd .. && uv run thebridge serve
```

## 仓库结构

- `packages/core/`：独立构建的 `thebridge-core` Python 包。
- `src/thebridge/`：TheBridge 产品后端和官方任务插件。
- `web/`：Vue 3 前端。

稳定入口见 [FUNCTION_MAP.md](FUNCTION_MAP.md)。

## 许可证

TheBridge 使用 AGPL-3.0-only。
