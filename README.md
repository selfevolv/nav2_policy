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
├── config/nav2_params.yaml       # SmacPlanner2D + MPPI Omni 参数
├── launch/m20_nav2.launch.py     # 独立地图服务器和 Nav2 bringup
├── scripts/                      # 启停、单题和批量执行器
├── compile_tasks.py              # 编译 Q01–Q24 公开路线
├── generate_usd_maps.py          # Isaac Sim USD 碰撞几何投影建图
├── navigation_bridge.py          # Runner 状态、TF/Odom、Nav2 Action 桥
├── policy_server.py              # Runner WebSocket Policy
├── summarize_results.py          # JSON/Markdown 验收汇总
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

echo "$ROS_DOMAIN_ID"                 # 42
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

命令必须输出 `COMPILED_TASKS=24`。生成的任务表含绝对数据路径，因此默认不提交到 Git。

### 4. 使用 Isaac Sim USD 建图

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

### 5. 协议自测

```bash
scripts/start_task_stack.sh Q04

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

Runner 参数由单题执行器强制设为：

- `attack-mode=off`；
- `navigation-mode=vla`；
- `base-mode=kinematic`；
- 5 Hz 观测、录像和动作；
- 动作 3–9 维始终为零；
- 底盘速度限制为 `vx [-0.25,0.25]`、`vy [-0.12,0.12]`、
  `yaw_rate [-0.30,0.30]`。

批量运行（默认 Q01–Q24，也可传入任务列表）：

```bash
BATCH_ID=<batch-id> scripts/run_all_tasks.sh
BATCH_ID=<batch-id> scripts/run_all_tasks.sh Q03 Q04 Q05
```

长批次可脱离 SSH 运行：

```bash
BATCH_ID="nav2_batch_$(date +%Y%m%d_%H%M%S)"
LOG="$PROJECT_DIR/results/batches/$BATCH_ID.log"
mkdir -p "$PROJECT_DIR/results/batches"

nohup setsid env BATCH_ID="$BATCH_ID" \
  "$PROJECT_DIR/scripts/run_all_tasks.sh" \
  >"$LOG" 2>&1 < /dev/null &

echo $! >"$PROJECT_DIR/results/batches/$BATCH_ID.pid"
```

检查后台批次：

```bash
ps -p "$(cat results/batches/<batch-id>.pid)"
tail -f results/batches/<batch-id>.log
```

每个任务的 `results/Qxx/<run-id>/` 保存官方视频、HDF5、Runner/Nav2/Policy 日志、
导航状态和运行摘要。批次目录保存 `runs.tsv`、`summary.json` 和 `summary.md`。
`video_kind=runner_episode` 表示官方仿真录像；只有 Runner 在录像器启动前失败时才生成
明确标记的 `diagnostic_placeholder`，后者不会计为导航成功。

批量执行会在启动 Isaac Sim 前做 Nav2 健康检查：使用公开出生点发布初始 TF，要求
Nav2 接受公开路线，失败时最多整栈重启三次。真实观测到达前动作仍强制为全零。

## 安全停止

停止单题只使用项目记录的 PID/PGID，并核验命令行属于本项目：

```bash
scripts/stop_task_stack.sh Q04
```

不要使用 `pkill python`、`killall` 或按名称清理 Isaac/ROS 进程；服务器可能同时运行
其他用户任务和原始 Nav2 开发环境。
