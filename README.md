# M20 Nav2 Navigation Policy

本项目把独立部署的 ROS 2 Nav2 适配为具身安全应用挑战赛 M20 Runner 所要求的
`openpi-websocket/pi0.5` Policy。当前阶段负责 Q01–Q24 的底盘导航，不执行机械臂、
夹爪或 Q15 蹲起动作；Runner 攻击模式由显式环境变量控制，默认关闭。

## 约束

- 不修改 `/home/youlika/navigation2_reproduction` 中的 Nav2 或 Isaac Sim 源码。
- 项目部署到独立目录，使用独立 `ROS_DOMAIN_ID`。
- 地图由赛题 Isaac Sim USD 场景的碰撞几何投影生成。
- 每道题都运行并保存视频，Runner 任务失败时也保留产物。
- 第一阶段目标是 24 道题中至少 12 道到达公开路线的导航终点。

## 当前官网成绩

截至 2026-09-04，竞赛官网当前实得分为 **12 分**。该数值是官网评分结果，与下方
离线统计的导航到达率、官方文件对数量和严格几何验收率是不同口径。

## 最新无攻击回归

2026-09-01 使用当前代码、每题独立 Runner/Isaac Sim 进程完成 Q01–Q24 全量回归，
结果目录为 `results_20260901_192331_535704189/`。24 题均确认
`attack_mode=off`，总墙钟时间 4 小时 26 分 54 秒。

| 口径 | 结果 | 说明 |
|---|---:|---|
| Policy 导航状态 | **16/24（66.7%）** | 以最终 `navigation_status.json` 的 `navigation_reached=true` 为准 |
| 导航成功且官方文件对有效 | **15/24（62.5%）** | Q16 已导航到达，但 Runner 后续超时、没有正式文件对 |
| 严格提交级导航 | **14/24（58.3%）** | 再排除 Q15：最小距离 0.2657 m，略高于 0.25 m 几何阈值 |
| 官方提交文件对 | **17/24** | 17 个 HDF5 均包含 `/metadata` 且 `/data` 中只能有 `demo_0` |

按 Policy 状态成功的任务为 Q01、Q02、Q03、Q05、Q06、Q07、Q13、Q14、Q15、Q16、
Q18、Q19、Q20、Q22、Q23、Q24。失败分为两类：Q04、Q09 实际进入导航但未到达；
Q08 因系统 OOM 未启动，Q10–Q12 因官方路线与膨胀障碍相交未启动，Q17/Q21 因官方
题包攻击索引 SHA-256 不匹配未启动。72 个 `episode/overview/chase` 视频均可解码；
上述 7 个未完成正式录像的任务使用明确标记的 5 秒诊断占位视频。

与上一份完整无攻击批次 `results_20260831_171329_021058160/` 相比，Policy 导航状态从
14/24（58.3%）提高到 16/24（66.7%），净增加 2 题；严格提交级结果从 12/24（50.0%）
提高到 14/24（58.3%）。Q02、Q05、Q06、Q07 由失败转为成功；Q04 因本轮异常提前结束
而退化，Q08 是 OOM，不属于算法退化。完整逐题数据和限制见
[TEST_REPORT_20260901.md](TEST_REPORT_20260901.md)。

本轮代码修改包括：

- 新增只向前行驶的版本化 `nav2_forward_v1.yaml`，仅供 Q02/Q05/Q06/Q07 使用；
- 为 Q05/Q09 新增由 Isaac Sim USD 碰撞几何生成、SHA-256 锁定的单题地图和绕行路线，
  路线覆盖只能修改中间航点，必须保留官方最终目标；
- 扩展任务清单校验，统一校验 profile、地图 YAML、PGM 和路线文件，并拒绝路径越出
  `config/`；
- 扩展 USD 建图工具的单题模式、端点清理和自定义输出名；Runner 启动时自动选择单题
  地图，并在结果目录保存实际地图快照；
- 增加相应单元测试、真实 Runner 测试报告和 Q05 三阶段绕行验证记录。

## 数据流

```text
Runner observation
  ├─ state[0:12] -> TF / Odometry
  └─ prompt       -> Qxx / public route
                         |
                         v
                 SmacPlanner2D + MPPI Omni
                         |
                         v
                     /cmd_vel
                         |
                         v
                actions[0:3], actions[3:10]=0
```

开发过程、真实 Runner 问题和验收结果记录在 [DEVELOPMENT.md](DEVELOPMENT.md)，完整
依赖见 [DEPENDENCIES.md](DEPENDENCIES.md)。

## 目录结构

```text
nav2_policy/
├── config/profiles/              # 只增不改的版本化 Nav2 参数 profile
├── config/tasks/Q01.json…Q24.json # 每题独立配置、频率、地图/路线引用与回归锁
├── config/tasks/Q05/             # Q05 的 USD 地图、元数据和东侧绕行路线
├── config/tasks/Q09/             # Q09 的 USD 地图、元数据和绕行路线
├── launch/m20_nav2.launch.py     # 独立地图服务器和 Nav2 bringup
├── scripts/                      # 启停、单题和批量执行器
├── build_overview_runtime.py     # 从校验过的官方 runtime 构建调试副本
├── compile_tasks.py              # 编译 Q01–Q24 公开路线
├── task_config.py                # 独立配置及 profile SHA-256 校验
├── check_nav2_ready.py           # Lifecycle/Action Server 无目标预检
├── generate_usd_maps.py          # Isaac Sim USD 碰撞几何投影建图
├── navigation_bridge.py          # Runner 状态、TF/Odom、Nav2 Action 桥
├── policy_server.py              # Runner WebSocket Policy
├── summarize_results.py          # JSON/Markdown 验收汇总
├── tests/                         # 任务元数据与验收单元测试
├── TEST_REPORT_20260830.md        # P0 修改与正式 Runner 测试报告
├── TEST_REPORT_20260901.md        # 隔离优化、Q05 修复与 24 题完整回归
├── requirements-policy.txt       # Policy Python 精确依赖
└── DEPENDENCIES.md               # ROS/Nav2/Isaac/系统依赖
```

## 部署

以下示例使用本次验证服务器的目录。部署到其他目录时，需要设置 `PROJECT_DIR` 和
`NAV2_ROOT`，并调整 `scripts/run_runner_task.sh` 顶部的题目数据、Runner 输出与配置
路径。

### 1. 克隆代码

```bash
DEPLOY_ROOT='/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy'
cd "$DEPLOY_ROOT"
git clone https://github.com/selfevolv/nav2_policy.git nav2_policy
cd nav2_policy
chmod u+x scripts/*.sh *.py
```

### 2. 准备 ROS 2/Nav2 环境

当前部署复用已有 Nav2 覆盖层，但不会修改其源码：

```bash
export PROJECT_DIR="$PWD"
export NAV2_ROOT='/home/youlika/navigation2_reproduction'
source scripts/env.sh

echo "$ROS_DOMAIN_ID"                 # 手工环境默认 42
ros2 pkg prefix nav2_bringup
ros2 pkg prefix nav2_smac_planner
ros2 pkg prefix nav2_mppi_controller
```

安装 Policy 的 Python 层依赖：

```bash
python -m pip install -r requirements-policy.txt
```

不要把 `rclpy`、Nav2 或 Isaac Sim 当作普通 pip 包安装。完整要求和验证命令见
[DEPENDENCIES.md](DEPENDENCIES.md)。

### 3. 编译公开任务表

```bash
QUESTION_TASK_ROOT='/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/question_to_player/task'

python compile_tasks.py \
  --question-root "$QUESTION_TASK_ROOT" \
  --config-dir "$PROJECT_DIR/config/tasks" \
  --output "$PROJECT_DIR/compiled_tasks.json"
```

命令必须输出 `COMPILED_TASKS=24`。生成文件含绝对数据路径，因此不提交到 Git；每次
部署都必须在目标服务器重新生成。任务表保存公开路线、导航阈值和官方运行上限；可调
动作频率由每题自己的 `config/tasks/Qxx.json` 提供；存在 hash 锁定的单题路线时，编译器
只替换中间航点，并强制保留官方最终目标。

### 4. 校验每题独立配置

```bash
python3 task_config.py validate-all
```

必须输出 `VALID_TASK_CONFIGS=24`。每个任务配置包含自己的动作频率、Nav2 profile 引用、
profile SHA-256 和导航回归基线。单题地图和路线也必须放在 `config/tasks/Qxx/` 并由清单
记录 SHA-256。Q01、Q02、Q04、Q05、Q06、Q07、Q09、Q14、Q19 当前标记为导航锁定；
最新的 Q02/Q05/Q06/Q07/Q09 证据来自 2026-09-01 隔离优化与 Q05 绕行回归。
导航锁只表示该配置曾有成功证据，用于避免无意改动；最近完整回归中 Q04 因提前结束、
Q09 因运行窗口过短未复现成功，不能把锁定状态直接当作最新成功率。

`config/profiles/nav2_default_v1.yaml` 是不可变基线。不得原地修改它；校验器会因 hash
不匹配拒绝启动。调试失败任务时，应复制成新的版本化 profile，例如
`nav2_forward_v1.yaml`，计算 SHA-256，然后只修改目标任务的 JSON。运行目录还会
保存实际使用的 `task_config.json` 和 `nav2_params.yaml` 快照。

### 5. 使用 Isaac Sim USD 建图

地图必须由赛题 `environment.json` 指向的 USD 生成：

```bash
mkdir -p "$PROJECT_DIR/maps"

"$NAV2_ROOT/isaacsim/python.sh" generate_usd_maps.py \
  --compiled-tasks "$PROJECT_DIR/compiled_tasks.json" \
  --output-dir "$PROJECT_DIR/maps" \
  --resolution 0.10 \
  --margin 3.0 \
  --corridor-radius 0.65
```

应生成 `warehouse`、`kitchen`、`market` 三组 `.pgm/.yaml/.json` 文件。源 USD 只读，
不会被脚本修改。

需要单题地图时，仍复用同一个工具，并把工件归档到该任务路径。Q09 的可复现命令为：

```bash
mkdir -p "$PROJECT_DIR/config/tasks/Q09"

"$NAV2_ROOT/isaacsim/python.sh" generate_usd_maps.py \
  --compiled-tasks "$PROJECT_DIR/compiled_tasks.json" \
  --output-dir "$PROJECT_DIR/config/tasks/Q09" \
  --task Q09 \
  --output-name q09 \
  --corridor-radius 0.0 \
  --endpoint-clear-radius 0.65
```

该地图保留 USD 碰撞投影，只清理机器人起点和官方终点的落脚圆盘；不会像共享地图那样
沿整条公开路线抹除家具。生成后必须更新 Q09 清单中的地图 hash，再重新编译任务表。

Q05 使用同一 USD 投影工具和 `config/tasks/Q05/route_override.json` 中的绕行线生成单题
地图。其路线走廊为 1.10 m：扣除 Nav2 0.60 m inflation 后保留 0.50 m 纠偏空间，同时
仍限制在 USD 核验过的料箱与油桶之间。可复现参数为 `--task Q05 --output-name q05
--margin 5.0 --corridor-radius 1.10 --endpoint-clear-radius 0.65`；生成后同样必须更新地图
hash 并重新编译任务表。

### 6. 协议自测

```bash
scripts/start_task_stack.sh Q04
scripts/check_task_stack.sh Q04 60

python self_test_client.py \
  --task Q04 \
  --compiled-tasks compiled_tasks.json \
  --endpoint ws://127.0.0.1:18022

scripts/stop_task_stack.sh Q04
```

成功输出应包含 `SELF_TEST_OK=1`。Policy 只监听 `127.0.0.1:18022`；已有遥操服务的
`18021` 不受影响。

## 执行与验收

当前验证部署目录：

```text
/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy
```

单题运行：

```bash
scripts/start_task_stack.sh Q04
scripts/run_runner_task.sh Q04 <run-id>
scripts/stop_task_stack.sh Q04
```

Runner 参数由单题执行器和 `config/tasks/Qxx.json` 共同确定：

- `ATTACK_MODE` 默认为 `off`；按官方攻击条件运行时必须显式设置 `ATTACK_MODE=on`；
- `navigation-mode=vla`；
- `base-mode=kinematic`；
- 5 Hz 观测与录像；Q01/Q09–Q24 使用 5 Hz 动作，Q02/Q03/Q04/Q06/Q08
  使用 2 Hz，Q05/Q07 使用 1 Hz；
- 严格使用公开任务的 `maximum_vla_actions` 和 `maximum_duration_s`，不扩展上限；
- Docker 外层墙钟超时默认为“官方 `maximum_duration_s` + 600 秒”，超时后先 TERM、
  60 秒后 KILL，并清理残留容器，防止单题挂死整个批次；
- 动作 3–9 维始终为零；
- 底盘速度限制为 `vx [-0.25,0.25]`、`vy [-0.12,0.12]`、
  `yaw_rate [-0.30,0.30]`。

批量运行（默认 Q01–Q24，也可传入任务列表）：

```bash
scripts/run_all_tasks.sh
scripts/run_all_tasks.sh Q03 Q04 Q05
# 官方镜像、开启题目攻击、禁用所有调试 runtime 副本
ATTACK_MODE=on RUNNER_OVERVIEW=0 RUNNER_CHASE=0 scripts/run_all_tasks.sh
```

每次命令都会独占一个精确到纳秒的目录，例如
`results_20260830_153012_123456789/`；如果目录已经存在，执行器直接拒绝运行，绝不把
新结果混入旧结果。

长批次可脱离 SSH 运行：

```bash
RUN_TIMESTAMP="$(date +%Y%m%d_%H%M%S_%N)"
LOG="$PROJECT_DIR/logs/batches/results_$RUN_TIMESTAMP.log"
mkdir -p "$PROJECT_DIR/logs/batches"

nohup setsid env RUN_TIMESTAMP="$RUN_TIMESTAMP" \
  "$PROJECT_DIR/scripts/run_all_tasks.sh" \
  >"$LOG" 2>&1 < /dev/null &

echo $! >"$PROJECT_DIR/logs/batches/results_$RUN_TIMESTAMP.pid"
```

检查后台批次：

```bash
ps -p "$(cat logs/batches/results_<timestamp>.pid)"
tail -f logs/batches/results_<timestamp>.log
```

批次日志会在启动时输出 `BATCH_TIMING_START`，每题分别输出 `TASK_TIMING_START` 和
`TASK_TIMING_END`。结束记录包含该题墙钟推理时间 `ELAPSED_S/ELAPSED_HMS`，并根据本批次
已完成任务的平均耗时滚动计算 `ETA_REMAINING_HMS` 和 `ETA_COMPLETION`。第一题完成前默认
按每题 1800 秒估算，可通过 `INITIAL_TASK_ESTIMATE_SECONDS` 调整。相同数据也会写入
`runs.tsv`，方便程序读取。

结果按“一次执行一个事务目录”组织，不再按任务长期累加不同 run-id：

```text
results_<YYYYMMDD_HHMMSS_NNNNNNNNN>/
├── runs.tsv
├── summary.json
├── summary.md
├── Q01/
│   ├── task_config.json
│   ├── nav2_params.yaml
│   ├── episode.mp4
│   ├── overview.mp4              # 仅调试批次存在，不进入提交目录
│   ├── chase.mp4                 # 远距第三人称追随视角，也不进入提交目录
│   ├── logs/status files…
│   └── submission/
│       ├── episode.hdf5
│       └── episode.mp4
└── Q02/…
```

这样目录名直接标识本次执行，目录内各 Qxx 必定来自同一批次；同一 Qxx 不会再出现多个
难以区分的历史子目录。旧 `results/` 只作为历史证据保留，新执行不会再写入其中。

两个文件只在同一次 Runner 运行同时产生且 HDF5 仅含 `/data/demo_0` 时标记
`submission_ready=1`。
`video_kind=runner_episode` 表示官方仿真录像；只有 Runner 在录像器启动前失败时才生成
明确标记的 `diagnostic_placeholder`，后者不会计为导航成功。

### 独立全局俯视与第三人称调试视频

需要在保持原产物不变的同时观察全场动态时，使用独立入口：

```bash
scripts/run_all_tasks_overview.sh Q01
# 或运行全部任务
scripts/run_all_tasks_overview.sh
```

该入口先从固定镜像 `safety-embodiment:20260817` 提取
`m20_fourview_runner.py`，核验官方源文件 SHA-256，再在 `cache/overview_runtime/`
按生成文件 SHA-256 存入不可变子目录。官方镜像和镜像内文件不会被修改；每个批次在
启动时固定自己使用的副本路径，后续构建不会改变正在运行的批次。副本保留原跟随相机，
额外创建第五、六台相机：第五台根据任务实际加载的 Isaac USD 场景边界计算画幅，位于
屋顶下方、场景中心正上方，采用正交投影向下拍摄；第六台随机械狗朝向移动，位于后方
6.0 米、上方 1.2 米并看向底盘中心，使完整机器人位于画面中央偏下，
形成远距第三人称赛车式视角。它把相机实际默认焦距缩短为 50%，在不改变位置和俯角的
前提下把目标平面的横向覆盖范围扩大约一倍；仍使用普通透视投影，不使用鱼眼畸变。

`overview.mp4` 与 `chase.mp4` 通过独立侧车目录传出，只复制到
`results_<timestamp>/Qxx/`；两者永远不会复制到 `submission/`。原有 `episode.mp4`、
`episode.hdf5`、任务配置、Nav2 参数、日志和汇总流程保持不变。调试批次使用
`cache/overview_logs/<timestamp>/`，不会覆盖普通运行的 `logs/Qxx/`。若 Isaac 在首帧前
失败，两个调试视角仍会分别生成明确标记的占位视频。两台额外的 1280×720 相机会降低
仿真实时速度，因此该入口默认使用“官方时长 + 1800 秒”的有限墙钟超时；普通运行仍为
“官方时长 + 600 秒”。

批量执行会在启动 Isaac Sim 前做 Nav2 健康检查：Policy bridge 先发布公开出生点 TF，
随后要求 8 个 lifecycle 节点全部 ACTIVE 且 `NavigateThroughPoses` Action Server 可用。
预检绝不发送目标；每次尝试使用新 ROS Domain，失败时最多整栈重启三次。只有收到
第一帧真实 Runner 观测后才允许提交目标，目标失败最多再尝试两次。

墙钟超时可在诊断时覆盖，但正式运行不建议缩短默认启动/收尾余量：

```bash
RUNNER_TIMEOUT_GRACE_SECONDS=600 scripts/run_all_tasks.sh Q16 Q17
```

超时任务会设置 `runner_timed_out=1`、返回非零并保留诊断视频，批处理随后继续下一题。

汇总器分别报告文件对有效性与导航成功，不把 `runner_status=0`、占位视频或固定
`0.5 m` 当作成功。导航-only 题读取正式 `robot_near_target` 条件，其他题使用公开
route arrival tolerance。

## 安全停止

停止单题只使用项目记录的 PID/PGID，并核验命令行属于本项目：

```bash
scripts/stop_task_stack.sh Q04
```

不要使用 `pkill python`、`killall` 或按名称清理 Isaac/ROS 进程；服务器可能同时运行
其他用户任务和原始 Nav2 开发环境。
