# 函数地图

> 只记录跨文件稳定入口和真实复用点。新增入口或改变调用方向时同步更新。

| 状态 | 领域 | 稳定入口 | 调用方向与边界 |
|---|---|---|---|
| 可用 | CLI | `thebridge.__main__:main` | `serve`、`validate`、`run`、`check`；`run` 接收任务路径、设备、插件配置和日志目录 |
| 可用 | 任务执行入口 | `thebridge.execution:run_task` | YAML 参数与 JSON 插件配置 → 插件激活/资源检查 → `StateRunner.run` → 插件停止 |
| 可用 | 运行记录 | `thebridge.execution:RecordingDevice` | 保留原尺寸截图；透传 `tap`/`back`；`run_task` 输出事件并可写入 `events.jsonl` |
| 可用 | API | `thebridge.app:app` | FastAPI 生命周期 → 插件激活 → REST/SSE；构建后托管 `web/dist` |
| 可用 | 插件发现 | `thebridge_core.plugins:PluginHost.discover` | Python entry points `thebridge.plugins` → 轻量插件对象 |
| 可用 | 插件生命周期 | `PluginHost.start`、`PluginHost.stop` | 服务依赖排序 → 资源预检 → 激活；停止时逆序撤销服务和任务 |
| 可用 | 任务 DSL | `thebridge_core.dsl:parse_task`、`load_task` | YAML → Pydantic 校验 → `TaskSpec` |
| 可用 | 状态执行 | `thebridge_core.runner:StateRunner.run` | 原始截图 → 状态识别 → 定位 → `tap_match`/`back` → 下一帧确认 |
| 可用 | 事件 | `thebridge_core.events:EventBus.emit`、`subscribe` | 运行时事实 → 内部订阅者及 SSE 投影；事件不参与控制决策 |
| 可用 | 资源预检 | `thebridge_core.artifacts:ArtifactStore.missing` | 插件/任务声明 → 源码树外固定 revision 缓存检查 |
| 可用 | ADB 设备 | `thebridge.builtin.android_adb.plugin:create_plugin` | entry point → 原始截图、ADB tap、返回键 → `android.device@1` |
| 可用 | macOS OCR | `thebridge.builtin.macos_vision.plugin:MacosVisionOcr.read` | 系统 Vision revision 2 → 原始帧坐标文本框 → `vision.text@1`；避免 revision 3 在演习边框文字下的错向识别，依赖 `macos-vision` extra |
| 可用 | 文本定位 | `thebridge.builtin.text_locator.plugin:TextLocator.locate` | `vision.text@1` + YAML 文本规则/锚点/顺序/文字高度偏移 → `vision.locator@1` |
| 可用 | OCR 复用 | `TextLocator.read_texts` | 普通文本规则和主线定位器共享同帧 OCR 与空白规范化 |
| 草案 | 主线定位 | `thebridge.builtin.azurlane_cn.campaign:CampaignLocator.locate` | YAML 关卡/模式/次数 → 章节比较、模式切换、关卡确认、连续作战次数校验 → `vision.locator@1` |
| 可用 | 演习选择 | `thebridge.builtin.azurlane_cn.exercise:select_opponent` | 四个完整 `Opponent` → 按主力+先锋总战力排序 → 选择不超过配置上限的最低者 |
| 草案 | 演习定位 | `thebridge.builtin.azurlane_cn.exercise_locator:ExerciseLocator.locate` | OCR 卡片/详情/次数 → 纯选择器 → 当前帧点击框；刷新等待新列表，次数为零退出 |
| 可用 | 委托选择 | `thebridge.builtin.azurlane_cn.commission:select_commission` | 任务 YAML 默认参数 + 用户覆盖 → `azurlane-cn.commission-selector@1` → 视觉候选排序 |
| 草案 | 国服任务包 | `thebridge.builtin.azurlane_cn.plugin:create_plugin` | entry point → 注册军事委托和每日任务状态图 |
| 草案 | 每日任务 | `src/thebridge/builtin/azurlane_cn/tasks/daily-raid.yaml`、`daily-rewards.yaml`、`daily-feed.yaml`、`daily-build.yaml`、`daily-campaign.yaml`、`daily-exercise.yaml` | CLI 直接加载；挑战从等级页、主线从章节页启动；演习支持任务/出击/演习入口；补食/轻型建造以领取对应每日奖励后返回为完成标记 |

## 当前主链

```text
thebridge run TASK.yaml
  → thebridge.execution:run_task
  → YAML TaskSpec + 插件配置
  → thebridge_core.runner:StateRunner.run
  → DeviceService.screenshot
  → LocatorService.locate
  → DeviceService.tap / back
  → 下一帧状态确认
  → EventBus
  → CLI 事件/截图日志（API 使用 REST/SSE）
```
