"""麦麦喊新人说话！(加群考察期) 插件配置模型。

功能：新人入群自动 @ 欢迎邀请发言，超过考察时长（默认 48h）未发言自动移出。
移出是确定性代码行为，不注册任何 LLM 工具；需要 bot 有群管理员权限。

联动：若「麦麦看到你了！」(group-awareness-plugin) 已启用，本插件自动禁用
（考察期由群感知插件执行，配置以群感知读取的为准）。
"""

from typing import Any, Literal

from maibot_sdk import Field, PluginConfigBase
from pydantic import field_validator


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(
        default=True,
        description="是否启用插件",
        json_schema_extra={"label": "启用插件"},
    )
    config_version: str = Field(
        default="1.0.0",
        description="配置版本",
        json_schema_extra={"label": "配置版本", "disabled": True},
    )
    sibling_awareness_config: str = Field(
        default="",
        description=(
            "「麦麦看到你了！」插件的 config.toml 完整路径（可选）。"
            "留空自动在插件目录同级查找 group-awareness-plugin/ 下的配置"
        ),
        json_schema_extra={"label": "群感知联动配置路径", "hint": "留空自动探测兄弟插件目录"},
    )


class GreetConfig(PluginConfigBase):
    """新人入群欢迎消息。"""

    __ui_label__ = "入群欢迎"
    __ui_icon__ = "wave"

    mode: Literal["template", "llm"] = Field(
        default="template",
        description="欢迎方式：template=固定模板；llm=按人设生成（有 API 费用）",
        json_schema_extra={"label": "欢迎方式", "hint": "template / llm"},
    )
    fallback_to_template: bool = Field(
        default=True,
        description="llm 模式生成失败时降级用固定模板；关闭则失败时不发送欢迎",
        json_schema_extra={"label": "失败降级模板"},
    )
    template: str = Field(
        default="欢迎新朋友加入～出来冒个泡认识一下？",
        description="mode=template 时的欢迎文案，或 llm 失败降级时的文案（自动 @ 新人）",
        json_schema_extra={"label": "固定文案", "placeholder": "欢迎新朋友加入～"},
    )

    @field_validator("mode")
    @classmethod
    def _validate_greet_mode(cls, value: Any) -> Literal["template", "llm"]:
        normalized = "" if value is None else str(value).strip().lower()
        if normalized in ("template", "llm"):
            return normalized  # type: ignore[return-value]
        return "template"


class KickMessageConfig(PluginConfigBase):
    """移出新成员的说明消息。"""

    __ui_label__ = "移出说明"
    __ui_icon__ = "log-out"

    mode: Literal["template", "llm"] = Field(
        default="template",
        description="移出说明方式：template=固定模板；llm=按人设生成（有 API 费用）",
        json_schema_extra={"label": "说明方式", "hint": "template / llm"},
    )
    fallback_to_template: bool = Field(
        default=True,
        description="llm 模式生成失败时降级用固定模板；关闭则失败时不发送说明（移出照常执行）",
        json_schema_extra={"label": "失败降级模板"},
    )
    template: str = Field(
        default="成员 {member_name}（QQ {user_id}）加入超过 {probation_hours} 小时未发言，已移出群聊。",
        description=(
            "mode=template 时的说明文案，或 llm 失败降级时的文案。占位符："
            "{member_name} 昵称；{user_id} 被移出者 QQ；{probation_hours} 考察时长（小时）"
        ),
        json_schema_extra={"label": "固定文案"},
    )

    @field_validator("mode")
    @classmethod
    def _validate_kick_mode(cls, value: Any) -> Literal["template", "llm"]:
        normalized = "" if value is None else str(value).strip().lower()
        if normalized in ("template", "llm"):
            return normalized  # type: ignore[return-value]
        return "template"


class LLMConfig(PluginConfigBase):
    """欢迎/移出说明的 LLM 生成参数。"""

    __ui_label__ = "LLM"
    __ui_icon__ = "sparkles"

    model: Literal["utils", "replyer", "planner"] = Field(
        default="planner",
        description=(
            "LLM 任务槽位（对应 Host model_task_config 下的任务名）："
            "utils=通用快模型；replyer=主回复模型（最贴人设但可能较慢）；planner=规划快模型"
        ),
        json_schema_extra={"label": "模型槽位", "hint": "utils / replyer / planner"},
    )
    temperature: float = Field(
        default=0.8,
        description="生成温度",
        json_schema_extra={"label": "温度", "min": 0, "max": 2, "step": 0.1},
    )
    max_tokens: int = Field(
        default=128,
        description="最大生成 token，0 表示不覆盖用 Host 配置",
        json_schema_extra={"label": "最大 token", "min": 0},
    )

    @field_validator("model")
    @classmethod
    def _validate_model(cls, value: Any) -> Literal["utils", "replyer", "planner"]:
        normalized = "" if value is None else str(value).strip().lower()
        if normalized in ("utils", "replyer", "planner"):
            return normalized  # type: ignore[return-value]
        return "planner"


class ProbationConfig(PluginConfigBase):
    """加群考察期：新成员超时未发言自动移出。

    移出是确定性代码行为（定时检查 + 条件判断），不注册任何 LLM 工具，
    机器人不会自主决定移出谁。需要 bot 拥有群管理员权限才能执行移出。

    作用域边界：仅对 enabled_groups 中列出的群生效；列表为空时不执行任何
    考察/移出（也不会登记新成员）。kick 属于高影响操作，必须显式列群。
    """

    __ui_label__ = "考察期"
    __ui_icon__ = "timer"
    __ui_order__ = 1

    enabled: bool = Field(
        default=False,
        description=(
            "启用加群考察期（需要 bot 有群管理员权限，仅用于自动移出超时未发言的新成员，"
            "LLM 不参与决策）"
        ),
        json_schema_extra={"label": "启用考察期", "hint": "需 bot 有群管理员权限"},
    )
    enabled_groups: list[str] = Field(
        default_factory=list,
        description=(
            "启用考察期的群号白名单（群号，字符串）。空数组表示不作用于任何群，"
            "不执行考察也不会移出任何成员。仅列表中的群会登记/考察/移出新人。"
        ),
        json_schema_extra={
            "label": "启用群列表",
            "hint": "必填：考察期仅对列出的群号生效，空数组则全局停用",
        },
    )
    probation_hours: float = Field(
        default=48.0,
        description="考察时长（小时），超时未发言的新成员将被移出",
        json_schema_extra={"label": "考察时长（小时）", "min": 0},
    )
    check_interval_minutes: int = Field(
        default=30,
        description="检查间隔（分钟）",
        json_schema_extra={"label": "检查间隔（分钟）", "min": 1},
    )
    min_messages: int = Field(
        default=0,
        description=(  # noqa
            "转正消息数阈值：进群后累计发言达到该条数即转正（不再仅看是否发过言）。"
            "0 表示不启用，保持原行为（进群后发过言即转正）。"
        ),
        json_schema_extra={"label": "转正消息数阈值", "hint": "0=不改用原行为；达到条数即转正", "min": 0},
    )
    llm_judge: bool = Field(
        default=False,
        description=(  # noqa
            "考察期满仍未转正时，用 LLM 判断该号是否为正常号/真人："
            "明确判定异常（广告/机器人等）才移出，其余保守保留。"
            "关闭则到期直接移出（原行为）。"
        ),
        json_schema_extra={"label": "到期 LLM 判号", "hint": "判定异常才移出，避免误踢真人"},
    )
    llm_judge_prompt: str = Field(
        default="",
        description=(
            "判号提示词（自定义文本）。留空使用内置默认。占位符："
            "{member_name} 昵称；{user_id} QQ；{hours} 进群小时；"
            "{message_count} 考察期内发言数；{min_messages} 转正消息数阈值；"
            "{progress} 未转正原因（按 min_messages 自动生成）。"
        ),
        json_schema_extra={"label": "判号提示词", "hint": "留空用内置默认；可自定义并带占位符"},
    )
    reject_add_request: bool = Field(
        default=False,
        description="移出时拒绝该成员再次申请加群",
        json_schema_extra={"label": "拒绝再次加群"},
    )
    whitelist: list[str] = Field(
        default_factory=list,
        description="白名单 QQ（永不考察、永不移出）",
        json_schema_extra={"label": "白名单 QQ"},
    )
    greet: GreetConfig = Field(
        default_factory=GreetConfig,
        description="新人入群欢迎（自动 @ 新人）",
        json_schema_extra={"label": "入群欢迎"},
    )
    kick_message: KickMessageConfig = Field(
        default_factory=KickMessageConfig,
        description="移出新成员的说明消息",
        json_schema_extra={"label": "移出说明"},
    )
    llm: LLMConfig = Field(
        default_factory=LLMConfig,
        description="欢迎/移出说明的 LLM 生成参数（greet/kick_message 的 llm 模式使用）",
        json_schema_extra={"label": "LLM 参数"},
    )


class GroupProbationConfig(PluginConfigBase):
    """麦麦喊新人说话！插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    probation: ProbationConfig = Field(default_factory=ProbationConfig)


def create_config():
    """创建默认配置实例。"""
    return GroupProbationConfig()