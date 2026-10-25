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
THEBRIDGE_PLUGINS=builtin.azurlane-cn,builtin.android-adb \
THEBRIDGE_SERIAL=<adb-serial> \
uv run thebridge serve
```

ADB 插件使用系统 `adb`，也可通过 `THEBRIDGE_ADB` 指定路径。当前军事委托状态图仍需要
`azurlane-cn.ui-locator@1`；未启用视觉插件时任务会明确显示为 unavailable。

委托选择顺序的默认值声明在任务 YAML 中，用户可用逗号分隔覆盖：

```bash
THEBRIDGE_COMMISSION_PRIORITY=night_long,gem,cognitive_chip,oil,cube,shortest
```

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

## 真机任务执行

macOS 上可使用系统 Vision OCR；ADB 保留设备原始截图尺寸：

```bash
uv sync --extra macos-vision
uv run --extra macos-vision thebridge run \
  src/thebridge/builtin/azurlane_cn/tasks/daily-raid.yaml \
  --serial DEVICE_SERIAL --timeout 180 --trace-dir /tmp/thebridge-daily-raid
```

将 `DEVICE_SERIAL` 替换为 ADB 设备序列号。当前任务均为草案，需要先手动进入对应页面：

| YAML | 运行前置条件 | 完成标记 |
|---|---|---|
| `daily-raid.yaml` | 已进入每日挑战等级页，有剩余次数且可快速挑战 | 领取挑战奖励后返回挑战卡片页 |
| `daily-rewards.yaml` | 已在任务的「每日」页，并有可见的「领取」按钮 | 点击全部领取、关闭奖励后回到任务页 |
| `daily-feed.yaml` | 已在「每日」任务页，后宅食量为 `0/40000`，持有「食物1000」 | 补充一份食物后领取对应每日奖励，再回到任务页 |
| `daily-build.yaml` | 已在「每日」任务页，可见「建造舰船1次」；允许消耗 600 物资和 1 个心智魔方 | 轻型舰建造一次后领取对应每日奖励，再回到任务页 |
| `daily-campaign.yaml` | 已在主线章节页；目标关卡已开放、已有可用舰队 | 连续作战结算次数达到配置值后返回章节页 |
| `daily-exercise.yaml` | 已在主界面、每日任务、出击或演习页；已有可用演习舰队 | 实际演习次数为 `0/10` 后退出演习页 |
| `login.yaml` | 游戏启动中或已在登录认证页，账号保持登录 | 点击认证提示后确认主界面的出击、任务和建造入口 |
| `event-enter.yaml` | 已选定活动关卡并打开详情页；两支水面舰队可出击 | 确认舰队数 `2/2` 后进入地图，等待索敌动画结束 |
| `event-battle.yaml` | 已在活动敌舰的稳定编队出击页 | 单场结算后返回地图或选关页；已实测护卫、Boss及单艘掉落展示 |
| `event-stage.yaml` | 指定单关的选关/详情/已支持编队页或地图；SP 从已配队进入的地图开始 | 持续地图决策与多战结算；实测 SP 恢复后连续完成 5 场护卫及 Boss；地图仍由人工/Codex 输入 |
| `event-story.yaml` | 已进入单条活动剧情，可从播放或自动战斗中恢复 | 跳过/确认循环，战斗期间等待，返回剧情列表；是否新增完成以右下角计数增长为准 |
| `event-story-all.yaml` | 已在活动剧情列表 | OCR文字+图标颜色选择未完成节点，必要时双向拖动；逐条核对计数，满进度退出；使用 `builtin.azurlane-story` |

后宅补食流程当前只覆盖上述饥饿起点；成功依据是领取对应每日奖励后返回任务页。
食物库存不足或文字未识别时可能超时，需要人工处理。
建造流程只处理「建造舰船1次」，确认框需同时识别轻型舰和上述消耗；
任务已可领取时直接领奖。

领取每日任务奖励（执行其他任务时替换 YAML 文件名，并使用新的日志目录）：

```bash
uv run --extra macos-vision thebridge run \
  src/thebridge/builtin/azurlane_cn/tasks/daily-rewards.yaml \
  --serial DEVICE_SERIAL --timeout 120 --trace-dir /tmp/thebridge-daily-rewards
```

`parameters.locators` 在任务 YAML 中配置文本规则、同排锚点和候选顺序；
`offset: [x, y]` 按识别文本框高度偏移点击位置。OCR 对小字仍有漏识别；
未匹配时会等待至超时，不会据此认定任务已完成。当前尚不支持全自动菜单遍历。

`--config PATH` 接受「插件 ID → 配置」的 JSON 对象；可配置 `builtin.android-adb` 的
`adb_path` 等参数，显式传入 `builtin.text-locator.rules` 会整体替换 YAML 的定位规则。
`--plugins ID [ID ...]` 替换启用插件列表，默认是 `builtin.android-adb`、
`builtin.macos-vision`、`builtin.text-locator`。接入其他已安装的 OCR 插件时，
用提供 `vision.text@1` 的插件 ID 替换 `builtin.macos-vision`，并通过 `--config` 传入配置。

主线任务使用 `builtin.azurlane-campaign` 替换通用文本定位插件：

```bash
uv run --extra macos-vision thebridge run \
  src/thebridge/builtin/azurlane_cn/tasks/daily-campaign.yaml \
  --serial DEVICE_SERIAL --timeout 300 --trace-dir /tmp/thebridge-daily-campaign \
  --plugins builtin.android-adb builtin.macos-vision builtin.azurlane-campaign
```

在该 YAML 的 `parameters.plugins.builtin.azurlane-campaign` 配置：

```yaml
stages:
  hard: "12-2"
  normal: "12-4"
mode: hard
runs: 3
```

`mode` 选择 `hard` 或 `normal`，`runs` 为 1–3。程序读取当前章号后逐页寻找目标，
并识别左下角模式切换按钮；按钮文字指向要切换的模式。
出击前校验关卡与连续作战次数，沿用现有舰队。
次数加减按钮按同排数字文字高度定位，已用当前平板截图校验，实际加减动作仍待验证。
困难 `12-2` 已分段真机执行并核对三次结算，完整状态图通过真实截图回放；
完整 YAML 的单次连续实机运行、普通 `12-4` 的实际战斗仍待验证。
任务默认插件配置来自 `parameters.plugins`；JSON 配置按插件顶层字段覆盖，
显式传入 `stages` 或 `rules` 会整体替换对应字段。CLI `--serial` 优先于配置。
超时会停止本次脚本，不会自动取消游戏内已启动的连续作战。

确认游戏卡死时，先停止原任务，再显式重启游戏并运行登录流程：

```bash
uv run --extra macos-vision thebridge run \
  src/thebridge/builtin/azurlane_cn/tasks/login.yaml \
  --serial DEVICE_SERIAL --restart-app com.bilibili.azurlane \
  --timeout 180 --trace-dir /tmp/thebridge-login
```

包名应与设备实际安装的版本一致。重启只终止目标游戏包并启动其 launcher，保留应用数据。
登录任务等待“触摸屏幕执行权限认证”，点击一次后等待主界面确认；不会凭启动命令成功
认定恢复完成。当前已验证同账号直接认证回首页；阻挡登录的额外页面会等待至超时，
首页出现后延迟弹出的通知仍需接续任务处理。普通任务超时不会自动触发重启，
恢复后应重新识别关卡状态再续跑。

选定活动关卡并打开详情后，运行进图任务：

```bash
uv run --extra macos-vision thebridge run \
  src/thebridge/builtin/azurlane_cn/tasks/event-enter.yaml \
  --serial DEVICE_SERIAL --timeout 120 --trace-dir /tmp/thebridge-event-enter
```

该任务从「关卡产出」详情页点击「立刻前往」，识别舰队选择页的
「可出击舰队数：2/2」后再次前往，不要求潜艇编队；最后确认地图「迎击」且索敌动画已消失。
T2、T3 的真实入口均已以 5 帧、2 次点击完成。选关仍由操作者完成，任务不会自动选择下一关。

在地图上选中敌舰、进入稳定的编队出击页后，运行单战任务：

```bash
uv run --extra macos-vision thebridge run \
  src/thebridge/builtin/azurlane_cn/tasks/event-battle.yaml \
  --serial DEVICE_SERIAL --timeout 300 --trace-dir /tmp/thebridge-event-battle
```

活动棋盘的 `battlefield.select_target` 当前接收结构化网格观察，默认 `policy="clear_all"`，
用四邻域 BFS 选择最近可达护卫，确认计数归零后才允许 Boss。
SP 只要求通关时，调用者可显式传入 `policy="boss_first"`：优先攻击可达 Boss，
或在行动范围内朝 Boss 分段推进；Boss 尚未出现、不可达或无法安全推进时继续选择护卫。
该策略不要求护卫计数归零或已知，仍要求已知行动范围和可通行地图。
当前白区内无可攻击目标时，沿已知地图选择目标并只返回本步允许范围内的移动前缀；
`Selection.reaches_target` 为假时仅移动到 `path[-1]`，不能直接点击远处的 `target.cell`。
每段只点击一个终点，段内路线由游戏自动寻路。T1 实测超出白区的终点会提示
“目标点超出移动范围”；不能把游戏自动寻路等同于取消本次行动范围限制。
每次战斗后需重新观察增援和左上角敌舰计数；`clear_all` 下计数未知或大于零时不会选择 Boss。
行动范围区分 `bounded`、`unrestricted`、`unknown`；没有白区不自动等于无限移动。
目前网格和计数仍由人工观察提供，尚未实现全自动地图解析与清图。
`event-battle.yaml` 已实测护卫、Boss 及有/无舰船掉落的结算路径。
T3 里士满掉落页已实测使用 `SHIPTYPE` 加「舰名」识别继续结算。
当前胜利门禁要求「大获全胜」（S）；其他评级与真实失败处理尚未验证，未匹配时会等待至超时。
经验结算后先检查是否出现 `SETTLE REWARDS` 结算奖励弹窗：有则点击「离开」，
否则通过 `observe` 仅观察确认返回地图或选关页。两条分支均已在 T6 真机验证；
其中 Boss 战以 20 帧、6 个动作通过结算奖励弹窗并点击「离开」。
T5 Boss 战后的同类弹窗此前由人工点击「离开」，现已沉淀为上述分支。
T1 已按七支护卫全部清除、普通敌舰计数归零、再击破 Boss 的顺序完成三星，选关页显示 Clear。
T2 已由一队清除八支护卫，再由二队击破 Boss；T2 至 T6 均已显示 Clear 三星。
SP 配队后已通关：一队打 7 支护卫，Boss 出现后切二队直接接战，8 场均 S；
选关页显示 Clear、今日次数 `0/1`。本次 SP 已确认无限移动，未清空剩余护卫。
当前清图规则为一队清道中、二队打 Boss；没有补给点时继续执行道中任务，不因弹药匮乏换队。
T1–T6 真机流程由人工读图驱动地图操作，入口和单战 YAML 独立运行；SP 使用下述持续任务。
实测入场动画期间点击可能无效，当前 runner 会等待至超时，不会自动重试该点击。

现已整理为 `event-stage.yaml` 单关持续任务：`builtin.azurlane-event` 消费地图观察，
选择目标、单次移动终点和舰队，等待新帧确认后继续；普通结算由 DSL 串联，
无需每场战斗重新启动命令。默认 SP/`boss_first`，可在 YAML 中修改关卡、策略与舰队职责。
只有本次运行确认 Boss 胜利并返回目标选关页才到达 `completed`；`needs-fleets` 仅表示需要配队。

地图视觉仍是待接环节。默认 `builtin.azurlane-map-input` 将原图和 JSON Schema 写入本机缓存，
等待人工或 Codex 提供结构化观察；其他视觉插件可实现 `azurlane-cn.map-observer@1` 替换它。
持续任务已在 SP 真机验证：修正攻击后过渡帧的等待逻辑后，一次运行连续完成后 5 场护卫及 Boss，
以 `completed` 退出。整次尝试仍有进图、落点修正、地图平移 3 次直接介入，并恢复 runner 一次；
所有地图视觉 JSON 均由 Codex 提供，尚无自动棋盘解析、地图平移或真实战败撤退分支。
SP 配队页已有正例，自动确认仍待实现。运行命令、配置与观察输入格式见
[活动任务包说明](docs/ACTIVITY_TASKS.md)。

剧情模式使用独立 `event-story.yaml`，复用默认 OCR/TextLocator，无需地图插件。
已实测进度 `0/26` → `6/26`，包含 EP2-1 的剧情、自动短战斗和后续剧情；
纯剧情可单次运行返回，混合关卡本次分段恢复，最终循环版已通过真实帧回放。
单条任务的 `returned` 只表示回到列表，不自动宣称计数增长。
批处理任务 `event-story-all.yaml` 另用节点颜色/锁定标记选关，按当前画面扫描与拖动，
逐条核对完成计数；配置与启动方式见活动任务包说明。
本次活动已实测 `26/26` 并领取 5 个心智魔方；最后 12 条连续自动播放，
两次边界反向找回漏识节点。整轮包含调试恢复，最终领奖/终态修订以真实截图回放验证。

军事演习使用独立的对手选择插件：

```bash
uv run --extra macos-vision thebridge run \
  src/thebridge/builtin/azurlane_cn/tasks/daily-exercise.yaml \
  --serial DEVICE_SERIAL --timeout 1800 --trace-dir /tmp/thebridge-daily-exercise \
  --plugins builtin.android-adb builtin.macos-vision builtin.azurlane-exercise
```

在 YAML 的 `parameters.plugins.builtin.azurlane-exercise` 中设置 `max_power: 26000`。
四个对手的主力和先锋战力都识别完整后，选择总和最低且不超过上限的一位；
详情页再次核对总和，再开始演习。沿用当前舰队，循环消耗界面显示的剩余次数。

无人符合时才立即更换对手，确认列表变化后再做决策。
`max_refreshes: 5` 限制本次运行的主动刷新次数，游戏另行限制每日最多五次；
界面未显示今日剩余刷新额度，不将配置值当作今日剩余值。中断后重启需用
`--config` 扣除已用刷新次数。额度用完仍无合格者时明确报错停止；
刷新后列表未变化或 OCR 不完整时等待，最终受运行超时限制。
战力上限只约束选择，不等同于胜率保证。
已在原始 3200×2136 真机上验证选人、主动刷新、结算及次数归零退出；
其他屏幕布局仍需验证。

每次运行请使用新的 `--trace-dir`：目录内保存原始尺寸 PNG 和 `events.jsonl`，
已有事件日志会拒绝覆盖。终端输出事件和最终 JSON 结果；截图与日志应放在 Git 仓库外。

## 仓库结构

- `packages/core/`：独立构建的 `thebridge-core` Python 包。
- `src/thebridge/`：TheBridge 产品后端和官方任务插件。
- `web/`：Vue 3 前端。

稳定入口见 [FUNCTION_MAP.md](FUNCTION_MAP.md)。

## 许可证

TheBridge 使用 AGPL-3.0-only。
