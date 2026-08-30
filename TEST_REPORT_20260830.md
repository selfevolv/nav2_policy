# Nav2 Policy P0 修改测试报告（2026-08-30）

## 结论

P0 修改解决了旧批次最主要的 lifecycle race、过早发目标、陈旧状态误判、动作上限扩展
和提交文件格式问题。四次正式 Runner 测试中，Q04、Q14、Q19 导航成功，Q05 导航失败；
四题均生成真实视频和协议 VALID 的同次 HDF5 文件对。

当前版本不建议直接作为“目标 30 分”的最终整套提交。Q04 是可用的导航-only 候选；
Q14/Q19 仅完成导航、没有操作；Q05 暴露了长距离反向路线的系统性慢速倒行问题。

## 修改内容

1. Bridge 先发布合成出生点 TF，Nav2 后启动；真实 Runner 首帧前禁止发送目标。
2. 每次启动使用新的 ROS Domain 和 run token，删除旧状态并做 8/8 lifecycle 无目标预检。
3. 目标总尝试次数限制为 3，失败采用退避，不再无限 goal rejection。
4. 严格使用公共任务动作/时长上限；采用任务级 1/2/5 Hz 动作频率。
5. navigation-only 使用正式成功半径，操作题使用 route arrival tolerance。
6. 只把同次生成且通过结构校验的 `submission/episode.hdf5 + episode.mp4` 标记为可提交。
7. 汇总分离 Runner 协议有效、导航成功和操作成功，不使用固定 0.5 m 推断。

## 测试层级

### 本地测试

```text
python3 -m unittest discover -s tests -v
Ran 4 tests ... OK
python3 -m compileall ...
bash -n scripts/*.sh
git diff --check
```

覆盖 navigation-only 正式半径、操作题 route 阈值、任务级动作频率，以及文件对/token
参与导航验收的逻辑。

### ROS 隔离测试

Q04 使用新 Domain 启动，结果：

```json
{
  "ready": true,
  "lifecycle_active": "8/8",
  "action_server": true,
  "goal_sent": false,
  "goal_attempts": 0,
  "request_count": 0
}
```

这证明初始 TF 足以激活 Nav2，同时合成状态不会再提前触发目标。

### 正式 Runner 测试

全部使用 attack off、kinematic base、官方任务动作上限和官方时长。

| 任务 | Hz | 上限 | 请求数 | 最小距离/阈值 m | 导航 | Runner/文件对 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Q04 | 2 | 400 | 302 | 0.102/0.600 | 成功 | VALID/有效 |
| Q05 | 1 | 400 | 239 | 8.289/0.600 | 失败 | VALID/有效 |
| Q14 | 5 | 500 | 500 | 0.070/0.250 | 成功 | VALID/有效 |
| Q19 | 5 | 600 | 600 | 0.118/0.250 | 成功 | VALID/有效 |

四题 lifecycle 第一次预检均成功，目标均只提交一次。Q14/Q19 因不执行操作而采满动作，
但到站后距离保持稳定。

## 结果与 SHA-256

### Q04（推荐保留的导航-only 候选）

目录：

```text
/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy/results/Q04/nav2_p0_q04_20260830_q04/submission
```

- `episode.hdf5`：1,919,795 bytes；`ffbda58e145111f1c210912741dbbb3c4d3947d6e52e5f62370068a5dac72028`
- `episode.mp4`：46,366,799 bytes；`f1421b4acb728a609ecdf0595c6857c6dfeeaae4b8b2e5c78a83275f1ea50bca`

### Q05（真实失败证据，不建议提交）

- HDF5：`dd384eac9668ba75ef1551ba09a6a4ee69c181901fc823aad68c509bcc7dcd0c`
- MP4：`de283d6c5ad332fb680445984a6ce86b6d1a95c6f5cf46be561d35c4a197bde2`

### Q14

- HDF5：`1b76c0623c506466e009ced42d79455656ec0c80d39c81e8f3de57b17b5aba68`
- MP4：`e6ab4f18fdc8ba6b1d85b2684918a9ffec2727ae307f81cee801260628131a32`

### Q19

- HDF5：`8386f07f234e4a19de1ffec2597094ddd17691566f50f3f8070ea2333ec54266`
- MP4：`76d0d06139d70d0add41c8a62964e42057d31c9bf6cd488b6ce31c9e54e02776`

## Q05 失败分析

Q05 并未发生 lifecycle、Action Server、地图规划或文件导出错误。目标一次被接受，距离从
约 41 m 持续下降到 8.289 m，但大部分时间命令接近：

```text
vx=-0.12 m/s, vy=-0.02~-0.09 m/s
```

当前 MPPI 允许倒车，`vx_min=-0.12` 且 `PathAngleCritic.forward_preference=false`。
Q05 初始路线与机器人朝向相反，控制器选择慢速倒行而不是转向后以 0.25 m/s 前进。
把动作频率降到 1 Hz 解决了动作计数限制，却无法突破 240 秒物理时长限制。

## 下一轮建议（尚未实施）

1. 新增一个简单的 forward-only 参数预设：`vx_min=0.0`、
   `PathAngleCritic.forward_preference=true`，仅用于 Q02/Q05/Q06/Q07 等反向长路线。
2. 先只对 Q05 做正式 A/B；目标是 180 秒内进入 0.60 m，并确认没有碰撞或振荡。
3. A/B 通过后回归 Q04，防止 forward-only 设置破坏已成功的正向路线。
4. Q10–Q12 的 Runner `route intersects inflated obstacle KitchenIsland` 属于官方预检阻塞，
   修改 Nav2 PGM 无法解决；应等待任务包/Runner 修正或单独向赛方反馈。
5. Q09 的 Runner `NoneType` 异常及 Q17/Q21 attack profile SHA 不匹配也应先做环境预检，
   不应计为 Policy 参数失败。

## 提交建议

- 不建议提交 Q05。
- 如果官网一次提交只接收单任务文件对，Q04 是四次测试里唯一同时属于 navigation-only、
  正式动作上限内成功、且文件对 VALID 的明确候选。
- Q14/Q19 的文件对可证明导航成功，但完整任务必然因操作为空而无法获得满分；在只有三次
  提交机会时不建议仅凭导航结果占用正式提交次数。
- 在 forward-only Q05 A/B 完成前，无法对“达到 30 分”作可靠保证。
