# 麦麦喊新人说话！（加群考察期）

> **⚠️ 免责声明**：本插件由 AI 辅助生成，代码可能存在未知缺陷或不当行为。使用前请自行审阅源码、评估风险，并对其在你的环境中产生的任何后果负责。

新人入群自动 @ 欢迎邀请发言，超过考察时长（默认 48 小时）未发言的新成员自动移出群聊。

## 与「麦麦看到你了！」的联动（互斥）

若同时安装了「麦麦看到你了！」（`group-awareness-plugin`）且其 `[plugin] enabled = true`，**只启用群感知插件执行考察期**：

1. 本插件（麦麦喊新人说话！）**自动禁用**（启动时检测到群感知已启用，日志说明原因），避免重复 @ / 重复移出
2. 群感知插件会**读取本插件的 `[probation]` 配置**作为考察期配置（配置只维护一份，改本插件这里即可，群感知自动生效）

场景对照：

| 安装情况 | 执行者 | 配置来源 |
|---|---|---|
| 只装本插件 | 本插件 | 本插件 `[probation]` |
| 只装群感知 | 群感知 | 群感知自带 `[probation]` |
| 两个都装 | 群感知（本插件自禁） | 本插件 `[probation]` |

> 注意：若两个都装，`probation.enabled` 开关请在**本插件**（麦麦喊新人说话！）的 config 里修改，群感知会自动读取。

> **联动依赖说明**：本插件通过读取「麦麦看到你了！」插件的 `config.toml` 判断对方是否启用。默认在插件目录同级查找 `group-awareness-plugin/`，也可用 `plugin.sibling_awareness_config` 指定完整路径。若对方插件目录改名或路径变化，本插件会静默降级为不压制（双方可能同时运行，需手动关一个）。

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
