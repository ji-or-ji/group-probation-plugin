"""麦麦喊新人说话！(加群考察期) 插件 — MaiBot SDK v2

新人入群时自动 @ 欢迎邀请发言，并加入考察名单；周期检查：
已发言转正、群主/管理员/白名单排除、超时（默认 48h）未发言自动移出，
移出后发送说明消息（含被移出者 QQ 号）。

安全边界：
- 移出是确定性代码（定时检查 + 条件判断），不注册任何 LLM 工具，
  机器人不会自主决定移出谁
- 需要 bot 拥有群管理员权限（仅用于 set_group_kick）

联动：「麦麦看到你了！」(group-awareness-plugin) 已启用时，本插件自动禁用，
考察期由群感知插件执行（配置以群感知读取的为准），避免重复 @ / 重复移出。
"""

from __future__ import annotations

import asyncio
import json
import time
import tomllib
from pathlib import Path
from typing import Any, Optional

from maibot_sdk import HookHandler, MaiBotPlugin
from maibot_sdk.types import ErrorPolicy, HookMode, HookOrder

from .config import GroupProbationConfig

EVT_INCREASE = "group_increase"
EVT_DECREASE = "group_decrease"

# 联动：检测到的群感知插件目录名（麦麦看到你了！）
SIBLING_AWARENESS_PLUGIN_ID = "group-awareness-plugin"


class GroupProbationPlugin(MaiBotPlugin):
    """麦麦喊新人说话！插件主类。"""

    config_model = GroupProbationConfig

    def __init__(self) -> None:
        super().__init__()
        # 考察名单：{group_id: {user_id: {join_ts, member_name}}}，持久化到 data 目录
        self._probation: dict[str, dict[str, dict[str, Any]]] = {}
        self._probation_file: Path | None = None
        self._probation_task: asyncio.Task | None = None
        # 被群感知插件压制（联动禁用）
        self._suppressed = False

    # ===== 生命周期 =====

    async def on_load(self) -> None:
        self._probation_file = Path(self.ctx.paths.data_dir) / "probation.json"

        # 联动检测：群感知插件已启用 → 本插件自动禁用（避免重复执行）
        if self._sibling_awareness_enabled():
            self._suppressed = True
            self.ctx.logger.info(
                "[考察期] 检测到「麦麦看到你了！」已启用，本插件自动禁用（考察期由群感知插件执行）",
            )
            return

        self._probation_load()
        if self.config.probation.enabled:
            self._probation_task = asyncio.create_task(
                self._probation_loop(), name="group-probation.probation",
            )
        self.ctx.logger.info(
            "麦麦喊新人说话！插件已加载（考察期=%s）",
            "开" if self.config.probation.enabled else "关",
        )

    async def on_unload(self) -> None:
        if self._probation_task:
            self._probation_task.cancel()
            self._probation_task = None
        self._probation_persist()
        self.ctx.logger.info("麦麦喊新人说话！插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        if self._suppressed:
            return
        if self._probation_task:
            self._probation_task.cancel()
            self._probation_task = None
        if self.config.probation.enabled:
            self._probation_task = asyncio.create_task(
                self._probation_loop(), name="group-probation.probation",
            )
        self.ctx.logger.info(
            "麦麦喊新人说话！配置已热更新: scope=%s（考察期=%s）",
            scope, "开" if self.config.probation.enabled else "关",
        )

    # ===== 联动检测 =====

    def _sibling_awareness_enabled(self) -> bool:
        """检测「麦麦看到你了！」是否已启用（读它的 config.toml）。"""
        try:
            # __file__ = plugins/<本插件>/plugin.py → parents[1] = plugins/ 根目录
            sibling_cfg = (
                Path(__file__).resolve().parents[1]
                / SIBLING_AWARENESS_PLUGIN_ID
                / "config.toml"
            )
            if not sibling_cfg.exists():
                return False
            with open(sibling_cfg, "rb") as f:
                data = tomllib.load(f)
            return bool(data.get("plugin", {}).get("enabled", False))
        except Exception as exc:
            self.ctx.logger.debug("[考察期] 联动检测异常: %s", exc)
            return False

    # ===== 事件处理 Hook =====

    @HookHandler(
        "chat.receive.before_process",
        name="group_probation_listener",
        description="感知新人进群/退群通知，维护考察名单",
        mode=HookMode.BLOCKING,
        order=HookOrder.EARLY,
        timeout_ms=3000,
        error_policy=ErrorPolicy.SKIP,
    )
    async def handle_group_notice(self, message: dict | None = None, **kwargs):
        del kwargs
        if self._suppressed or not self.config.plugin.enabled:
            return None

        ctx = self._extract_notice_context(message)
        if ctx is None:
            return None

        # 进群：加入考察名单 + @ 欢迎
        if ctx["event"] == EVT_INCREASE and self.config.probation.enabled:
            await self._handle_probation_join(ctx)
        # 退群：清理考察名单（人已不在群，无需保留）
        elif ctx["event"] == EVT_DECREASE:
            self._probation_remove(ctx["group_id"], ctx.get("user_id") or "")
            self._probation_persist()

        # 通知事件不应进入主链路被当作聊天消息回复
        return {"action": "abort"}

    def _extract_notice_context(self, message: Any) -> Optional[dict[str, Any]]:
        """从消息 dict 中提取进群/退群通知；不是目标事件时返回 None。"""
        if not isinstance(message, dict):
            return None
        if not message.get("is_notify"):
            return None

        msg_info = message.get("message_info") or {}
        if not isinstance(msg_info, dict):
            return None
        additional = msg_info.get("additional_config") or {}
        if not isinstance(additional, dict):
            return None

        notice_type = str(additional.get("napcat_notice_type") or "").strip()
        payload = additional.get("napcat_notice_payload") or {}
        if not isinstance(payload, dict):
            return None

        group_id = str(payload.get("group_id") or "").strip()
        if not group_id:
            return None

        if notice_type not in (EVT_INCREASE, EVT_DECREASE):
            return None

        user_id = str(payload.get("user_id") or "").strip()
        if not user_id:
            return None

        return {
            "event": notice_type,
            "group_id": group_id,
            "user_id": user_id,
            "summary": str(additional.get("napcat_notice_summary") or ""),
        }

    # ===== 考察期逻辑 =====

    async def _handle_probation_join(self, ctx: dict[str, Any]) -> None:
        """新人进群：加入考察名单并发送 @ 欢迎。"""
        user_id = ctx["user_id"]
        cfg = self.config.probation

        # 解析昵称（进群时成员在群内，可查到）
        member_name = await self._resolve_member_name(ctx["group_id"], user_id) or user_id

        self._probation.setdefault(ctx["group_id"], {})[user_id] = {
            "join_ts": time.time(),
            "member_name": member_name,
        }
        self._probation_persist()

        text = ""
        if cfg.greet.mode == "llm":
            text = await self._generate_text(
                f"QQ 群里刚有新成员加入：{member_name}（QQ {user_id}）。"
                "请以你的性格自然地欢迎 TA，并邀请 TA 出来说句话冒个泡。"
                "简短、口语化，只输出要说的话。"
            )
        if not text:
            text = cfg.greet.template or "欢迎新朋友加入～"
        await self._send_at_message(ctx["group_id"], user_id, text)
        self.ctx.logger.info(
            "[考察期] 新人 %s(%s) 加入考察名单，欢迎已发送", member_name, user_id,
        )

    async def _probation_loop(self) -> None:
        """周期检查考察名单（超时未发言者移出）。"""
        interval = max(1, self.config.probation.check_interval_minutes) * 60
        while True:
            await asyncio.sleep(interval)
            try:
                await self._check_probation()
            except Exception as exc:
                self.ctx.logger.info("[考察期] 检查异常: %s", exc, exc_info=True)

    async def _check_probation(self) -> None:
        """遍历考察名单：转正（已发言）、排除（管理员/白名单/已退群）、移出（超时未发言）。"""
        cfg = self.config.probation
        if not cfg.enabled:
            return
        whitelist = set(cfg.whitelist)
        now = time.time()
        probation_seconds = float(cfg.probation_hours) * 3600

        for group_id, members in list(self._probation.items()):
            for user_id, entry in list(members.items()):
                # 白名单跳过
                if user_id in whitelist:
                    self._probation_remove(group_id, user_id)
                    continue
                # 查询成员状态
                try:
                    result = await self.ctx.api.call(
                        "adapter.napcat.group.get_group_member_info",
                        group_id=int(group_id),
                        user_id=int(user_id),
                    )
                except Exception as exc:
                    # 查询失败（已不在群）→ 移出考察
                    self.ctx.logger.info(
                        "[考察期] 查询成员 %s 失败（可能已退群），移出考察: %s", user_id, exc,
                    )
                    self._probation_remove(group_id, user_id)
                    continue
                data = result.get("data") if isinstance(result, dict) else None
                if not isinstance(data, dict):
                    self._probation_remove(group_id, user_id)
                    continue
                role = str(data.get("role") or "")
                if role in ("owner", "admin"):
                    self._probation_remove(group_id, user_id)
                    continue
                last_sent = data.get("last_sent_time") or 0
                # 发过言（进群后）→ 转正
                if isinstance(last_sent, (int, float)) and last_sent > float(entry.get("join_ts") or 0):
                    self.ctx.logger.info(
                        "[考察期] %s(%s) 已发言，转正", entry.get("member_name"), user_id,
                    )
                    self._probation_remove(group_id, user_id)
                    continue
                # 超时未发言 → 移出
                if now - float(entry.get("join_ts") or 0) >= probation_seconds:
                    await self._kick_member(group_id, user_id, entry)
        self._probation_persist()

    async def _kick_member(self, group_id: str, user_id: str, entry: dict[str, Any]) -> None:
        """移出超时未发言成员，并发送移出说明。"""
        cfg = self.config.probation
        try:
            await self.ctx.api.call(
                "adapter.napcat.group.set_group_kick",
                group_id=int(group_id),
                user_id=int(user_id),
                reject_add_request=cfg.reject_add_request,
            )
        except Exception as exc:
            self.ctx.logger.info("[考察期] 移出失败 %s(%s): %s", entry.get("member_name"), user_id, exc)
            return
        self.ctx.logger.info(
            "[考察期] 已移出 %s(%s) from %s（超时未发言）", entry.get("member_name"), user_id, group_id,
        )
        # 移出说明（直接调 API 发纯文本，不依赖 stream 解析）
        text = await self._compose_kick_text(group_id, user_id, entry)
        if text:
            try:
                await self.ctx.api.call(
                    "adapter.napcat.group.send_group_msg",
                    group_id=int(group_id),
                    message=[{"type": "text", "data": {"text": text}}],
                )
            except Exception as exc:
                self.ctx.logger.info("[考察期] 移出说明发送失败: %s", exc)
        self._probation_remove(group_id, user_id)

    async def _compose_kick_text(self, group_id: str, user_id: str, entry: dict[str, Any]) -> str:
        """按配置生成移出说明（llm 优先，失败回退模板）。"""
        cfg = self.config.probation
        text = ""
        if cfg.kick_message.mode == "llm":
            text = await self._generate_text(
                f"群成员 {entry.get('member_name') or user_id}（QQ {user_id}）加入超过 "
                f"{cfg.probation_hours} 小时未发言，已被移出群聊。"
                "请以你的性格自然地说明这件事（要包含被移出者的 QQ 号），简短，只输出要说的话。"
            )
        if not text:
            text = (cfg.kick_message.template or "").replace(
                "{member_name}", entry.get("member_name") or user_id,
            ).replace("{user_id}", user_id).replace(
                "{probation_hours}", str(cfg.probation_hours),
            )
        return text

    async def _generate_text(self, user_prompt: str) -> str:
        """按考察期 llm 槽位生成一句话（失败返回空串，调用方回退模板）。"""
        cfg = self.config.probation.llm
        persona = ""
        try:
            persona = await self.ctx.config.get("personality.personality", "")
        except Exception:
            persona = ""
        system = (
            f"{persona}\n\n"
            "你是群里的一员，正在自然地和群友交流。"
            "只输出要说的话本身，不要解释、不要加引号。"
        )
        prompt = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]
        try:
            kwargs: dict[str, Any] = {"prompt": prompt, "temperature": cfg.temperature}
            model = cfg.model.strip()
            if model:
                kwargs["model"] = model
            if cfg.max_tokens > 0:
                kwargs["max_tokens"] = cfg.max_tokens
            result = await self.ctx.llm.generate(**kwargs)
            return self._extract_llm_text(result)
        except Exception:
            self.ctx.logger.debug("[考察期] LLM 生成失败，回退模板", exc_info=True)
            return ""

    @staticmethod
    def _extract_llm_text(result: Any) -> str:
        """从 llm.generate 结果中提取文本（兼容多种返回结构）。"""
        if result is None:
            return ""
        if isinstance(result, str):
            return result.strip()
        if isinstance(result, dict):
            content = result.get("content") or result.get("text") or ""
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text") or ""))
                content = "".join(parts)
            return str(content).strip()
        return str(result).strip()

    async def _resolve_member_name(self, group_id: str, user_id: str) -> str:
        """解析成员昵称（群名片 → 昵称）。"""
        try:
            result = await self.ctx.api.call(
                "adapter.napcat.group.get_group_member_info",
                group_id=int(group_id),
                user_id=int(user_id),
            )
            data = result.get("data") if isinstance(result, dict) else None
            if isinstance(data, dict):
                card = str(data.get("card") or "").strip()
                if card:
                    return card
                nick = str(data.get("nickname") or "").strip()
                if nick:
                    return nick
        except Exception as exc:
            self.ctx.logger.debug("[考察期] 昵称解析失败: %s", exc)
        return ""

    async def _send_at_message(self, group_id: str, user_id: str, text: str) -> bool:
        """向群发送一条 @ 指定成员 + 文本的消息（直接调适配器 API，不经 LLM）。"""
        try:
            await self.ctx.api.call(
                "adapter.napcat.group.send_group_msg",
                group_id=int(group_id),
                message=[
                    {"type": "at", "data": {"qq": user_id}},
                    {"type": "text", "data": {"text": text}},
                ],
            )
            return True
        except Exception as exc:
            self.ctx.logger.info("[考察期] 发送 @ 消息失败: %s", exc)
            return False

    def _probation_remove(self, group_id: str, user_id: str) -> None:
        """从考察名单移除一个成员（群为空时一并清理）。"""
        members = self._probation.get(group_id)
        if members and user_id in members:
            del members[user_id]
            if not members:
                del self._probation[group_id]

    def _probation_persist(self) -> None:
        """持久化考察名单（重启不丢，超时者不会被漏踢）。"""
        try:
            if not self._probation_file:
                return
            self._probation_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._probation_file, "w", encoding="utf-8") as f:
                json.dump(self._probation, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.ctx.logger.info("[考察期] 持久化失败: %s", exc)

    def _probation_load(self) -> None:
        """启动时加载持久化的考察名单。"""
        try:
            if self._probation_file and self._probation_file.exists():
                with open(self._probation_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._probation = data
        except Exception as exc:
            self.ctx.logger.info("[考察期] 加载失败: %s", exc)
