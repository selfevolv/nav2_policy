#!/usr/bin/env bash
set -eo pipefail

PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
NAV2_ROOT="${NAV2_ROOT:-/home/youlika/navigation2_reproduction}"
CONDA_BIN="${CONDA_BIN:-/home/youlika/miniconda3/bin/conda}"

eval "$("$CONDA_BIN" shell.bash hook)"
conda activate navigation2
source "$NAV2_ROOT/navigation2_ws/install_gcc11/setup.bash"
source "$NAV2_ROOT/isaac_ros_ws/install/setup.bash"

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export ROS_DISTRO=humble
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp

# The conda underlay has nav2_msgs 1.1.18 and the source overlay has 1.1.20.
# Match the known-good Carter reproduction without changing either installation.
NAV2_MSGS_LIB="$NAV2_ROOT/navigation2_ws/install_gcc11/nav2_msgs/lib"
NAV2_PRELOAD="$NAV2_MSGS_LIB/libnav2_msgs__rosidl_generator_c.so:$NAV2_MSGS_LIB/libnav2_msgs__rosidl_generator_py.so:$NAV2_MSGS_LIB/libnav2_msgs__rosidl_typesupport_c.so:$NAV2_MSGS_LIB/libnav2_msgs__rosidl_typesupport_fastrtps_c.so:$NAV2_MSGS_LIB/libnav2_msgs__rosidl_typesupport_introspection_c.so"
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:${LD_LIBRARY_PATH:-}"
export LD_PRELOAD="$NAV2_PRELOAD${LD_PRELOAD:+:$LD_PRELOAD}"
export PROJECT_DIR NAV2_ROOT
