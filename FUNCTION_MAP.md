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
| 可用 | 状态执行 | `thebridge_core.runner:StateRunner.run` | 原始截图 → 状态识别 → 定位 → `tap_match`/`back`，或 `observe` 仅转移状态 → 下一帧确认 |
| 可用 | 事件 | `thebridge_core.events:EventBus.emit`、`subscribe` | 运行时事实 → 内部订阅者及 SSE 投影；事件不参与控制决策 |
| 可用 | 资源预检 | `thebridge_core.artifacts:ArtifactStore.missing` | 插件/任务声明 → 源码树外固定 revision 缓存检查 |
| 可用 | ADB 设备 | `thebridge.builtin.android_adb.plugin:create_plugin` | entry point → 原始截图、ADB tap、返回键 → `android.device@1` |
| 可用 | 显式重启应用 | `AdbDevice.restart_app` | `run --restart-app PACKAGE` → 解析 launcher → force-stop 当前包 → start；登录后置条件仍交由任务 YAML 判断 |
| 可用 | macOS OCR | `thebridge.builtin.macos_vision.plugin:MacosVisionOcr.read` | 系统 Vision revision 2 → 原始帧坐标文本框 → `vision.text@1`；避免 revision 3 在演习边框文字下的错向识别，依赖 `macos-vision` extra |
| 可用 | 文本定位 | `thebridge.builtin.text_locator.plugin:TextLocator.locate` | `vision.text@1` + YAML 文本规则/锚点/顺序/文字高度偏移 → `vision.locator@1` |
| 可用 | OCR 复用 | `TextLocator.read_texts` | 普通文本规则和主线定位器共享同帧 OCR 与空白规范化 |
| 草案 | 主线定位 | `thebridge.builtin.azurlane_cn.campaign:CampaignLocator.locate` | YAML 关卡/模式/次数 → 章节比较、模式切换、关卡确认、连续作战次数校验 → `vision.locator@1` |
| 可用 | 演习选择 | `thebridge.builtin.azurlane_cn.exercise:select_opponent` | 四个完整 `Opponent` → 按主力+先锋总战力排序 → 选择不超过配置上限的最低者 |
| 草案 | 演习定位 | `thebridge.builtin.azurlane_cn.exercise_locator:ExerciseLocator.locate` | OCR 卡片/详情/次数 → 纯选择器 → 当前帧点击框；刷新等待新列表，次数为零退出 |
| 可用 | 委托选择 | `thebridge.builtin.azurlane_cn.commission:select_commission` | 任务 YAML 默认参数 + 用户覆盖 → `azurlane-cn.commission-selector@1` → 视觉候选排序 |
| 草案 | 棋盘选择 | `thebridge.builtin.azurlane_cn.battlefield:select_target` | 外部网格、行动范围、护卫计数 + `policy` → BFS 目标或安全移动前缀；默认 `clear_all` 清空护卫后打 Boss，`boss_first` 优先可攻击/可推进的 Boss；`Selection.reaches_target` 区分攻击/推进；尚未接自动图像解析 |
| 草案 | 地图观察接口 | `thebridge.builtin.azurlane_cn.map_observation:MapObserver`、`BoardObservation.validate_frame` | `azurlane-cn.map-observer@1` → 原图格子框/敌人/当前舰队/行动范围；严格关联当前帧；不绑定 OCR 或模型 |
| 草案 | 本地视觉输入 | `LocalMapObserver.observe`、`LocalMapObserverPlugin` | 原图与 JSON Schema 写入源码树外的本次会话目录 → `bridge.event.observation-required` → 等待结构化观察；当前人工/Codex填写，不是自动 CV |
| 草案 | 活动定位与决策 | `thebridge.builtin.azurlane_cn.event_locator:EventLocator.locate` | 同帧 OCR + MapObserver → `select_target` → 一队道中/二队 Boss/单次终点；等待切队和移动确认，攻击过渡帧仅等待战备页；本轮 Boss 胜利才允许完成 |
| 草案 | 活动持续任务 | `src/thebridge/builtin/azurlane_cn/tasks/event-stage.yaml` | 可配置单关 → 地图决策/多战/结算 → `completed`；SP 恢复后实测连续 5 场护卫及 Boss；SP 编队页自动确认待实现，仍交接 `needs-fleets`；地图观察依赖外部输入 |
| 可用 | 活动离线自检 | `check_event`、`check_map_observation` | `thebridge check` → 无设备模拟多战/切队延迟/攻击过渡帧/策略/当前帧约束/本地输入；真机验证范围见活动任务包说明 |
| 草案 | 国服任务包 | `thebridge.builtin.azurlane_cn.plugin:create_plugin` | entry point → 注册任务目录内的 YAML 状态图 |
| 草案 | 登录恢复 | `src/thebridge/builtin/azurlane_cn/tasks/login.yaml` | 等待认证提示 → 点击一次 → 主界面组合标识确认；重启由操作者显式触发 |
| 草案 | 活动单战 | `src/thebridge/builtin/azurlane_cn/tasks/event-battle.yaml` | 从稳定编队页启动；实测护卫/Boss、有无舰船掉落、经验结算和返回；与地图观察/舰队切换/终点点击分离 |
| 草案 | 活动进图 | `src/thebridge/builtin/azurlane_cn/tasks/event-enter.yaml` | 已选关卡详情→两水面舰队2/2→地图；沿用现有编成，不要求潜艇 |
| 草案 | 每日任务 | `src/thebridge/builtin/azurlane_cn/tasks/daily-raid.yaml`、`daily-rewards.yaml`、`daily-feed.yaml`、`daily-build.yaml`、`daily-campaign.yaml`、`daily-exercise.yaml` | CLI 直接加载；挑战从等级页、主线从章节页启动；演习支持任务/出击/演习入口；补食/轻型建造以领取对应每日奖励后返回为完成标记 |

## 当前主链

```text
thebridge run TASK.yaml
  → thebridge.execution:run_task
  → YAML TaskSpec + 插件配置
  → thebridge_core.runner:StateRunner.run
  → DeviceService.screenshot
  → LocatorService.locate
  → DeviceService.tap / back，或 observe（无设备输入）
  → 下一帧状态确认
  → EventBus
  → CLI 事件/截图日志（API 使用 REST/SSE）
```
