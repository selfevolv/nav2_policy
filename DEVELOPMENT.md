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

## 2026-08-30：P0 稳定性修复与正式限额回归

### 对旧结论的隔离复核

- Nav2 单独启动时只有 map server 能激活，controller 会等待 bridge 提供的 TF；因此
  “先让 Nav2 全部 ACTIVE 再启动 Policy”不可行。
- 正确顺序改为先启动 bridge 发布合成出生点 TF，再启动 Nav2。合成状态只用于 lifecycle，
  不再满足发目标条件。
- 独立 Domain 143 复现了旧缺陷：`request_count=0` 时目标已被接受，随后 controller
  报 `Failed to make progress`。新代码要求 0.75 秒内存在真实 Runner 观测。
- 修复后 Q04 隔离预检达到 8/8 lifecycle ACTIVE、Action Server ready，同时保持
  `goal_attempts=0`、`goal_sent=false`、`request_count=0`。

### 启动与目标状态机修改

- 每次 stack 启动生成新的 `ROS_DOMAIN_ID` 和 `run_token`，启动前删除旧状态文件。
- `start_task_stack.sh` 等待本次 token 的 bridge 初始状态后才启动 Nav2。
- 新增 `check_nav2_ready.py`，通过 lifecycle service 和 Action Client 做无目标预检，
  不再使用可能陈旧的 `goal_accepted`。
- Action 失败采用最多三次总尝试、1/2 秒退避；到达任务级导航阈值后不再因 Nav2 后续
  ABORTED 抹掉成功证据。
- `navigation_reached` 与“停止输出”解耦：第一次进入正式导航阈值即可记录证据，只有
  route tolerance 连续满足或 Nav2 SUCCEEDED 后才停止底盘命令，避免 Q01 精确终点过早刹车。

### 正式动作预算与提交文件对

- 删除 `duration × action_hz` 自动扩大动作上限的逻辑，严格使用公共任务上限。
- Runner 已确认低频动作会持续保持，频率必须是 50 的正约数。当前表为：Q05/Q07=1 Hz，
  Q02/Q03/Q04/Q06/Q08=2 Hz，其余=5 Hz。
- navigation-only 题从正式 success condition 编译导航半径；操作题使用 route controller
  arrival tolerance，汇总不再硬编码 0.5 m。
- 同次 Runner 产物复制为 `submission/episode.hdf5 + episode.mp4`，并用 Runner 镜像验证
  HDF5 根组只有 `metadata/data` 且 `/data` 只有 `demo_0`。
- Runner 失败即使生成诊断视频也返回非零；批处理继续执行，但占位视频和无效文件对
  永不计入导航成功。

### 正式 Runner 测试结果

- Q04：2 Hz、官方 400 动作/240 秒；一次目标，302 次 Policy 请求，最小距离
  0.102 m（阈值 0.60 m），Nav2 SUCCEEDED，Runner 协议 VALID，文件对有效。
- Q05：1 Hz、官方 400 动作/240 秒；一次目标，239 次请求，最小距离 8.289 m，导航失败；
  Runner 协议和文件对仍有效，因此保留了真实失败视频。轨迹长期使用约
  `vx=-0.12 m/s` 倒行，证明只降低频率不能解决反向长路线。
- Q14：5 Hz、官方 500 动作；导航最小距离 0.070 m（阈值 0.25 m），文件对有效。
- Q19：5 Hz、官方 600 动作；导航最小距离 0.118 m（阈值 0.25 m），文件对有效。
- 四次正式测试均在第一次 stack preflight 通过、目标只提交一次，未再出现旧批次中的
  lifecycle transition race 或数百次 goal rejection。
- 当前版本不建议直接作为目标 30 分的最终提交：短路线和正向路线可靠，但 Q05 已证明
  长距离反向路线存在系统性速度不足。详细数据与 SHA-256 见 `TEST_REPORT_20260830.md`。

## 2026-08-30：任务配置隔离与运行事务目录

- 新增 `config/tasks/Q01.json` 至 `Q24.json`，每题独立记录 Nav2 profile、动作频率、
  profile SHA-256、导航状态、锁定状态和基线运行；动作频率不再硬编码在
  `compile_tasks.py`。
- Q01 按 2026-08-29 历史成功证据锁定；Q04、Q14、Q19 按 2026-08-30 正式 Runner
  证据锁定。Q05 保留正式失败基线但不锁定。其他任务在取得可靠成功证据前标为
  `unverified`。
- 原 `config/nav2_params.yaml` 移为不可变的
  `config/profiles/nav2_default_v1.yaml`。`task_config.py` 在启动前核验 profile hash；
  原地修改共享 profile 会使任务拒绝启动，调参必须新建版本并只切换目标任务。
- 单题结果同时保存任务清单和 Nav2 参数快照，保证以后能复现该视频实际使用的配置。
- 新结果结构改为 `results_<精确时间>/<Qxx>/`。每次单题或批量调用只创建一个新的根
  目录；根目录已存在或同一任务目录已存在时直接失败，避免新旧数据混合。
- 旧 `results/Qxx/<run-id>/` 不迁移、不删除，只保留为历史证据。官方提交单元仍是每题
  目录内同次 Runner 生成的 `submission/episode.hdf5 + episode.mp4`。

## 2026-08-31：Runner 墙钟超时

- 完整 Q01–Q24 批次在 Q16 导航成功后卡住：最后观测为 330、最后视频帧为 354，
  Isaac/Carb 工作线程持续占用 CPU，但 13 小时未生成最终 MP4/HDF5，Q17–Q24 未启动。
- 官方 `maximum_duration_s` 是仿真内部限制，Isaac 关闭或交付阶段挂起时不能保证 Docker
  退出；原执行器没有外层墙钟 watchdog，因此批次会无限等待。
- `run_runner_task.sh` 现用 GNU `timeout` 包裹 Runner Docker，默认墙钟上限为官方时长
  加 600 秒冷启动/收尾余量，超时后 TERM 并在 60 秒后 KILL。
- Docker 使用 `--cidfile`；若客户端超时后容器仍存在，执行器会按精确容器 ID 执行
  stop/kill/rm，不使用名称或宽泛进程匹配。
- 超时写入 `runner_timed_out`、`runner_wall_timeout_s` 和清理日志；随后按失败任务生成
  诊断视频并返回非零，批处理可以继续下一题。

## 2026-08-31：独立 Isaac 全局俯视调试录像

- 官方 Runner 只原子发布 `episode.mp4 + submission.hdf5`，额外写入内部 workdir 的文件
  不会发布；因此俯视视频使用独立只写侧车挂载，不改变官方发布目录。
- `build_overview_runtime.py` 仅接受 SHA-256 为
  `6f1e3327c378e9c69785fbbf35147ee1012a382b31d4e13fe49f8c82913006b3` 的官方
  `m20_fourview_runner.py`，并生成缓存副本。官方镜像 ID 保持
  `sha256:4edf7b5faed0799ee81e286e1bf358cc46ba5080779bdca16b783b2b0668a578`。
- 副本保留原三台 Policy 相机和第四台跟随录像相机，只在启用
  `NAV2_OVERVIEW_OUTPUT` 时增加第五台 1280×720 相机。正交画幅从已加载 USD 默认 Prim
  的 render bounds 计算，相机位于屋顶下方并垂直朝向场景地面。
- 第一版外部透视相机虽然覆盖完整场景，但只能看到仓库屋顶，已作为失败校准运行保留；
  第二版改为屋顶下方正交投影，Q01 预览确认可以看到完整仓库内部。
- `RUN_LOG_ROOT` 新增向后兼容覆盖项；普通运行仍写 `logs/`，俯视调试运行写
  `cache/overview_logs/<timestamp>/`，避免覆盖既有日志。
- 结果目录只增加同级 `overview.mp4`；执行器没有向 `submission/` 复制该文件，也没有
  改动 `run_summary.json` 的既有字段。
- Q01 第二版完整运行产生 954 帧同步跟随/俯视录像，Runner 状态 0、提交文件对验证通过、
  导航最小距离 0.022 m。由于第五台 1280×720 相机会降低仿真实时速度，俯视入口单独把
  墙钟余量设为 1200 秒；普通入口仍保持 600 秒。

## 2026-09-01：失败任务隔离优化与 Q09 单题 USD 地图

- Q02、Q05、Q06、Q07 的失败轨迹持续以 `vx=-0.12 m/s` 倒行，240 秒内仍在运动而非
  卡死。新增只增不改的 `config/profiles/nav2_forward_v1.yaml`：禁止正常路径倒行，
  启用路径朝向和前进偏好；只有这四份未锁定任务清单引用新 profile，已成功任务继续
  使用原始 `nav2_default_v1.yaml`。
- Q09 旧共享地图沿公开路线清除了 `0.65 m` 走廊，导致餐桌和椅子的碰撞投影从 Nav2
  中消失，真实机器人最终撞住。新增 `config/tasks/Q09/`，复用 USD 投影工具生成无路线
  清障地图，只清理起点/终点 `0.65 m` 落脚区。
- Q09 绕行线由该地图上的八连通 A* 生成，按 `0.50 m` 碰撞净距校验并简化为 8 个航点；
  最后一个坐标仍为官方 `[5.45, -0.15]`。地图、PGM 和路线均通过任务清单 SHA-256 锁定。
- `task_config.py` 统一解析并校验 profile、单题地图和单题路线，拒绝越出 `config/` 的
  路径；`compile_tasks.py` 应用路线时强制保留官方最终目标；`run_nav2.sh` 只在任务清单
  声明地图时替换共享场景地图。
- Runner 结果额外保存实际使用的 `nav2_map.yaml`（仅单题地图任务），不改变官方
  `submission/episode.hdf5 + episode.mp4` 事务文件对，也不修改 Runner 或 Nav2 源码。
- 正式隔离回归运行 Q02/Q06/Q05/Q07/Q09，五题均生成三视角视频和有效官方文件对；
  Q02、Q06、Q07、Q09 导航成功，Q05 在距目标 3.415 m 处物理受阻，总成功率 4/5。
- Q02/Q06/Q07/Q09 已按本次真实 Runner 证据锁定；Q05 保持失败且不锁定。完整数据见
  `TEST_REPORT_20260901.md`。

## 2026-08-31：独立远距第三人称追随录像

- 保留第五台 `overview` 正交俯视相机；只在调试入口额外启用第六台 1280×720 透视相机，
  其侧车文件为 `chase.mp4`。
- 追随相机复用官方录像相机的机械狗朝向，不引入路径预测或平滑控制。首次 Q01 实拍使用
  后方 4.5 m、上方 2.2 m、目标前移 1.2 m，虽然录像完整，但机械狗主体持续被裁在画面
  下沿，因此该批次在 Q02 停止并作为失败校准保留。
- 第二版眼点改为机器人后方 4.5 m、上方 1.4 m，目标位于底盘后方 0.3 m、上方 0.5 m；
  多帧实拍已能显示更大场景，但后腿仍越过画面下沿，因此仍判定不合格。
- 第三版继续使用简单常量：眼点位于后方 5.0 m、上方 1.2 m，直接看向底盘中心上方
  0.1 m；多帧中主体已完整可辨，但足端仍偶尔触及下边缘，因此继续缩小画面占比。
- 第四版后距增加到 6.0 m、高度保持 1.2 m，视线落在底盘中心；它保持第三版低俯角，
  同时把整机投影再缩小约 17%，为四足末端留出稳定边距并进一步扩大场景视野。
- 用户确认第四版角度后要求大幅扩大视野。第五版保持上述位姿不变，只把运行时读取的
  默认焦距乘以 0.5，使目标平面的横向覆盖范围约翻倍；日志记录原/新焦距、水平光圈和
  计算所得水平 FOV，方便复核。透视模型不变，不引入鱼眼或后处理变形。
- `NAV2_CHASE_OUTPUT` 与 `NAV2_OVERVIEW_OUTPUT` 都只写独立侧车挂载；执行器仅把两段视频
  复制到结果任务目录，`submission/` 仍严格只有官方同步生成的 HDF5/MP4 文件对。
- 调试 runtime 改为 `cache/overview_runtime/<patched-sha256>/m20_fourview_runner.py`；批次
  启动时固定绝对路径，因此新构建不能改变已启动批次所用代码。
- 新补丁已针对镜像内官方源文件（SHA-256 `6f1e3327…06b3`）完成精确上下文转换并通过
  Python 编译，生成副本 SHA-256 为 `9260213e…a451`。真实 Isaac 画面校准需等当前旧版
  Q01–Q24 批次释放 GPU 后执行，避免影响待提交结果。
- 两台额外相机的调试入口墙钟余量改为 1800 秒；普通入口和正式提交逻辑不变。

## 2026-08-31：批次耗时与 ETA 日志

- `run_all_tasks.sh` 记录每题从整栈启动、预检、Runner 推理到收尾清理的完整墙钟耗时；
  失败与超时任务同样记录，避免 ETA 只统计成功样本而过度乐观。
- 第一题完成前以 1800 s/题生成初始 ETA；之后用当前批次所有已完成任务的平均墙钟耗时
  重算剩余秒数和预计完成时间。日志使用单行键值格式，`runs.tsv` 同步保存数值字段。
- 旧批次暴露出 `trap cleanup EXIT INT TERM` 在 TERM 后执行清理却返回主循环的问题。新版
  将 EXIT 清理与 INT/TERM 退出处理分开，收到信号后以 130/143 退出，不再启动下一题。

## 2026-09-01：Q05 USD 几何核验与东侧绕行

- 失败回放的最终位置为 `[-43.768, -90.756]`，距官方终点 3.415 m。使用临时只读
  Isaac Sim/pxr 探针核对目标区域 USD 后，确认官方直线段穿过黄色料箱：其世界坐标边界
  约为 `x=-43.381~-42.740, y=-91.724~-91.259`；失败点与机器人半径相加后正好接触它。
- 料箱东侧与下一个油桶之间约有 3.1 m 实际通道。Q05 独立路线保留前四个公开航点，
  然后经 `[-41.5,-89.8] -> [-41.5,-93.5]` 从东侧绕过料箱；末段恢复官方安全接近方向，
  经 `[-43.2,-96.8]` 到达不变的官方终点 `[-45.1,-93.9]`。
- `config/tasks/Q05/` 新增 hash 锁定的 `route_override.json` 与 Q05 专用 USD 投影地图。
  地图分辨率 0.10 m、尺寸 151×538，只沿已核验路线清理 1.10 m 导航走廊；扣除 0.60 m
  inflation 后有 0.50 m 横向纠偏空间，且 USD 边界证明可规划中心仍在料箱和油桶之间。
- 纯栅格连通性检查在 0.0、0.4、0.5、0.6 m 四种障碍净距下均能从起点抵达终点；
  任务清单校验输出 `VALID_TASK_CONFIGS=24`，策略单元测试 15 项通过。
- 第一版使用 0.65 m 走廊和东北侧短接近线，成功绕过料箱但进入白箱区，最小距离
  0.884 m；第二版恢复官方末段方向，但轨迹在 `[-41.065,-90.510]` 横向偏离中心 0.435 m，
  由于可纠偏余量仅 `0.65-0.60=0.05 m`，Nav2 报 `Starting point in lethal space`，最小
  距离 5.236 m。两次失败均完整保存三视角视频与有效官方文件对。
- 第三版只把 Q05 走廊改为 1.10 m，真实 Runner 在 220 次请求内到达 0.061 m，
  `navigation_reached=true`、一次目标、无超时；三段视频均为 225 秒，官方提交文件对验证
  通过。Q05 已按 `results_20260901_170204_578850115/Q05` 证据标记成功并锁定。
- 几何与地图探针均为临时文件，不属于 Policy；验证完成后删除本机和服务器临时副本。

## 2026-09-01：同版本 24 题无攻击完整回归

- 批次 `results_20260901_192331_535704189/` 完成 Q01–Q24，所有任务使用独立
  Runner/Isaac Sim 进程且攻击关闭；总墙钟时间 4 小时 26 分 54 秒。
- `navigation_reached=true` 为 16/24（66.7%），严格提交级为 14/24（58.3%），相比
  上一完整批次两种口径均净增加 2 题。Q02/Q05/Q06/Q07 改善，Q04 因提前结束回退，
  Q08 因 OOM 未运行。
- 17/24 官方文件对有效，72/72 三视角视频可解码。Q16 导航已成功但 Runner 后续超时；
  Q15 的状态成功与严格 0.25 m 几何阈值存在 0.0157 m 边界差异，提交评估按失败处理。
- Q10–Q12 的路线膨胀障碍校验错误和 Q17/Q21 的题包 SHA-256 错误在 Policy 运行前发生，
  与 Nav2 规划无关；当前代码不绕过或修改官方 Runner/题包校验。

## 2026-09-02：官方镜像攻击模式全量回归入口

- 普通 `run_all_tasks.sh` 继续直接使用 `safety-embodiment:20260817`；本轮显式设置
  `RUNNER_OVERVIEW=0`、`RUNNER_CHASE=0`，不构建、不挂载 `m20_fourview_runner.py` 副本。
- `run_runner_task.sh` 新增受校验的 `ATTACK_MODE=on|off`，默认值仍为 `off`；实际值同时
  传给官方 CLI 并写入 `run_summary.json`，防止攻击回归与无攻击回归混淆。

## 2026-09-04：记录官网成绩

- 当前竞赛官网实得分为 **12 分**。
- 官网得分与本地导航到达率、严格几何验收率分开记录，避免把导航子任务统计误写为
  竞赛最终成绩。
