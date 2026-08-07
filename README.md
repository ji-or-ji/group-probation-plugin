# 麦麦喊新人说话！（加群考察期）

> **⚠️ 免责声明**：本插件由 AI 辅助生成，代码可能存在未知缺陷或不当行为。使用前请自行审阅源码、评估风险，并对其在你的环境中产生的任何后果负责。

新人入群自动 @ 欢迎邀请发言，超过考察时长（默认 48 小时）未发言的新成员自动移出群聊。

## 功能

- **入群欢迎**：新人进群自动 @ TA 并发送欢迎文案（固定模板或 LLM 按人设生成），邀请出来说话
- **考察期**：新人进群后开始计时，周期检查发言状态
  - 已发言 → 转正，移出考察
  - 群主 / 管理员 / 白名单 → 排除，永不考察
  - 超时未发言 → 自动移出（`set_group_kick`），并在群内发送说明（含被移出者 QQ 号）
- **持久化**：考察名单存于 `data/plugins/group-probation-plugin/probation.json`，重启不丢，超时者不会被漏踢

## 安全边界

- 移出是**确定性代码**（定时检查 + 条件判断），**不注册任何 LLM 工具**，机器人不会自主决定移出谁
- 需要 bot 拥有**群管理员权限**，该权限仅用于执行 `set_group_kick`
- 白名单 QQ、群主、管理员永远不受考察

## 与「麦麦看到你了！」的联动

若同时安装了「麦麦看到你了！」（`group-awareness-plugin`）且其 `[plugin] enabled = true`：

1. 本插件（麦麦喊新人说话！）**自动禁用**，考察期由群感知插件执行，避免重复 @ / 重复移出
2. 群感知插件会**读取本插件的 `[probation]` 配置**作为考察期配置（配置只维护一份，改这里即可）

若未安装或未启用「麦麦看到你了！」，本插件独立运行。

## 配置

```toml
[plugin]
enabled = true

[probation]
enabled = false            # 启用考察期（需 bot 有群管理员权限）
probation_hours = 48       # 考察时长（小时），可改
check_interval_minutes = 30
reject_add_request = false # 移出时是否拒绝再次加群
whitelist = []             # 白名单 QQ，永不考察

[probation.greet]
mode = "template"          # template / llm（人格化，有 API 费用）
template = "欢迎新朋友加入～出来冒个泡认识一下？"

[probation.kick_message]
mode = "template"          # template / llm
template = "成员 {member_name}（QQ {user_id}）加入超过 {probation_hours} 小时未发言，已移出群聊。"

[probation.llm]
model = "planner"          # utils / replyer / planner
temperature = 0.8
max_tokens = 128
```

## 上线步骤

1. 重启 MaiBot，插件加载
2. WebUI 将 `probation.enabled` 置 `true`
3. 在目标群将 bot 设为管理员
4. 建议先用短考察时长（如 1 小时）实测踢人链路，确认无误再改回 48h

## 环境要求

- MaiBot >= 1.0.0，SDK >= 2.0.0
- NapCat 适配器（提供 `set_group_kick` / `send_group_msg` / `get_group_member_info` API）
- 模型槽位 `planner`（LLM 模式需要）
