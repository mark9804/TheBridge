# 活动单关任务包

## 当前结果与验证范围

- T1 在本轮开始前已三星；本轮 T2–T6 均已三星通关。
- SP 配队后已通关：一队击破 7 支护卫，Boss 出现即切二队接战，8 场均 S 胜利；最终选关页显示 Clear、今日次数 `0/1`。
- **真机已验证**：普通活动进图、护卫/Boss 战斗、S 胜利、有/无舰船掉落、EXP 结算、结算奖励弹窗退出；SP 修正后一次持续任务完成后 5 场护卫及 Boss，自动切队、选择目标并返回 `completed`。
- **离线已验证**：新 `event-stage.yaml` 持续状态图、结构化地图选择、移动确认、延迟切队、旧页面不重复点击、通关终态与配队交接。
- **介入边界**：地图观察仍由人工/Codex 填写 JSON。本次另有 3 次直接操作：确认配队后进图、一次落点修正（实际误移到相邻格）、切二队后平移地图；中途恢复 runner 一次，并非从入口到通关零介入的一次运行。
- **待验证/实现**：SP 自动配队页确认、自动地图解析与平移、全关零直接介入运行，以及真实战败撤退分支。

任务文件位于 `src/thebridge/builtin/azurlane_cn/tasks/`：`event-enter.yaml` 负责普通活动进图，`event-battle.yaml` 负责单场战斗，`event-stage.yaml` 将已支持的界面与地图决策连接成单关循环。完整任务不会自动切换上/下篇或连续选择下一关。

## 策略与现场经验

修改 `event-stage.yaml` 的 `parameters.plugins.builtin.azurlane-event`，保留其中已有 `rules`：

```yaml
stage: SP
policy: boss_first
mob_fleet: 1
boss_fleet: 2
```

`stage` 可选 `T1`–`T6` 或 `SP`。两支舰队编号必须不同。

- `clear_all`：先清护卫，当前敌舰计数为 0 且没有可见护卫后才转向 Boss，适合普通关卡的清图目标。每战重新观察增援，不能用旧计数减一推算。
- `boss_first`：Boss 出现后优先二队接近并攻击；如果护卫实际阻断路径，先交给一队处理，再尝试 Boss。SP 只需通关，不要求清空其他敌人。
- 一队负责道中、二队负责 Boss；没有补给点时，弹药为 0 不改变这项分工。
- 每次只点击本段终点，段内由游戏自动寻路。白色行动范围有限时仍需分段；不能把自动寻路理解为任意远点均可一步抵达。
- 本次 SP 已由用户确认无限移动，按 `mobility: unrestricted` 观察；二队直接点击可达 Boss 终点进入战斗。移动动画中的浅色格子不能单独证明步数受限。
- 切队后等待目标 `FLEET` 编号确认，不因第一张截图仍是旧队而再次点击切换。
- 攻击点击后等待战备页，过渡地图帧不再额外请求人工观察或重复点击；点击未生效仍受任务超时限制。切队会移动镜头，目标框必须来自新帧，不能复用旧坐标。
- 精英护卫也可能有大体积图标；Boss 需要结合标志和当前局面判断。残骸没有活敌的等级/强度标记，不应计入活敌。

当前策略按可达性和距离选择目标；观察结构中的 `strength` 可记录一/二/三标志，但尚不实现按强度排序或“打五次强敌”计数策略。

## 如何运行

先配好 SP 的两支水面舰队并手动进入地图，再启动完整任务。SP 的舰队页面与普通关卡不同；现已保存配好队的真实样本，但自动确认规则尚未实现，从该页面启动仍进入 `needs-fleets`，不会点击黄色“立刻前往”。潜艇不作为普通活动进图的前置条件。

在仓库根目录执行，替换 `SERIAL` 为设备序列号。日志目录必须是新的；以下命令将轨迹保存在仓库之外：

```sh
thebridge_event_run="$(mktemp -d /tmp/thebridge-event.XXXXXX)"
uv run --extra macos-vision thebridge run \
  src/thebridge/builtin/azurlane_cn/tasks/event-stage.yaml \
  --serial SERIAL \
  --plugins builtin.android-adb builtin.macos-vision builtin.azurlane-event builtin.azurlane-map-input \
  --timeout 3600 \
  --trace-dir "$thebridge_event_run/trace"
```

显式插件列表替换了默认列表，**不要再加入 `builtin.text-locator`**；它与活动定位插件都会提供 `vision.locator@1`。当前命令使用 macOS 系统 OCR；地图观察另走独立服务。

超时覆盖整次任务，包括等待人工地图输入的时间。运行期间保持游戏画面不被其他控制者操作。普通编队、战果、奖励、掉船和 EXP 界面由 DSL 连续处理，无需每场战斗重新启动任务。

## 如何提供地图观察

默认 `builtin.azurlane-map-input` 是本地结构化输入插件，尚不是自动图像识别。每当需要地图信息，它会输出 `bridge.event.observation-required` 事件，其中包含：

- `image_path`：本次原尺寸截图。
- `request_path`：当前帧编号、尺寸与输入要求。
- `response_path`：等待人工或 Codex 写入的 JSON 文件。
- `schema_path`：当前 `BoardObservation` JSON Schema。

默认目录在 `${XDG_CACHE_HOME:-~/.cache}/thebridge/map-input/` 下，每次运行独立建目录。以事件提供的实际路径为准：打开截图和请求，依据该帧内容填写并一次性保存完整 `response.json`。帧编号和尺寸必须与请求一致；旧帧响应不能用于新截图。

收到一份有效观察后，插件自动选择目标、决定是否切队，或点击当前范围内的移动/攻击终点；随后根据新帧确认结果。移动和战后通常会请求新的观察，切队先通过 `FLEET` 编号确认；攻击后的过渡帧只等待战备页。同帧的确认与下一次决策复用同一观察，不要求重复标注同一帧。

下面是 **synthetic 合成示例，仅解释字段，不是真实地图或可复用的点击坐标，不能直接提交给真机请求**：

```json
{
  "frame_id": 7,
  "width": 200,
  "height": 100,
  "stable": true,
  "active_fleet": 1,
  "origin": [0, 0],
  "guard_count": 1,
  "mobility": "bounded",
  "walkable_cells": [[0, 0], [1, 0], [2, 0]],
  "blocked_cells": [],
  "allowed_cells": [[1, 0], [2, 0]],
  "cells": [
    {"cell": [1, 0], "box": {"left": 70, "top": 20, "right": 110, "bottom": 60}},
    {"cell": [2, 0], "box": {"left": 120, "top": 20, "right": 160, "bottom": 60}}
  ],
  "enemies": [{"cell": [2, 0], "boss": false, "strength": 2}]
}
```

字段含义：

- `origin`、`cell` 和各格子列表统一使用零基 `[列, 行]` 网格坐标，例如 A1 为 `[0, 0]`；相机移动不改变格子身份。
- `box` 为本次原始截图的像素框，不能使用聊天预览缩放后的坐标。选择器最终点击的格子必须有唯一可见框。
- `walkable_cells` 是已确认的可通行地形，包含己方与敌人所在的可达目标格；未知地形不补猜。障碍或其他不可穿越占位放入 `blocked_cells`。
- `guard_count` 是本帧普通敌舰计数，可为 `null` 表示未知；`clear_all` 遇到未知计数会停止决策。
- `mobility: bounded` 必须提供白色行动范围 `allowed_cells`。没有白区时，只有明确知道行动不受限才能填 `unrestricted`，否则填 `unknown` 并停止决策。
- `stable: false` 表示仍在移动/索敌等动画中，不产生地图动作。`enemies` 仅列活敌；`boss` 需要正向判断，`strength` 可为 1、2、3 或 `null`。

## 结束、异常与扩展边界

终态 `completed` 要求本次运行已确认 Boss 战胜利，并返回目标关卡的纯选关界面。单独看到“作战模式”、一次 S 胜利或启动时已有 Clear，都不足以判定本轮通关。重启任务会丢失本轮 Boss 上下文；从任意战备/结算页恢复不能继承先前运行的通关证明。

`needs-fleets` 是等待用户配队/补充界面样本的交接终态；即使 CLI 发出 `bridge.run.finished`，也不代表通关。应检查 CLI 的 `final_state`（事件中的 `state`）和现场证据。

未知图像、无法确定的移动范围、不可达目标或未支持的战果会停止/超时并保留轨迹。现在仅有 S 胜利的真实门禁；SP 尚未发生战败，因此没有编造失败页或撤退确认词。后续取得真实失败样本后，再加入“从该关卡撤退”的分支。

确实卡死时，可显式选择 `--restart-app com.bilibili.azurlane` 配合 `login.yaml` 恢复；它只重启指定应用，不清除应用数据。OCR 超时本身不能触发杀游戏，也不会自动接续原任务。

地图服务协议为 `azurlane-cn.map-observer@1`：实现 `async observe(frame) -> BoardObservation` 的其他插件可以替换本地输入插件，活动 DSL 和选择器不必更换。目前没有接入自动 CV、远端模型服务或自动平移地图；这些是减少地图标注介入的后续实现点。模型和截图等运行资源不进入 Git。

## 剧情模式

活动选关页左下角点击“剧情模式”进入剧情列表，右下角“已完成阶段”是进度依据。金色书本/双剑表示已完成，白色书本表示可播放、白色双剑表示包含战斗，锁形节点显示前置条件。向左拖动可查看右侧后续节点；完成一条后本次活动会自动移动到下一条。长标题有滚动裁剪，不能把截断的 OCR 编号当成完整节点 ID。

`event-story.yaml` 负责已经进入的单条剧情：跳过 → 确认 → 等待后续剧情或返回列表。遇到自动战斗时保持等待、不发输入；战斗后再次出现剧情，则继续跳过与确认。跳过确认使用“是否确定跳过”约束，返回使用顶部剧情标题和完成计数；确认框尚未消失时不重复点击。

```sh
uv run --extra macos-vision thebridge run \
  src/thebridge/builtin/azurlane_cn/tasks/event-story.yaml \
  --serial SERIAL --timeout 300 \
  --trace-dir /tmp/thebridge-story-new-run
```

先手动选择一条未完成剧情，轨迹目录使用新目录。任务也能从正在播放/自动战斗中恢复；如果已在剧情列表，则不点击，直接到 `returned`。该终态只证明返回列表，新增完成必须比较运行前后的计数，不能把启动时已有进度当成本次完成。

2026-10-24 首次单条任务试验从 `0/26` 推进到 `6/26`：EPS-1、EP1-1～EP1-4 为纯剧情；EP2-1 实测剧情 → 自动短战斗 → 后续剧情 → 列表。EP1-3、EP1-4 各由单次 YAML 自动返回；EP2-1 在补入循环和修正返回 OCR 门禁时分段恢复。后续全量任务的完整进度与混合关卡验证见下文。

单条任务不负责选关或比较进度基线。未知战备/奖励/失败页保持等待并受总超时约束，不套用普通活动战斗的领奖流程。

### 全部剧情扫描

从剧情列表启动 `event-story-all.yaml`，启用专用定位插件：

```sh
thebridge_story_run="$(mktemp -d /tmp/thebridge-story.XXXXXX)"
uv run --extra macos-vision thebridge run \
  src/thebridge/builtin/azurlane_cn/tasks/event-story-all.yaml \
  --serial SERIAL \
  --plugins builtin.android-adb builtin.macos-vision builtin.azurlane-story \
  --timeout 2400 --trace-dir "$thebridge_story_run/trace"
```

当前帧中央文本提供候选标题，STORY 锚点和文字高度定位图标；金色标为完成，白色标为可入，“完成 EP…”前置条件标为锁定。图标被屏幕裁断时暂不点击，滚动标题不要求完整 EP 前缀。

可见未完成节点优先进入；没有候选时向左拖动，到边界反向。拖后连续两帧布局稳定才继续；边界必须同时满足位置和节点标识未变，不能只凭等距图标仍在原位置判断。`parameters.plugins.builtin.azurlane-story.swipe_region` 为相对当前画面的拖动矩形，`max_swipes_without_progress` 限制无进度扫描。遍历两端仍找不到候选会停止并保留轨迹。

每次选关记录当前完成数，返回后必须增长再继续；计数达到总数才进入 `completed`。进度数字根据 OCR 定位的文字框局部放大重读，处理实机 `7` 被全图识别成 `1` 的情况。OCR 无有效结果时等待，不推测进度或反复进入旧节点。默认插件列表中不要混入 `builtin.text-locator`，避免重复提供定位服务。

2026-10-24 已从 `6/26` 完成至 `26/26`，5 个心智魔方奖励显示已领取。最后 12 条播放由同一进程连续完成，两次实际边界反向扫描找回了漏识节点；本轮前半段修复 OCR/锁定条件/编号边界时有多次任务恢复，最后奖励分支另外补入，不是整轮零干预一次运行。

完成奖励仅匹配“获得道具”且含“心智魔方”，关闭后等待纯列表；终态支持 OCR 把 `26/26已领取` 合并为同一段文字。最终奖励与终态规则已用真实截图回放验证（重复奖励帧不重复点击），实机终态补测期间设备被其他操作带离剧情页，未取得最终修订版的完整实机正常退出记录。运行时应保持设备由一个控制者操作；结束证据以剧情完成计数为准。
