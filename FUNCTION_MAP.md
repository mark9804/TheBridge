# 函数地图

> 只记录跨文件稳定入口和真实复用点。新增入口或改变调用方向时同步更新。

| 状态 | 领域 | 稳定入口 | 调用方向与边界 |
|---|---|---|---|
| 可用 | CLI | `thebridge.__main__:main` | `serve`、`validate`、`check` 三个开发入口 |
| 可用 | API | `thebridge.app:app` | FastAPI 生命周期 → 插件激活 → REST/SSE；构建后托管 `web/dist` |
| 可用 | 插件发现 | `thebridge_core.plugins:PluginHost.discover` | Python entry points `thebridge.plugins` → 轻量插件对象 |
| 可用 | 插件生命周期 | `PluginHost.start`、`PluginHost.stop` | 服务依赖排序 → 资源预检 → 激活；停止时逆序撤销服务和任务 |
| 可用 | 任务 DSL | `thebridge_core.dsl:parse_task`、`load_task` | YAML → Pydantic 校验 → `TaskSpec` |
| 可用 | 状态执行 | `thebridge_core.runner:StateRunner.run` | 原始截图 → 状态识别 → 定位 → 点击 → 下一帧确认 |
| 可用 | 事件 | `thebridge_core.events:EventBus.emit`、`subscribe` | 运行时事实 → 内部订阅者及 SSE 投影；事件不参与控制决策 |
| 可用 | 资源预检 | `thebridge_core.artifacts:ArtifactStore.missing` | 插件/任务声明 → 源码树外固定 revision 缓存检查 |
| 可用 | ADB 设备 | `thebridge.builtin.android_adb.plugin:create_plugin` | entry point → 原始截图与 ADB tap → `android.device@1` |

## 当前主链

```text
YAML TaskSpec
  → thebridge_core.runner:StateRunner.run
  → DeviceService.screenshot
  → LocatorService.locate
  → DeviceService.tap
  → 下一帧状态确认
  → EventBus
  → REST/SSE/统计插件
```
