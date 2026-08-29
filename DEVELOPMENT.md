# M20 Nav2 Policy 开发记录

## 2026-08-29：实施开始

### 用户验收要求

1. 第一阶段不考虑攻击。
2. 实现 Q01–Q24 的导航部分，不实现操作部分。
3. 每道题必须生成视频，即使 Runner 最终判定失败。
4. 导航到达率至少 50%，即至少 12/24。
5. 不修改现有 Nav2 项目源码；需要修改的内容必须放在新目录。
6. 地图必须基于 Isaac Sim 环境描述 USD 建模，并优先采用简单方案。
7. 编写 Policy 的同时持续记录 Markdown 开发步骤。

### 已核验环境

- 远端主机：`youlika@192.168.1.189`。
- 原始复现目录：`/home/youlika/navigation2_reproduction`，只读复用其安装结果。
- Nav2：源码 tag `1.1.20`，39 个包已经构建。
- 原 Carter 演示配置使用 NavFn、DWB 和差速模型，不能直接用于 M20。
- Runner 镜像：`safety-embodiment:20260817`。
- Runner Policy：WebSocket + MessagePack/NumPy，动作维度 10，状态维度 25。
- 底盘动作：`vx/vy/yaw_rate = actions[0:3]`。
- Runner 默认推理超时 1 秒，第一阶段使用 `H=1`。
- `question_to_player` 中 Q01–Q24 均提供公开 `route.json` 和场景 USD 路径。
- 历史 Runner 成功和失败运行都生成过 `episode.mp4`。
- 现有遥操服务占用 `127.0.0.1:18021`，新 Policy 开发端口使用 `18022`。

### 冻结的简单实现方案

1. 从 24 个任务的 `environment.json`、`route.json`、`task.json` 编译任务表。
2. 使用 Isaac Sim Python/pxr 打开三套 USD。
3. 把启用碰撞的静态几何世界 AABB 投影到二维栅格。
4. 为避免 AABB 过度保守，用公开路线清理一条固定宽度安全走廊。
5. 使用 Runner 的世界位姿直接发布 TF/Odometry，不运行 AMCL。
6. 使用 SmacPlanner2D 和 MPPI Omni；所有输出再次按 Runner 上限裁剪。
7. 批量脚本逐题运行，始终复制视频、日志和导航统计。

### 当前进度

- [x] 核验 Runner 协议、Nav2 插件和远端依赖。
- [x] 创建独立工程与开发记录。
- [x] 编译 24 题任务表。
- [x] 生成三套 USD 二维地图。
- [x] 实现 ROS2–Policy 桥初版。
- [ ] 完成 Q04 smoke test。
- [ ] 批量运行 Q01–Q24。
- [ ] 达到至少 12/24 导航成功。

### 地图生成第一次尝试

- 命令通过独立安装的 `isaacsim/python.sh` 启动，没有修改 Isaac Sim。
- 首次执行在导入 `pxr` 时失败：`ModuleNotFoundError: No module named 'pxr'`。
- 原因是 Isaac Sim 5.1 的 Python 运行时需先导入 `isaacsim`，再导入 bundled `pxr`。
- 已把兼容初始化加入新项目的地图生成器，准备重试。
- 第二次尝试证明只导入 `isaacsim` 仍不足；Carbonite 明确要求先实例化
  `SimulationApp`。生成器现使用独立 headless `SimulationApp`，结束时主动关闭。

### USD 地图生成结果

地图分辨率统一为 0.10 米。所有文件输出在新项目 `maps/`，没有修改场景 USD。

| 场景 | 地图尺寸 | 投影碰撞 Prim | 占用比例 |
| --- | ---: | ---: | ---: |
| kitchen | 103×179 | 2867 | 22.35% |
| market | 167×167 | 838 | 12.24% |
| warehouse | 581×611 | 1905 | 54.97% |

每个场景同时生成 `.pgm`、`.yaml` 和 `.json`。JSON 保存源 USD 路径、SHA-256、
地图原点、尺寸、碰撞 Prim 数和路线走廊参数。

### Policy/ROS2 桥初版

- 新 Policy 监听 `127.0.0.1:18022`，保留遥操服务的 `18021`。
- `state[0:12]` 发布为 `map -> odom -> base_link` 和 `/odom`。
- 使用 `NavigateThroughPoses` 提交公开路线。
- 订阅平滑后的 `/cmd_vel`，只写动作 `0:3`，其余七维恒为零。
- 观测超过 0.75 秒或速度命令超过 0.50 秒未更新时输出全零。
- 独立配置使用 SmacPlanner2D、MPPI Omni、5 Hz 控制和 Runner 物理限幅。

### Nav2 独立启动第一次尝试

- Q04 首次启动在 launch 参数解析阶段退出，未启动任何导航节点。
- 原因：Nav2 1.1.20 的 `PythonExpression` 要求 `use_composition` 使用 `False`
  而不是小写 `false`。
- 已仅修正新项目的 launch 文件，原 Nav2 文件未改动。

### Nav2 节点激活检查

- map_server 成功读取 warehouse 地图：581×611，0.10 m/cell。
- MPPI 插件与全部 critic 已开始加载。
- 首次 controller 配置因 `CostCritic.consider_footprint=true` 与圆形
  `robot_radius` 不匹配而停止。
- 为保持简单，改为 `consider_footprint=false`，继续使用 costmap 圆形半径碰撞检查。
- 第二次激活确认 SmacPlanner2D 和 MPPI Omni 已完整配置；BT Navigator 因 Carter
  参数中的旧库名 `nav2_round_robin_bt_node` 与实际安装库
  `nav2_round_robin_node_bt_node` 不同而退出。
- 已按覆盖层中的实际 `.so` 名称修正，并移除本行为树不使用且未安装的
  `nav2_path_expiring_timer_condition`。
- 两个 SSH 测试 launch 曾在 PTY 结束后残留，已按精确父 PID 清理；原 Carter 进程未动。
- 为避免后续 SSH PTY 残留，新增 `start_task_stack.sh` / `stop_task_stack.sh`，只按
  PID 文件和精确项目路径管理本项目进程。
- 合成状态首次提交目标时，BT Navigator 正处于最后约 0.8 秒激活窗口，Action Server
  拒绝了请求。桥接层已改为拒绝后每 0.5 秒重试，不把启动时序当成永久失败。
- 后台进程现通过 `setsid` 建立独立进程组；停止脚本按验证过的 PGID 依次发送
  INT、TERM、KILL，避免留下孤儿节点。

### 合成端到端自测通过

- 使用 Q04 出生点状态，以 5 Hz 发送 60 次合成 Runner 请求。
- 启动阶段第一次目标被拒后，第二次自动重试被接受。
- SmacPlanner2D 生成路线，MPPI Omni 输出非零 `vx/vy/yaw_rate`。
- 平滑后的峰值速度为 `0.25 m/s`，没有超过 Runner 上限。
- Policy 单次处理通常约 0.2–0.5 ms，远低于 1 秒超时。
- 自测标志：`SELF_TEST_OK=1`。

### Runner 单题执行器

- 新增 `run_runner_task.sh Qxx [run-id]`。
- 强制 `attack-mode=off`、`navigation-mode=vla`、`base-mode=kinematic`。
- Runner 成败都复制 `episode.mp4`、HDF5、导航状态和完整日志到项目 `results/`。
- Runner 失败不会中断后续批处理；只有缺失视频会以单独状态 20 报告。

### Q04 首次真实 Runner 启动检查

- 首次真实运行在 Isaac Sim 启动前被 Runner 的 locked-input 校验拒绝，因此不计为
  导航测试，也没有生成视频。
- 原因：镜像内置的旧题目快照缺少
  `M20_piper_high_precision/evidence/isaac51_build.log`；服务器上的官方更新数据集
  `question_to_player` 包含该文件。
- 为保持改动隔离，未修改 Runner 镜像、官方题目数据或全局 Runner 辅助函数。
  `run_runner_task.sh` 现在只读挂载官方 `question_to_player` 到镜像预期的题目根目录。
- 输出权限修正也收敛在导航项目单题脚本内，并且只处理本次安全格式 `run-id` 对应目录。
- 修复挂载后 Q04 完成 400 个真实控制步并生成 1280×720、5 FPS、85 秒 H.264
  视频；机器人从 `(-42.50, -53.00)` 行驶到 `(-20.66, -52.27)`，终点最小距离
  从 39.89 m 降至 18.07 m。该次因动作数耗尽而未到终点，视频仍完整保留。
- 400 步在 5 Hz 下只有 80 秒，在 0.25 m/s 安全限速下理论最多约 20 m，小于 Q04
  约 40 m 距离。单题执行器现在保证动作预算至少为 `任务时长 × 动作频率`，不放宽
  速度限制；Q04 的有效预算因此为 1200 步、240 秒。
- 新增导航项目自己的 `/root/.cache/ov` 与 `/root/.cache/nvidia` 持久缓存挂载，减少
  同场景后续任务重复编译纹理/着色器。缓存不写入官方题目目录。

### 批量验收执行器

- 新增 `run_all_tasks.sh`，默认按 Q01–Q24 串行执行；每题使用独立 Nav2/Policy
  进程状态，避免上一题目标泄漏到下一题。
- 每题保存 Runner 视频、HDF5、Runner 日志、Nav2 日志、Policy 日志和导航状态。
- 若 Runner 在录像器启动前失败，则用 FFmpeg 生成 5 秒、1280×720 的诊断占位视频，
  并在 `run_summary.json` 标记 `video_kind=diagnostic_placeholder`；占位视频永不计为
  导航成功。
- 新增 `summarize_results.py`，输出 JSON 与 Markdown 批次报告，明确统计视频完整率、
  导航成功数、最小终点距离以及是否达到 50% 目标。

### Q04 长预算重跑并发修复

- 一次重跑中 Nav2 的 BT Navigator 生命周期配置响应超时；保留 Runner 的同时单独重启
  Nav2 后，旧 Policy 的 Action Future 异常使 ROS executor 不再发布 TF。确认 Runner
  不支持 Policy 断线重连，因此后续一律整栈重启，不在单次录像中热重启组件。
- 随后的完整 Policy 运行暴露了状态文件写入竞争：观测线程和 Action 回调可能同时替换
  同一个 `navigation_status.tmp`，造成 `FileNotFoundError` 并关闭 WebSocket。
- 桥接层现用独立互斥锁串行化状态文件原子写入；Action goal/result Future 的异常会被
  转换为安全的零动作和目标重试，不再终止 ROS executor。
- 修复后的 Q04 在 734 个控制步完成官方导航段：Runner 状态 `SUCCEEDED`、交付协议
  `VALID`，生成 759 帧、151.8 秒、1280×720 H.264 官方视频（47.2 MB）。终点最小
  距离 0.313 m，Runner 在桥的 0.25 m/连续 10 帧判据前主动结束导航段。
- 汇总器因此同时接受两类成功证据：桥明确到达，或 Runner 正常完成、官方视频存在、
  未耗尽动作预算且最小终点距离不超过 0.5 m。该派生依据会单独写入报告，避免与操作
  成功混淆。
- 为减少 Fast DDS 启动瞬间的服务响应竞争，独立 launch 让地图服务器先启动，2 秒后
  再启动导航节点；未修改任何 Nav2 源码。

### Q01/Q02 批次与 Nav2 启动健康门

- Q01 导航成功：929 控制步，终点最小距离 0.113 m，Runner `SUCCEEDED`、协议
  `VALID`，官方视频约 63.4 MB。
- Q02 导航失败但录像完整：1171 控制步始终停在出生点，官方视频约 36.8 MB。
  日志确认 Fast DDS 在 `planner_server/change_state` 返回时超时，地图已激活但导航
  Action Server 未上线；该题不计成功。
- 为避免后续题目直到录像结束才发现相同问题，桥接层用公开 `spawn_xyz/spawn_yaw`
  初始化 TF。初始 TF 只帮助 Nav2 lifecycle，观测时间仍为空，因此真实 Runner 首帧前
  Policy 必定输出零动作。
- 批量执行器现在于启动 Isaac Sim 前等待 Nav2 接受公开路线；30 秒未接受则整栈重启，
  最多 3 次。三次仍失败时仍运行 Runner 并保存失败视频，不掩盖失败。
- Q03 健康门短测在第 1 次启动即通过：目标已接受、`request_count=0`、
  `observation_age_s=null`、输出速度全零。
- Q03–Q24 已改为服务器独立监督进程运行，避免 SSH/对话断开中止。批次 PID 记录在
  `results/batches/nav2_q03_q24_detached_20260829.pid`，总日志为同目录同名前缀 `.log`；
  每题仍由脚本单独保存官方视频与日志。
