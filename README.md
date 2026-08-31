# M20 Nav2 Navigation Policy

本项目把独立部署的 ROS 2 Nav2 适配为具身安全应用挑战赛 M20 Runner 所要求的
`openpi-websocket/pi0.5` Policy。当前阶段负责 Q01–Q24 的底盘导航，不执行机械臂、
夹爪或 Q15 蹲起动作，全部攻击关闭。

## 约束

- 不修改 `/home/youlika/navigation2_reproduction` 中的 Nav2 或 Isaac Sim 源码。
- 项目部署到独立目录，使用独立 `ROS_DOMAIN_ID`。
- 地图由赛题 Isaac Sim USD 场景的碰撞几何投影生成。
- 每道题都运行并保存视频，Runner 任务失败时也保留产物。
- 第一阶段目标是 24 道题中至少 12 道到达公开路线的导航终点。

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
├── config/tasks/Q01.json…Q24.json # 每题独立配置、频率与回归锁
├── launch/m20_nav2.launch.py     # 独立地图服务器和 Nav2 bringup
├── scripts/                      # 启停、单题和批量执行器
├── compile_tasks.py              # 编译 Q01–Q24 公开路线
├── task_config.py                # 独立配置及 profile SHA-256 校验
├── check_nav2_ready.py           # Lifecycle/Action Server 无目标预检
├── generate_usd_maps.py          # Isaac Sim USD 碰撞几何投影建图
├── navigation_bridge.py          # Runner 状态、TF/Odom、Nav2 Action 桥
├── policy_server.py              # Runner WebSocket Policy
├── summarize_results.py          # JSON/Markdown 验收汇总
├── tests/                         # 任务元数据与验收单元测试
├── TEST_REPORT_20260830.md        # P0 修改与正式 Runner 测试报告
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
  --output "$PROJECT_DIR/compiled_tasks.json"
```

命令必须输出 `COMPILED_TASKS=24`。生成文件含绝对数据路径，因此不提交到 Git；每次
部署都必须在目标服务器重新生成。任务表保存公开路线、导航阈值和官方运行上限；可调
动作频率由每题自己的 `config/tasks/Qxx.json` 提供。

### 4. 校验每题独立配置

```bash
python3 task_config.py validate-all
```

必须输出 `VALID_TASK_CONFIGS=24`。每个任务配置包含自己的动作频率、Nav2 profile 引用、
profile SHA-256 和导航回归基线。Q01、Q04、Q14、Q19 当前标记为导航锁定，其中 Q01 是
旧批次历史成功证据，Q04/Q14/Q19 是 2026-08-30 正式 Runner 成功证据。

`config/profiles/nav2_default_v1.yaml` 是不可变基线。不得原地修改它；校验器会因 hash
不匹配拒绝启动。调试失败任务时，应复制成新的版本化 profile，例如
`nav2_forward_only_v1.yaml`，计算 SHA-256，然后只修改目标任务的 JSON。运行目录还会
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

- `attack-mode=off`；
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
