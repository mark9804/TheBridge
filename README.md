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
