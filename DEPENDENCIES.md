# 依赖与兼容环境

本文记录已完成真实 Runner 视频验证的环境。`requirements-policy.txt` 只包含 Policy
自身的 Python 包；ROS 2、Nav2 和 Isaac Sim 不能仅靠 pip requirements 部署。

## 已验证平台

| 组件 | 版本/要求 |
| --- | --- |
| 操作系统 | Ubuntu 22.04 LTS，x86_64 |
| Python | 3.11.15 |
| ROS 2 | Humble |
| RMW | `rmw_fastrtps_cpp` |
| Nav2 | 1.1.20 源码覆盖层；Humble 接口 |
| Isaac Sim | 5.1.0，提供 `SimulationApp` 与 bundled `pxr` |
| Runner 镜像 | `safety-embodiment:20260817` |
| NVIDIA 驱动 | 580.159.03（当前验证机） |
| NVIDIA Container Toolkit | 1.19.1（当前验证机） |

已验证 Python 包：

| 包 | 版本 | 用途 |
| --- | ---: | --- |
| `numpy` | 1.26.4 | Runner 状态和动作数组 |
| `msgpack` | 1.2.2 | WebSocket 二进制协议 |
| `websockets` | 16.1.1 | 同步 Policy 服务和自测客户端 |

ROS 运行时还必须提供以下包或等价源码覆盖层：

- `rclpy`、`geometry_msgs`、`nav_msgs`、`tf2_ros`；
- `nav2_msgs`、`nav2_bringup`、`nav2_map_server`；
- `nav2_smac_planner`、`nav2_mppi_controller`；
- `nav2_velocity_smoother`、`nav2_bt_navigator`、`nav2_lifecycle_manager`；
- `nav2_behaviors`、`nav2_waypoint_follower`、`nav2_smoother`。

当前部署直接复用只读的既有覆盖层：

```text
/home/youlika/navigation2_reproduction/navigation2_ws/install_gcc11
/home/youlika/navigation2_reproduction/isaac_ros_ws/install
```

项目不会修改这两个目录。`scripts/env.sh` 仅 source 它们，并使用独立
`ROS_DOMAIN_ID=42`。

## 系统工具

- Docker 与 NVIDIA Container Toolkit：运行官方 Runner/Isaac Sim 容器；
- `ffmpeg`、`ffprobe`：视频验证，以及 Runner 在录像器启动前失败时生成明确标记的
  诊断占位视频；
- Bash、`setsid`、`nohup`、`ss`：进程隔离、后台批次和端口健康检查；
- GNU coreutils/diffutils：`sha256sum`、`mktemp`、`cmp`，用于校验并生成俯视 runtime 副本；
- Git：版本管理。

## Python 包安装

在已经能够导入 ROS 2 Humble `rclpy` 和 Nav2 消息的 Python 3.11 环境中执行：

```bash
python -m pip install -r requirements-policy.txt
```

当前服务器使用 Conda 环境 `navigation2`。不要用纯 Python 虚拟环境覆盖
`scripts/env.sh`，否则会丢失 ROS 2/Nav2 包和动态库路径。

## 依赖检查

```bash
source scripts/env.sh

python -c 'import numpy, msgpack, websockets, rclpy; print("Python dependencies OK")'
ros2 pkg prefix nav2_bringup
ros2 pkg prefix nav2_smac_planner
ros2 pkg prefix nav2_mppi_controller
docker image inspect safety-embodiment:20260817 >/dev/null
ffmpeg -version
```

USD 地图生成器必须用 Isaac Sim 自带的 Python 启动，不能用普通 Conda Python：

```bash
/home/youlika/navigation2_reproduction/isaacsim/python.sh \
  generate_usd_maps.py --help
```
