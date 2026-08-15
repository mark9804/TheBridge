# TheBridge 开发约束

- 始终使用简体中文交流；代码标识符和代码注释使用英文。
- Python 使用 uv，前端使用 pnpm；Vue 组件只使用 Composition API 和 TypeScript。
- 开始修改前先读 `FUNCTION_MAP.md`，新增跨文件入口时同步更新。
- `DEVELOPMENT_LOG.md` 记录本地开发过程并保持 Git 忽略；一次性检查放在 `local_tests/` 或 `/tmp`，用后删除。
- Git 不保存截图、模板、模型、APK、Dex 或其他运行时二进制。资源必须由显式同步命令写入源码树之外的缓存。
- 所有游戏操作使用“截图 → 识别 → 操作 → 下一帧确认”，禁止用固定休眠猜测页面状态。
- 坐标始终使用原始截图坐标；核心层不得假设 1280×720 或 16:9。
- 核心只维护插件生命周期、DSL、执行器、事件和资源预检。OCR、视觉模型、设备输入和游戏任务均通过插件接入。
- `packages/core` 是独立 `thebridge-core` distribution，只能被 `thebridge` 产品包单向依赖；禁止 `thebridge_core` 反向导入 `thebridge`。
- 只在出现第二个真实调用者时抽取工具函数；不为假想兼容性增加包装层。
- 仓库不维护常规 `tests/` 套件。长期检查通过 `thebridge check`、Ruff 和前端类型构建完成。
