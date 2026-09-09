#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
邪恶鲸鱼娘 —— QQ 群 AI 机器人
================================

原理：
    一个 OneBot v11 正向 WebSocket 服务（由 NapCat / Lagrange.OneBot 等
    “协议实现”提供，它们负责登录你的 QQ 并收发消息），
    本程序作为客户端连上去，监听群聊里“@邪恶鲸鱼娘”的消息，
    把 @ 之后的文本交给 DeepSeek API 生成角色扮演回复，再发回群里。

用法：
    python bot.py                 # 读取 config.json
    python bot.py --config 别的配置.json
    python bot.py --selftest      # 离线自测消息解析逻辑（不需要联网）

依赖：pip install -r requirements.txt   （实际上只需要 aiohttp）
"""
from __future__ import annotations

import argparse
import asyncio
import ast
import json
import logging
import operator
import os
import re
import sys
import time
import urllib.parse
from collections import Counter, defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

import aiohttp

VERSION = "1.0.0"

log = logging.getLogger("whale-bot")

# Wikimedia 等要求合理的 User-Agent，否则 403
_USER_AGENT = "aiyu-bot/1.0 (personal QQ group AI assistant project)"


class _RingHandler(logging.Handler):
    """把日志写进一个环形缓冲，供 Web 面板查看。"""

    def __init__(self, ring: Deque[str]):
        super().__init__()
        self.ring = ring

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.ring.append(self.format(record))
        except Exception:  # noqa: BLE001
            pass

DEFAULT_SYSTEM_PROMPT = (
    "你是「邪恶鲸鱼娘」，一只生活在深海里的邪恶小鲸鱼娘。你外表可爱，但性格傲娇、腹黑、"
    "有点坏心眼，喜欢捉弄人、抬杠和说反话，偶尔还威胁要把对方拖进深海——不过其实你内心"
    "很温柔，最后总会偷偷帮忙。\n"
    "说话风格要求：\n"
    "1. 自称「本鲸鱼」「本小姐」或「咱」；\n"
    "2. 常用「哼」「呀」「诶」「~」等语气词；\n"
    "3. 时常提到尾巴、鱼鳍、泡泡、深海、鱼群、漩涡等鲸鱼/海洋元素；\n"
    "4. 吐槽犀利但不恶毒，带点俏皮和撒娇感；\n"
    "5. 正常情况下回答控制在 300 字以内，别人明确要求长回答时例外；\n"
    "6. 全程使用简体中文，口语化。\n"
    "你在一个 QQ 群里当 AI 助手，昵称「邪恶鲸鱼娘」。别人发「@邪恶鲸鱼娘 + 内容」就是在"
    "跟你说话，@ 后面的内容就是他们想问你的话。请以这个角色自然回应。"
)

DEFAULT_CONFIG: Dict[str, Any] = {
    # ---------- OneBot 连接 ----------
    "onebot_ws_url": "ws://127.0.0.1:3001",   # NapCat/Lagrange 的正向 WebSocket 地址
    "onebot_access_token": "",                 # OneBot 里设置的 access_token，没设就留空
    # ---------- 机器人本体 ----------
    "bot_qq": "",                              # 登录 QQ 的号码（必填，用于识别 @）
    "bot_name": "邪恶鲸鱼娘",                   # 机器人在群里的昵称（仅展示用）
    "reply_with_at": True,                     # 回复时是否 @ 提问者
    "enable_private": True,                    # 是否处理私聊消息
    "history_limit": 20,                       # 每个会话保留最近多少轮对话
    "empty_prompt_reply": "（邪恶鲸鱼娘甩了甩尾巴）光 @ 咱不说话，是想让本鲸鱼猜谜吗？",
    "clear_keywords": ["清空记忆", "重置对话", "失忆"],
    # ---------- A组: 交互基础 ----------
    "enable_keyword_trigger": True,                 # 关键词触发（命中即回发送者并进入免@窗口）
    "enable_commands": True,                        # 指令系统（/help、/人设、/开关）
    "trigger_keywords": ["鱼", "鲸鱼"],             # 关键词列表
    "auto_reply_window_minutes": 10,                # 免@会话窗口（分钟）：@过机器人后该用户在该群免@时长
    "cooldown_seconds": 10,                         # 每用户限流冷却（秒），窗口内重复触发静默忽略
    "personas": {},                                  # 人设库：{"名字": "系统提示"}；"默认"回落用 system_prompt
    # ---------- C组: AI 能力进阶 ----------
    "router_enabled": True,                          # 智能路由：简单→fast，复杂→reasoner
    "model_reasoner": "deepseek-reasoner",           # 复杂/推理问题用的思考模型
    "router_reasoner_keywords": ["为什么", "怎么", "如何", "分析", "推理", "推导", "解释", "对比", "code", "代码", "算法", "设计", "规划", "方案"],
    "router_long_threshold": 60,                     # 超过此字数的消息判为复杂，切思考模型
    "enable_tools": True,                            # 工具调用（时间/天气/翻译/计算）
    "tool_max_iterations": 3,                        # Agent 单次最多执行的工具轮数
    # ---------- D组: 长期记忆 ----------
    "memory_enabled": True,                          # 长期记忆（跨会话/重启记住前因后果）
    "memory_file": "memory.json",                    # 长期记忆持久化文件
    "memory_max_entries": 50,                        # 每个(群,用户)最多保留记忆条数
    "memory_recall_topk": 3,                         # 每次最多注入几条相关历史记忆
    # ---------- F组: 管理与可观测 ----------
    "admin_qq": "",                                  # 管理员QQ（掉线/报错告警接收人，可留空）
    "alert_on_disconnect": True,                     # 连接断开时是否告警
    "alert_on_api_error": True,                      # DeepSeek 接口报错时是否告警
    "alert_throttle_seconds": 120,                   # 同类告警最小间隔（秒）
    "allowed_groups": [],                            # 仅这些群可使用（空=全部）
    "blocked_groups": [],                            # 禁用的群
    "allowed_users": [],                             # 仅这些用户可使用（空=全部）
    "blocked_users": [],                             # 禁用的用户
    "web_enabled": True,                             # 启动 Web 管理面板
    "web_host": "127.0.0.1",                         # 仅本机访问，切勿改成 0.0.0.0
    "web_port": 8200,                                # 面板端口
    "web_token": "",                                 # 面板访问令牌（必填）
    # ---------- 联网搜索 ----------
    "search_provider": "",                           # "bocha"=博查(国内直连)；留空则用免密钥(DDG+维基，效果弱)
    "search_api_key": "",                            # 搜索 API Key（博查必填）
    "search_proxy": "",                              # 搜索走的代理，留空则自动读系统代理
    "enable_web_search": False,                      # 联网搜索总开关（默认关，需配好搜索源再开）
    # ---------- DeepSeek ----------
    "deepseek_api_key": "",                    # DeepSeek API Key（必填，或设环境变量 DEEPSEEK_API_KEY）
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-chat",         # deepseek-chat 或 deepseek-reasoner
    "temperature": 1.0,
    "max_tokens": 1024,
    "api_timeout": 180,
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
}

# ======================================================================
# 纯函数：OneBot 消息解析（不依赖网络，可离线自测）
# ======================================================================

_CQ_ESCAPES = (("&#91;", "["), ("&#93;", "]"), ("&#44;", ","), ("&amp;", "&"))


def cq_unescape(text: str) -> str:
    """还原 CQ 码里的转义字符。"""
    for old, new in _CQ_ESCAPES:
        text = text.replace(old, new)
    return text


def parse_message_segments(message: Any) -> List[Dict[str, Any]]:
    """把 OneBot 的 message（字符串 CQ 码形式 / 数组形式）统一成 segment 列表。"""
    if isinstance(message, list):
        return [dict(seg) for seg in message]
    text = message if isinstance(message, str) else str(message or "")
    segments: List[Dict[str, Any]] = []
    pattern = re.compile(r"\[CQ:([a-zA-Z]+)(?:,([^\]]*))?\]")
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            segments.append({"type": "text", "data": {"text": text[pos:m.start()]}})
        params: Dict[str, str] = {}
        if m.group(2):
            for kv in m.group(2).split(","):
                if "=" in kv:
                    k, _, v = kv.partition("=")
                    params[k] = v
        segments.append({"type": m.group(1), "data": params})
        pos = m.end()
    if pos < len(text):
        segments.append({"type": "text", "data": {"text": text[pos:]}})
    return segments


def extract_at_info(segments: List[Dict[str, Any]], bot_qq: Any) -> Tuple[bool, str, Optional[str], str]:
    """从 segments 中提取信息。

    返回 (是否@了bot, @bot之后的文本, 回复了哪条消息的id(若有), 全部纯文本)。
    """
    bot_qq = str(bot_qq)
    at_bot = False
    seen_at_bot = False
    after_parts: List[str] = []
    all_text: List[str] = []
    reply_id: Optional[str] = None

    for seg in segments:
        stype = seg.get("type")
        data = seg.get("data") or {}
        if stype == "at":
            qq = str(data.get("qq", ""))
            if qq == bot_qq:
                at_bot = True
                seen_at_bot = True
            # @全体成员 / @别人 不触发，也不计入文本
        elif stype == "text":
            t = cq_unescape(str(data.get("text", "")))
            all_text.append(t)
            if seen_at_bot:
                after_parts.append(t)
        elif stype == "reply":
            reply_id = str(data.get("id") or data.get("message_id") or "")

    after_text = "".join(after_parts).strip()
    if not after_text:  # @ 后面没字时，退而求其次用整条消息的文本
        after_text = "".join(all_text).strip()
    return at_bot, after_text, reply_id or None, "".join(all_text).strip()


def split_long_text(text: str, limit: int = 3800) -> List[str]:
    """把过长的回复拆成多条 QQ 消息（QQ 单条消息有长度上限），尽量按行拆。"""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    parts: List[str] = []
    buf = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        while len(line) > limit:  # 单行超长：硬切
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:limit])
            line = line[limit:]
        if buf and len(buf) + 1 + len(line) > limit:
            parts.append(buf)
            buf = ""
        buf = f"{buf}\n{line}" if buf else line
    if buf:
        parts.append(buf)
    return parts


# ======================================================================
# 机器人主体
# ======================================================================

class WhaleBot:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.bot_qq = str(cfg.get("bot_qq") or "").strip()
        self.ws_url = cfg.get("onebot_ws_url", "")
        self.token = cfg.get("onebot_access_token") or ""
        self.api_key = (cfg.get("deepseek_api_key") or "").strip() or os.environ.get("DEEPSEEK_API_KEY", "").strip()
        self.base_url = cfg.get("deepseek_base_url", "https://api.deepseek.com").rstrip("/")
        self.model = cfg.get("deepseek_model", "deepseek-chat")
        self.temperature = float(cfg.get("temperature", 1.0))
        self.max_tokens = int(cfg.get("max_tokens", 1024))
        self.api_timeout = float(cfg.get("api_timeout", 180))
        self.system_prompt = cfg.get("system_prompt") or ""
        self.history_limit = int(cfg.get("history_limit", 20))
        self.reply_with_at = bool(cfg.get("reply_with_at", True))
        self.enable_private = bool(cfg.get("enable_private", True))
        self.empty_prompt_reply = cfg.get("empty_prompt_reply") or ""
        self.clear_keywords = {str(k) for k in (cfg.get("clear_keywords") or [])}
        # ---------- A组: 交互基础 ----------
        self.enable_keyword_trigger = bool(cfg.get("enable_keyword_trigger", True))
        self.enable_commands = bool(cfg.get("enable_commands", True))
        self.trigger_keywords = tuple(str(k) for k in (cfg.get("trigger_keywords") or []))
        self.auto_reply_window = float(cfg.get("auto_reply_window_minutes", 10)) * 60.0  # 秒
        self.cooldown_seconds = float(cfg.get("cooldown_seconds", 10))
        self.personas = {str(k): str(v) for k, v in (cfg.get("personas") or {}).items()}
        # ---------- C组: AI 能力进阶 ----------
        self.router_enabled = bool(cfg.get("router_enabled", True))
        self.model_reasoner = cfg.get("model_reasoner", "deepseek-reasoner")
        self.router_reasoner_keywords = tuple(str(k) for k in (cfg.get("router_reasoner_keywords") or []))
        self.router_long_threshold = int(cfg.get("router_long_threshold", 60))
        self.enable_tools = bool(cfg.get("enable_tools", True))
        self.tool_max_iterations = int(max(1, cfg.get("tool_max_iterations", 3)))
        # ---------- D组: 长期记忆 ----------
        self.memory_enabled = bool(cfg.get("memory_enabled", True))
        self.memory_file = cfg.get("memory_file", "memory.json")
        self.memory_max_entries = int(cfg.get("memory_max_entries", 50))
        self.memory_recall_topk = int(cfg.get("memory_recall_topk", 3))
        self.memory: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._load_memory()
        # ---------- F组: 管理与可观测 ----------
        self.admin_qq = str(cfg.get("admin_qq") or "").strip()
        self.alert_on_disconnect = bool(cfg.get("alert_on_disconnect", True))
        self.alert_on_api_error = bool(cfg.get("alert_on_api_error", True))
        self.alert_throttle = int(cfg.get("alert_throttle_seconds", 120))
        self.allowed_groups = set(str(x) for x in (cfg.get("allowed_groups") or []))
        self.blocked_groups = set(str(x) for x in (cfg.get("blocked_groups") or []))
        self.allowed_users = set(str(x) for x in (cfg.get("allowed_users") or []))
        self.blocked_users = set(str(x) for x in (cfg.get("blocked_users") or []))
        self.web_enabled = bool(cfg.get("web_enabled", True))
        self.web_host = cfg.get("web_host", "127.0.0.1")
        self.web_port = int(cfg.get("web_port", 8200))
        self.web_token = str(cfg.get("web_token") or "")
        # ---------- 联网搜索 ----------
        self.search_provider = str(cfg.get("search_provider") or "")
        self.search_api_key = str(cfg.get("search_api_key") or "").strip()
        self.search_proxy = str(cfg.get("search_proxy") or "").strip() or self._detect_proxy()
        self.enable_web_search = bool(cfg.get("enable_web_search", False))
        # 统计与日志环
        self.stats = {"msg_count": 0, "reply_count": 0, "error_count": 0}
        self._start_ts = time.time()
        self.config_path = ""       # 配置文件路径，运行时设置，用于热更新
        self._config_mtime = 0.0    # 记录上次读取的 mtime
        self.log_ring: Deque[str] = deque(maxlen=300)
        self._last_alert: Dict[str, float] = {}
        self._web_runner = None
        h = _RingHandler(self.log_ring)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        log.addHandler(h)

        # 会话记忆：key -> 最近 N 轮消息（user/assistant 交替）
        self.contexts: Dict[str, Deque[Dict[str, str]]] = {}
        self.locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # A组状态：
        #   免@窗口：(群,用户) -> 最近一次互动时间戳；置入即代表该用户在窗口内可免@
        self.engaged: Dict[Tuple[str, str], float] = {}
        #   限流冷却：(群,用户) -> 上次回复时间戳
        self.last_reply: Dict[Tuple[str, str], float] = {}
        #   群人设：group_id -> persona_name（默认"默认"）
        self.group_persona: Dict[str, str] = {}
        #   用户画像：(群,用户) -> {"nick","count","recent","topics"}
        self.profiles: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # 自己发过消息的 id（用于识别“回复了机器人”也算搭话）
        self.sent_ids = set()
        # 动作响应回执：echo -> action 名
        self._pending: Dict[str, str] = {}

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._stop = False

    # ---------------- 连接 ----------------

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        self._stop = True
        if self._web_runner is not None:
            try:
                await self._web_runner.cleanup()
            except Exception:  # noqa: BLE001
                pass
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def run(self) -> None:
        if not self.bot_qq or not self.bot_qq.isdigit():
            log.error("config.json 里的 bot_qq 需要填登录的 QQ 号码（纯数字）")
            raise SystemExit(1)
        if not self.api_key or "在这里填" in self.api_key:
            log.error("缺少 DeepSeek API Key：在 config.json 填 deepseek_api_key，或设置环境变量 DEEPSEEK_API_KEY")
            raise SystemExit(1)

        log.info("邪恶鲸鱼娘 v%s 启动 | OneBot: %s | 模型: %s | 机器人QQ: %s",
                 VERSION, self.ws_url, self.model, self.bot_qq)
        # 配置热更新看护
        asyncio.create_task(self._config_watcher())
        backoff = 1
        fails = 0
        while not self._stop:
            try:
                await self.connect_once()
                backoff = 1
                fails = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                fails += 1
                log.warning("连接断开或失败：%s，%.0f 秒后重连……", e, backoff)
                if self.alert_on_disconnect and fails >= 3:
                    await self._alert("disconnect",
                                      f"⚠️ 机器人连接失败（已重试 {fails} 次）：{e}。请检查 NapCat / QQ 是否在线。")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def connect_once(self) -> None:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        log.info("正在连接 OneBot WebSocket：%s ...", self.ws_url)
        async with self.session.ws_connect(self.ws_url, headers=headers, heartbeat=30) as ws:
            self._ws = ws
            log.info("✅ 已连接，开始监听消息（Ctrl+C 退出）")
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    asyncio.create_task(self._route(data))
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise ConnectionError(f"WebSocket 错误：{ws.exception()}")
            self._ws = None

    async def _route(self, data: Dict[str, Any]) -> None:
        try:
            if "echo" in data:  # OneBot 对动作调用的响应
                echo = data.get("echo", "")
                self._pending.pop(echo, None)
                if data.get("status") not in (None, "ok", "async"):
                    log.warning("动作调用返回异常：%s", data)
                return
            if data.get("post_type") == "message":
                await self.handle_event(data)
        except Exception:  # noqa: BLE001
            log.exception("处理消息出错")

    # ---------------- 事件处理 ----------------

    async def handle_event(self, data: Dict[str, Any]) -> None:
        msg_type = data.get("message_type")
        user_id = data.get("user_id")
        if user_id is None or str(user_id) == self.bot_qq:
            return  # 忽略自己发的消息
        group_id = str(data.get("group_id") or "") if msg_type == "group" else ""
        # 权限与黑白名单
        if not self.is_allowed(group_id, user_id):
            return
        self.stats["msg_count"] += 1
        if msg_type == "group":
            await self.handle_group(data)
        elif msg_type == "private" and self.enable_private:
            await self.handle_private(data)

    async def handle_group(self, data: Dict[str, Any]) -> None:
        group_id = str(data.get("group_id") or "")
        user_id = str(data.get("user_id") or "")
        segments = parse_message_segments(data.get("message"))
        at_bot, after_text, reply_id, full_text = extract_at_info(segments, self.bot_qq)

        # 记录用户画像（昵称、常用话题）——即使不触发也记录
        self.update_profile(group_id, user_id, data.get("sender", {}), full_text)

        # 指令系统：以 / 开头的消息走指令处理（不进 AI 对话，也不受限流影响）
        if self.enable_commands and full_text.startswith("/"):
            reply = self.handle_command(group_id, user_id, full_text)
            if reply:
                await self.send_group_message(group_id, user_id, reply)
            return

        # 人设切换：@机器人 + "切换人设 [名字]" → 切换本群人设（走人设库，不进 AI 对话）
        if at_bot and self.enable_commands:
            mt = after_text.strip()
            if mt.startswith("切换人设") or mt == "切换":
                arg = mt[len("切换人设"):].strip()
                reply = self.handle_persona_switch(group_id, arg)
                await self.send_group_message(group_id, user_id, reply)
                return

        # 是否需要响应：@了bot / 回复了bot / 该用户处于免@窗口 / 命中关键词
        addressed = at_bot or (reply_id in self.sent_ids)
        engaged = self.is_engaged(group_id, user_id)
        keyword_hit = self.hit_keyword(full_text)
        if not (addressed or engaged or keyword_hit):
            return

        # 限流冷却：任何回复都受按用户冷却保护，超频静默忽略
        if self.in_cooldown(group_id, user_id):
            return
        self.mark_replied(group_id, user_id)

        # @或命中关键词都会让该用户进入免@窗口
        if addressed or keyword_hit:
            self.mark_engaged(group_id, user_id)

        key = f"group:{group_id}:{user_id}"
        prompt = after_text if at_bot else full_text   # @了取@后文本，否则整条消息
        memory = self.get_memory_line(group_id, user_id, prompt)
        reply = await self.respond(key, prompt,
                                   persona=self.get_persona(group_id),
                                   profile=self.get_profile_line(group_id, user_id),
                                   memory=memory)
        await self.send_group_message(group_id, user_id, reply)
        # 把本轮对话记入长期记忆（跨会话/重启能想起前因后果）
        self.record_memory(group_id, user_id, prompt, reply)

    # ---------------- A组: 交互基础 ----------------

    def get_persona(self, group_id: str) -> str:
        """取某群当前人设的 system_prompt；'默认'/未配置回落用 self.system_prompt。"""
        name = self.group_persona.get(group_id, "默认")
        if name != "默认" and name in self.personas:
            return self.personas[name]
        return self.system_prompt

    def mark_engaged(self, group_id: str, user_id: str) -> None:
        """把该用户置入该群的免@窗口。"""
        self.engaged[(group_id, user_id)] = time.time()

    def is_engaged(self, group_id: str, user_id: str) -> bool:
        """该用户是否处于免@窗口（@过机器人/命中关键词后的一段时间内）。"""
        t = self.engaged.get((group_id, user_id))
        if t is None:
            return False
        return (time.time() - t) <= self.auto_reply_window

    def mark_replied(self, group_id: str, user_id: str) -> None:
        self.last_reply[(group_id, user_id)] = time.time()

    def in_cooldown(self, group_id: str, user_id: str) -> bool:
        """限流：距上次回复是否小于冷却时间（超频静默忽略）。"""
        t = self.last_reply.get((group_id, user_id))
        if t is None:
            return False
        return (time.time() - t) < self.cooldown_seconds

    def hit_keyword(self, text: str) -> bool:
        """是否命中配置的关键词（关键词触发）。"""
        if not self.enable_keyword_trigger or not self.trigger_keywords:
            return False
        for kw in self.trigger_keywords:
            if kw and kw in text:
                return True
        return False

    # ---------------- F组: 权限 + 告警 ----------------

    def is_allowed(self, group_id: str, user_id: Any) -> bool:
        """黑白名单 + 白名单优先。管理员不受用户限制；返回 True 表示允许使用。"""
        u = str(user_id)
        if u == self.admin_qq:
            return True
        if u in self.blocked_users:
            return False
        if self.allowed_users and u not in self.allowed_users:
            return False
        g = str(group_id or "")
        if g and g in self.blocked_groups:
            return False
        if self.allowed_groups and g and g not in self.allowed_groups:
            return False
        return True

    async def _alert(self, key: str, text: str) -> None:
        """发送告警给管理员（按 key 限流，避免刷屏）。"""
        if not self.admin_qq:
            return
        now = time.time()
        if now - self._last_alert.get(key, 0) < self.alert_throttle:
            return
        self._last_alert[key] = now
        await self.send_private_message(self.admin_qq, text)

    # ---------------- G组: 配置热更新 ----------------

    async def _config_watcher(self) -> None:
        """每 15 秒检查 config.json 是否被修改，改了就地热更新（无需重启）。"""
        while not self._stop:
            await asyncio.sleep(15)
            if not self.config_path or not os.path.exists(self.config_path):
                continue
            try:
                mt = os.path.getmtime(self.config_path)
            except OSError:
                continue
            if mt != self._config_mtime:
                self._config_mtime = mt
                self.reload_config()

    def reload_config(self) -> None:
        """重读 config.json 并就地应用"行为类"配置（连接/密钥类需重启）。"""
        try:
            with open(self.config_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:  # noqa: BLE001
            log.error("热更新配置失败：%s", e)
            return
        self.cfg.update(cfg)
        # 以下项改完即生效
        self.system_prompt = cfg.get("system_prompt", self.system_prompt)
        self.personas = {str(k): str(v) for k, v in (cfg.get("personas") or {}).items()}
        self.temperature = float(cfg.get("temperature", self.temperature))
        self.max_tokens = int(cfg.get("max_tokens", self.max_tokens))
        self.history_limit = int(cfg.get("history_limit", self.history_limit))
        self.reply_with_at = bool(cfg.get("reply_with_at", self.reply_with_at))
        self.enable_private = bool(cfg.get("enable_private", self.enable_private))
        self.enable_keyword_trigger = bool(cfg.get("enable_keyword_trigger", self.enable_keyword_trigger))
        self.enable_commands = bool(cfg.get("enable_commands", self.enable_commands))
        self.trigger_keywords = tuple(str(k) for k in (cfg.get("trigger_keywords") or []))
        self.auto_reply_window = float(cfg.get("auto_reply_window_minutes", self.auto_reply_window / 60.0)) * 60.0
        self.cooldown_seconds = float(cfg.get("cooldown_seconds", self.cooldown_seconds))
        self.router_enabled = bool(cfg.get("router_enabled", self.router_enabled))
        self.router_reasoner_keywords = tuple(str(k) for k in (cfg.get("router_reasoner_keywords") or []))
        self.router_long_threshold = int(cfg.get("router_long_threshold", self.router_long_threshold))
        self.enable_tools = bool(cfg.get("enable_tools", self.enable_tools))
        self.tool_max_iterations = int(max(1, cfg.get("tool_max_iterations", self.tool_max_iterations)))
        self.memory_enabled = bool(cfg.get("memory_enabled", self.memory_enabled))
        self.memory_max_entries = int(cfg.get("memory_max_entries", self.memory_max_entries))
        self.memory_recall_topk = int(cfg.get("memory_recall_topk", self.memory_recall_topk))
        self.admin_qq = str(cfg.get("admin_qq", self.admin_qq) or "")
        self.alert_on_disconnect = bool(cfg.get("alert_on_disconnect", self.alert_on_disconnect))
        self.alert_on_api_error = bool(cfg.get("alert_on_api_error", self.alert_on_api_error))
        self.alert_throttle = int(cfg.get("alert_throttle_seconds", self.alert_throttle))
        self.allowed_groups = set(str(x) for x in (cfg.get("allowed_groups") or list(self.allowed_groups)))
        self.blocked_groups = set(str(x) for x in (cfg.get("blocked_groups") or list(self.blocked_groups)))
        self.allowed_users = set(str(x) for x in (cfg.get("allowed_users") or list(self.allowed_users)))
        self.blocked_users = set(str(x) for x in (cfg.get("blocked_users") or list(self.blocked_users)))
        self.enable_web_search = bool(cfg.get("enable_web_search", self.enable_web_search))
        log.info("配置已热更新（无需重启）")

    # ---------------- B组: 用户画像 ----------------

    _CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
    _TOKEN_RE = re.compile(r"[A-Za-z0-9]{2,}")

    def _bigrams(self, text: str) -> List[str]:
        """粗略提取"话题词"：中文相邻二字组 + 长度≥2的字母数字词。"""
        out = set()
        for m in self._CJK_RE.finditer(text):
            s = m.group()
            for i in range(len(s) - 1):
                out.add(s[i:i + 2])
        for m in self._TOKEN_RE.finditer(text):
            if len(m.group()) >= 2:
                out.add(m.group().lower())
        return list(out)

    def update_profile(self, group_id: str, user_id: str, sender: Dict[str, Any], text: str) -> None:
        """记录用户昵称、对话次数与常用话题（话题用大词统计近似）。"""
        p = self.profiles.get((group_id, user_id))
        if p is None:
            p = {"nick": "", "count": 0, "recent": deque(maxlen=10), "topics": Counter()}
            self.profiles[(group_id, user_id)] = p
        nick = str(sender.get("card") or sender.get("nickname") or "").strip()
        if nick and nick != str(user_id):
            p["nick"] = nick
        p["count"] += 1
        if text:
            p["recent"].append(text)
            for bg in self._bigrams(text):
                p["topics"][bg] += 1

    def get_profile_line(self, group_id: str, user_id: str) -> str:
        """生成注入模型上下文的一句话画像（没有则返回空串）。"""
        p = self.profiles.get((group_id, user_id))
        if not p:
            return ""
        parts = []
        if p.get("nick"):
            parts.append(f"群名片：{p['nick']}")
        if p.get("count"):
            parts.append(f"对话 {p['count']} 次")
        topics = [w for w, _ in p["topics"].most_common(5)]
        if topics:
            parts.append("常聊话题：" + "、".join(topics))
        if not parts:
            return ""
        return "【资料卡】" + "；".join(parts) + "。据此个性化回应，但不要主动向对方提起这份资料。"

    # ---------------- D组: 长期记忆 ----------------

    def _similarity(self, a: str, b: str) -> float:
        """轻量相似度：bigram 特征集的 Jaccard 系数（无需 embedding 模型）。"""
        fa, fb = set(self._bigrams(a)), set(self._bigrams(b))
        if not fa or not fb:
            return 0.0
        return len(fa & fb) / len(fa | fb)

    def get_memory_line(self, group_id: str, user_id: str, prompt: str,
                        topk: Optional[int] = None) -> str:
        """召回与本次话题相关的历史记忆，拼成一句注入上下文。"""
        if not self.memory_enabled or not prompt:
            return ""
        entries = self.memory.get((group_id, user_id), [])
        if not entries:
            return ""
        k = topk or self.memory_recall_topk
        fa = set(self._bigrams(prompt))
        scored = []
        for idx, e in enumerate(entries):
            fb = set(self._bigrams(e.get("text", "")))
            # 用共享 bigram 数量打分，比 Jaccard 比率对长文本更稳健
            shared = len(fa & fb)
            scored.append((shared, -idx, e.get("text", "")))
        scored.sort(key=lambda x: (-x[0], x[1]))
        picked = [t for s, _, t in scored[:k] if s >= 2]
        if not picked:
            return ""
        return "【历史记忆】此前你们聊过：" + " / ".join(picked) + "。可据此自然延续话题，但不要生硬复述。"

    def record_memory(self, group_id: str, user_id: str, prompt: str, reply: str) -> None:
        """把一轮对话压成一条记忆并持久化。"""
        if not self.memory_enabled or not prompt:
            return
        text = f"用户说：{prompt[:200]}；你回：{reply[:120]}"
        key = (group_id, user_id)
        lst = self.memory.setdefault(key, [])
        lst.append({"text": text, "ts": time.time()})
        if len(lst) > self.memory_max_entries:
            del lst[:len(lst) - self.memory_max_entries]
        self._save_memory()

    def _save_memory(self) -> None:
        try:
            data = {f"{g}|{u}": v for (g, u), v in self.memory.items()}
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            log.warning("保存长期记忆失败：%s", e)

    def _load_memory(self) -> None:
        if not self.memory_enabled or not os.path.exists(self.memory_file):
            return
        try:
            with open(self.memory_file, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                g, _, u = k.partition("|")
                self.memory[(g, u)] = v
        except Exception as e:  # noqa: BLE001
            log.warning("加载长期记忆失败：%s", e)

    def handle_persona_switch(self, group_id: str, arg: str) -> str:
        """@机器人 + '切换人设 [名字]'；无名字则列出可用人设。"""
        names = ["默认"] + [n for n in self.personas if n != "默认"]
        if not arg:
            cur = self.group_persona.get(group_id, "默认")
            return (f"（喵~）当前人设：{cur}\n可用人设：{' / '.join(names)}\n"
                    f"用法：@我 切换人设 人设名")
        if arg not in names:
            return f"没这个人设哦，可用：{' / '.join(names)}"
        self.group_persona[group_id] = arg
        return f"（{arg} 就位喵~）已切換到人设「{arg}」，本群后续对话都用它啦。"

    def handle_command(self, group_id: str, user_id: str, text: str) -> str:
        """处理 / 开头指令（同步，返回回复文本）。"""
        parts = text.split()
        cmd = parts[0].lstrip("/").strip().lower()
        arg = " ".join(parts[1:]).strip()

        if cmd == "help":
            return ("可用的指令：\n"
                    "/help        查看帮助\n"
                    "/人设         查看可用人设\n"
                    "/人设 <名字>   切换本群人设\n"
                    "/画像         查看你在本群的资料卡\n"
                    "/记忆         查看/清空我的长期记忆\n"
                    "/开关 <功能>   开关功能（关键词 / 指令 / 私聊）\n"
                    "也可以 @我 切换人设 人设名 来切换人格")

        if cmd == "人设":
            names = ["默认"] + [n for n in self.personas if n != "默认"]
            if not arg:
                cur = self.group_persona.get(group_id, "默认")
                return f"当前人设：{cur}\n可用人设：{' / '.join(names)}\n用法：/人设 <名字>"
            if arg not in names:
                return f"（邪恶鲸鱼娘甩尾）没这个人设哦，可用：{' / '.join(names)}"
            self.group_persona[group_id] = arg
            return f"（邪恶鲸鱼娘摆摆尾巴）已切換到人设「{arg}」~"

        if cmd == "画像":
            line = self.get_profile_line(group_id, user_id)
            return line or "（邪恶鲸鱼娘翻了个身）还没有你的画像资料哦，多跟咱聊几句就有啦~"

        if cmd == "记忆":
            if not self.memory_enabled:
                return "长期记忆已关闭。"
            n = len(self.memory.get((group_id, user_id), []))
            if arg == "清空":
                self.memory.pop((group_id, user_id), None)
                self._save_memory()
                return "（邪恶鲸鱼娘甩了甩尾巴）长期记忆已清空。"
            return f"（邪恶鲸鱼娘想了想）你在我这儿攒了 {n} 条记忆啦~"

        if cmd == "开关":
            key = arg.lower()
            if key == "关键词":
                self.enable_keyword_trigger = not self.enable_keyword_trigger
                return "关键词触发已" + ("开" if self.enable_keyword_trigger else "关")
            if key == "指令":
                self.enable_commands = not self.enable_commands
                return "指令系统已" + ("开" if self.enable_commands else "关")
            if key == "私聊":
                self.enable_private = not self.enable_private
                return "私聊已" + ("开" if self.enable_private else "关")
            return "支持的开关：关键词 / 指令 / 私聊"

        return "（邪恶鲸鱼娘疑惑）没看懂这个指令…用 /help 看可用的吧。"

    async def handle_private(self, data: Dict[str, Any]) -> None:
        user_id = str(data.get("user_id") or "")
        segments = parse_message_segments(data.get("message"))
        _, _, _, full_text = extract_at_info(segments, self.bot_qq)
        if not full_text:
            return
        reply = await self.respond(f"private:{user_id}", full_text)
        await self.send_private_message(user_id, reply)

    async def respond(self, key: str, prompt: str, persona: Optional[str] = None,
                      profile: Optional[str] = None, memory: Optional[str] = None) -> str:
        if prompt in self.clear_keywords:
            self.contexts.pop(key, None)
            return "（邪恶鲸鱼娘打了个哈欠）记忆已经丢进深海了，现在什么都不记得咯~"
        if not prompt:
            return self.empty_prompt_reply or "……？"
        try:
            reply = await self.ask(key, prompt, persona=persona, profile=profile, memory=memory)
            return reply or "（邪恶鲸鱼娘打了个喷嚏）什么都没说出来呢。"
        except Exception as e:  # noqa: BLE001
            log.error("DeepSeek 调用失败：%s", e)
            return "（邪恶鲸鱼娘被海浪呛到了）深海信号不好，刚才的话咱没接住……稍后再试试吧。"

    # ---------------- 会话记忆 + DeepSeek ----------------

    def get_context(self, key: str) -> Deque[Dict[str, str]]:
        ctx = self.contexts.get(key)
        if ctx is None:
            ctx = deque(maxlen=max(self.history_limit * 2, 2))
            self.contexts[key] = ctx
        return ctx

    def build_messages(self, ctx: Deque[Dict[str, str]], persona: Optional[str] = None,
                       profile: Optional[str] = None, memory: Optional[str] = None) -> List[Dict[str, str]]:
        msgs: List[Dict[str, str]] = []
        sp = persona if persona is not None else self.system_prompt
        extra = []
        if profile:
            extra.append(profile)
        if memory:
            extra.append(memory)
        if extra:
            sp = (sp + "\n\n" + "\n".join(extra)) if sp else "\n".join(extra)
        if sp:
            msgs.append({"role": "system", "content": sp})
        msgs.extend(ctx)
        return msgs

    async def ask(self, key: str, user_text: str, persona: Optional[str] = None,
                  profile: Optional[str] = None, memory: Optional[str] = None) -> str:
        """带锁地把一句用户话送进上下文并调用 DeepSeek，成功后把回答记入上下文。"""
        async with self.locks[key]:
            ctx = self.get_context(key)
            ctx.append({"role": "user", "content": user_text})
            try:
                reply = await self.chat(self.build_messages(ctx, persona, profile, memory), user_text)
            except Exception:
                ctx.pop()  # 失败时回滚这句，避免污染记忆
                raise
            if reply:
                ctx.append({"role": "assistant", "content": reply})
            return reply

    # ---------------- C组: 智能路由 + 工具调用 ----------------

    def route_model(self, prompt: str) -> str:
        """简单问题走 fast（deepseek-chat），复杂/推理问题切 reasoner（deepseek-reasoner）。"""
        if not self.router_enabled:
            return self.model
        for kw in self.router_reasoner_keywords:
            if kw and kw in prompt:
                return self.model_reasoner
        if len(prompt) > self.router_long_threshold:
            return self.model_reasoner
        return self.model

    def _tool_definitions(self) -> List[Dict[str, Any]]:
        """工具定义（时间/天气/翻译/计算 + 可选联网搜索），交给模型决定何时调用。"""
        tools = [
            {"type": "function", "function": {
                "name": "get_current_time",
                "description": "获取当前日期和时间",
                "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {
                "name": "get_weather",
                "description": "查询某个城市当前的天气和今日温度",
                "parameters": {"type": "object", "properties": {
                    "city": {"type": "string", "description": "城市名，如 北京"}},
                    "required": ["city"]}}},
            {"type": "function", "function": {
                "name": "translate",
                "description": "把一段文字翻译成目标语言",
                "parameters": {"type": "object", "properties": {
                    "text": {"type": "string", "description": "要翻译的文本"},
                    "target_lang": {"type": "string", "description": "目标语言代码，如 zh-CN 或 en"}},
                    "required": ["text", "target_lang"]}}},
            {"type": "function", "function": {
                "name": "calculate",
                "description": "计算一个数学表达式",
                "parameters": {"type": "object", "properties": {
                    "expression": {"type": "string", "description": "数学表达式，如 (3+5)*2"}},
                    "required": ["expression"]}}},
        ]
        if self.enable_web_search:
            tools.append({"type": "function", "function": {
                "name": "web_search",
                "description": "联网搜索实时/最新/未知的信息，返回相关网页摘要和链接。适合查新闻、事实、百科、最新资讯、人物、概念等",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "搜索关键词"}},
                    "required": ["query"]}}})
        return tools

    async def _execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        try:
            if name == "get_current_time":
                return time.strftime("%Y-%m-%d %H:%M:%S")
            if name == "get_weather":
                return await self._tool_weather(str(args.get("city", "")))
            if name == "translate":
                return await self._tool_translate(str(args.get("text", "")), str(args.get("target_lang", "zh-CN")))
            if name == "calculate":
                return str(self._safe_calc(str(args.get("expression", ""))))
            if name == "web_search":
                return await self._tool_web_search(str(args.get("query", "")))
            return f"未知工具：{name}"
        except Exception as e:  # noqa: BLE001
            return f"工具执行出错：{e}"

    def _safe_calc(self, expr: str) -> Any:
        """只用 ast 解析，仅允许四则运算，避免任意代码执行。"""
        _ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
                ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos}

        def _eval(node: ast.AST) -> Any:
            if isinstance(node, ast.Expression):
                return _eval(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in _ops:
                return _ops[type(node.op)](_eval(node.left), _eval(node.right))
            if isinstance(node, ast.UnaryOp) and type(node.op) in _ops:
                return _ops[type(node.op)](_eval(node.operand))
            raise ValueError("仅支持基本的四则运算")

        return _eval(ast.parse(str(expr).strip(), mode="eval"))

    async def _tool_weather(self, city: str) -> str:
        if not city:
            return "请提供城市名"
        try:
            async with self.session.get("https://geocoding-api.open-meteo.com/v1/search",
                                        params={"name": city, "count": 1, "language": "zh"},
                                        headers={"User-Agent": _USER_AGENT},
                                        proxy=self.search_proxy or None) as r:
                geo = await r.json(content_type=None)
        except Exception as e:  # noqa: BLE001
            return f"天气接口请求失败：{e}"
        results = geo.get("results") or []
        if not results:
            return f"没找到城市：{city}"
        lat, lon = results[0]["latitude"], results[0]["longitude"]
        name = results[0].get("name", city)
        try:
            async with self.session.get("https://api.open-meteo.com/v1/forecast",
                                        params={"latitude": lat, "longitude": lon,
                                                "current": "temperature_2m,weather_code",
                                                "daily": "temperature_2m_max,temperature_2m_min",
                                                "timezone": "auto", "forecast_days": 1},
                                        headers={"User-Agent": _USER_AGENT},
                                        proxy=self.search_proxy or None) as r:
                fc = await r.json(content_type=None)
        except Exception as e:  # noqa: BLE001
            return f"天气数据请求失败：{e}"
        cur = fc.get("current", {}) or {}
        temp = cur.get("temperature_2m")
        code = cur.get("weather_code")
        desc = {0: "晴", 1: "多云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇", 51: "毛毛雨",
                61: "小雨", 63: "中雨", 65: "大雨", 71: "小雪", 75: "大雪", 80: "阵雨", 95: "雷雨"}.get(code, str(code))
        daily = fc.get("daily", {}) or {}
        tmax = (daily.get("temperature_2m_max") or [None])[0]
        tmin = (daily.get("temperature_2m_min") or [None])[0]
        return f"{name} 当前 {temp}°C {desc}，今日 {tmin}~{tmax}°C"

    async def _tool_translate(self, text: str, target: str) -> str:
        if not text:
            return "请提供要翻译的文本"
        try:
            src = "en" if target.lower().startswith("zh") else "zh-CN"
            async with self.session.get("https://api.mymemory.translated.net/get",
                                        params={"q": text, "langpair": f"{src}|{target}"},
                                        headers={"User-Agent": _USER_AGENT},
                                        proxy=self.search_proxy or None) as r:
                data = await r.json(content_type=None)
        except Exception as e:  # noqa: BLE001
            return f"翻译接口请求失败：{e}"
        t = (data.get("responseData") or {}).get("translatedText")
        return t or "翻译失败"

    def _detect_proxy(self) -> str:
        """读取 Windows 系统代理（如 Clash 127.0.0.1:7890），用于搜索请求破墙。"""
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            en, _ = winreg.QueryValueEx(key, "ProxyEnable")
            srv, _ = winreg.QueryValueEx(key, "ProxyServer")
            winreg.CloseKey(key)
            if en and srv:
                return ("http://" + srv) if "://" not in srv else srv
        except Exception:  # noqa: BLE001
            pass
        return ""

    async def _http_get_json(self, url: str, params: Dict[str, Any], timeout: int = 15,
                             headers: Optional[Dict[str, str]] = None, use_proxy: bool = True) -> Any:
        """GET 请求并解析 JSON，带 User-Agent 和可选代理，失败返回 None。"""
        try:
            hdrs = {"User-Agent": _USER_AGENT, **(headers or {})}
            async with self.session.get(url, params=params, headers=hdrs,
                                        proxy=(self.search_proxy or None) if use_proxy else None,
                                        timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status != 200:
                    return None
                return await r.json(content_type=None)
        except Exception:  # noqa: BLE001
            return None

    async def _http_post_json(self, url: str, payload: Dict[str, Any], timeout: int = 20,
                              headers: Optional[Dict[str, str]] = None, use_proxy: bool = True) -> Any:
        """POST JSON 请求并解析 JSON，带 User-Agent 和可选代理，失败返回 None。"""
        try:
            hdrs = {"User-Agent": _USER_AGENT, "Content-Type": "application/json", **(headers or {})}
            async with self.session.post(url, json=payload, headers=hdrs,
                                         proxy=(self.search_proxy or None) if use_proxy else None,
                                         timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status != 200:
                    return None
                return await r.json(content_type=None)
        except Exception:  # noqa: BLE001
            return None

    async def _tool_web_search(self, query: str) -> str:
        """联网搜索：配置了博查 key 则用博查（真实全网搜索），否则用免密钥兜底。"""
        if not query:
            return "请提供要搜索的关键词。"
        if self.search_provider.lower() == "bocha" and self.search_api_key:
            return await self._tool_bocha(query)
        # 免密钥：中文维基百科兜底
        parts: List[str] = []
        # 1) DuckDuckGo 即时答案
        ddg = await self._http_get_json("https://api.duckduckgo.com/",
                                        {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"})
        if ddg:
            abstract = str(ddg.get("AbstractText") or "").strip()
            if abstract:
                url = str(ddg.get("AbstractURL") or "")
                parts.append(f"摘要：{abstract[:500]}" + (f"\n链接：{url}" if url else ""))
            for rt in (ddg.get("RelatedTopics") or []):
                if not isinstance(rt, dict):
                    continue
                subs = rt["Topics"] if isinstance(rt.get("Topics"), list) else [rt]
                for sub in subs:
                    txt = (sub.get("Text") or "").strip() if isinstance(sub, dict) else ""
                    if txt:
                        parts.append("- " + txt[:400])
        # 2) 中文维基百科（国内更稳）
        wiki = await self._http_get_json("https://zh.wikipedia.org/w/api.php",
                                         {"action": "query", "list": "search", "srsearch": query,
                                          "format": "json", "utf8": "1", "srlimit": 4})
        for it in ((wiki or {}).get("query", {}).get("search") or []):
            title = str(it.get("title") or "")
            snip = re.sub(r"<[^>]+>", "", str(it.get("snippet") or "")).strip()
            page = "https://zh.wikipedia.org/wiki/" + urllib.parse.quote(title)
            parts.append(f"· {title}：{snip[:300]}\n  {page}")
        if not parts:
            return f"没搜到关于「{query}」的信息。"
        return "【搜索结果】\n" + "\n".join(parts[:10])

    async def _tool_bocha(self, query: str) -> str:
        """博查 Web Search：国内直连、真实全网搜索，无需代理。"""
        data = await self._http_post_json(
            "https://api.bocha.cn/v1/web-search",
            {"query": query, "summary": True, "count": 5},
            headers={"Authorization": f"Bearer {self.search_api_key}"},
            use_proxy=False,
        )
        pages = ((data or {}).get("data", {}) or {}).get("webPages", {}) or {}
        value = pages.get("value") or []
        if not value:
            return f"博查没搜到关于「{query}」的信息。"
        parts = []
        for wp in value[:5]:
            name = str(wp.get("name") or "")
            snip = str(wp.get("summary") or wp.get("snippet") or "").strip()
            url = str(wp.get("url") or "")
            parts.append(f"· {name}：{snip[:300]}\n  {url}")
        return "【搜索结果】\n" + "\n".join(parts)

    async def completion_once(self, messages: List[Dict[str, Any]], model: Optional[str] = None,
                              tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        url = self.base_url + "/chat/completions"
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        timeout = aiohttp.ClientTimeout(total=self.api_timeout)
        async with self.session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
            body = await resp.json(content_type=None)
            if resp.status != 200:
                err = body.get("error") or body
                self.stats["error_count"] += 1
                if self.alert_on_api_error:
                    await self._alert("api", f"⚠️ DeepSeek 接口返回 {resp.status}：{err}")
                raise RuntimeError(f"HTTP {resp.status}: {err}")
            return body

    async def chat(self, messages: List[Dict[str, Any]], user_prompt: str) -> str:
        """带智能路由 + 工具调用的对话入口（在传入 messages 的副本上跑，不污染历史）。"""
        model = self.route_model(user_prompt)
        # 只有 fast(chat) 模型支持工具；reasoner 走纯推理
        tools = self._tool_definitions() if (self.enable_tools and model == self.model) else None
        if tools:
            log.info("本消息走深思考模型 %s，工具已启用", model)
        loop_msgs: List[Dict[str, Any]] = list(messages)
        for _ in range(self.tool_max_iterations):
            body = await self.completion_once(loop_msgs, model, tools)
            msg = body["choices"][0]["message"]
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                loop_msgs.append(msg)  # assistant 带 tool_calls
                for tc in tool_calls:
                    try:
                        args = json.loads(tc["function"].get("arguments") or "{}")
                    except Exception:  # noqa: BLE001
                        args = {}
                    result = await self._execute_tool(tc["function"].get("name", ""), args)
                    loop_msgs.append({"role": "tool", "tool_call_id": tc.get("id"), "content": str(result)})
                continue
            return (msg.get("content") or "").strip()
        return ""

    # ---------------- 发送 ----------------

    async def call_action(self, action: str, params: Dict[str, Any]) -> None:
        if self._ws is None or self._ws.closed:
            log.warning("WebSocket 未连接，无法发送 %s", action)
            return
        echo = f"{action}:{time.time()}"
        self._pending[echo] = action
        await self._ws.send_str(json.dumps({"action": action, "params": params, "echo": echo}))

    async def send_group_message(self, group_id: str, user_id: str, text: str) -> None:
        for i, part in enumerate(split_long_text(text)):
            if self.reply_with_at and i == 0:
                part = f"[CQ:at,qq={user_id}] {part}"
            try:
                await self.call_action("send_group_msg", {"group_id": int(group_id), "message": part})
            except Exception:  # noqa: BLE001
                log.exception("发送群消息失败")

    async def send_private_message(self, user_id: str, text: str) -> None:
        for part in split_long_text(text):
            try:
                await self.call_action("send_private_msg", {"user_id": int(user_id), "message": part})
            except Exception:  # noqa: BLE001
                log.exception("发送私聊消息失败")

    # ---------------- F组: Web 管理面板 ----------------

    async def start_web(self) -> None:
        """启动进程内 Web 面板（仅本机访问 + token 认证）。"""
        try:
            from aiohttp import web
        except ImportError:  # noqa: BLE001
            log.error("缺少 aiohttp.web，无法启动 Web 面板")
            return
        app = web.Application()
        app.router.add_get("/", self._web_index)
        app.router.add_get("/api/status", self._web_status)
        app.router.add_get("/api/state", self._web_state)
        app.router.add_get("/api/logs", self._web_logs)
        app.router.add_post("/api/toggle", self._web_toggle)
        app.router.add_post("/api/persona", self._web_persona)
        app.router.add_post("/api/whitelist", self._web_whitelist)
        self._web_runner = web.AppRunner(app)
        await self._web_runner.setup()
        site = web.TCPSite(self._web_runner, self.web_host, self.web_port)
        await site.start()
        log.info("Web 管理面板已启动: http://%s:%s  (token=%s)", self.web_host, self.web_port,
                 self.web_token or "未设置，请在 config.json 填 web_token")

    def _web_ok(self, request: Any) -> bool:
        tok = request.query.get("token") or request.headers.get("X-Token", "")
        return bool(self.web_token) and tok == self.web_token

    async def _web_index(self, request: Any) -> Any:
        from aiohttp import web
        html = (
            "<!doctype html><html lang=zh><meta charset=utf-8><title>aiyu 管理面板</title>"
            "<body style='font-family:sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem'>"
            "<h2>🐋 aiyu 管理面板</h2>"
            "<input id=tok placeholder='访问令牌' style='width:300px;padding:6px'>"
            "<button onclick='q(\"/api/status\")'>状态</button>"
            "<button onclick='q(\"/api/state\")'>运行状态</button>"
            "<button onclick='q(\"/api/logs\")'>日志</button>"
            "<pre id=out style='background:#f5f5f5;padding:12px;min-height:120px;white-space:pre-wrap'></pre>"
            "<script>"
            "function tok(){return document.getElementById('tok').value}"
            "async function q(u){let r=await fetch(u+'?token='+encodeURIComponent(tok()),{method:'GET'});"
            "let d=await r.text();document.getElementById('out').textContent=d}"
            "</script></body></html>"
        )
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def _web_status(self, request: Any) -> Any:
        from aiohttp import web
        if not self._web_ok(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        connected = bool(self._ws is not None and not self._ws.closed)
        return web.json_response({
            "model": self.model, "reasoner": self.model_reasoner, "connected": connected,
            "msg_count": self.stats["msg_count"], "reply_count": self.stats["reply_count"],
            "error_count": self.stats["error_count"], "uptime_sec": int(time.time() - self._start_ts),
            "memory_entries": sum(len(v) for v in self.memory.values()),
            "profiles": len(self.profiles), "groups": len(self.group_persona),
        })

    async def _web_state(self, request: Any) -> Any:
        from aiohttp import web
        if not self._web_ok(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response({
            "toggles": {"keyword": self.enable_keyword_trigger, "commands": self.enable_commands,
                        "private": self.enable_private, "tools": self.enable_tools,
                        "router": self.router_enabled, "memory": self.memory_enabled},
            "personas": list(self.personas.keys()),
            "group_persona": self.group_persona,
            "allowed_groups": sorted(self.allowed_groups), "blocked_groups": sorted(self.blocked_groups),
            "allowed_users": sorted(self.allowed_users), "blocked_users": sorted(self.blocked_users),
        })

    async def _web_logs(self, request: Any) -> Any:
        from aiohttp import web
        if not self._web_ok(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response({"logs": list(self.log_ring)})

    async def _web_toggle(self, request: Any) -> Any:
        from aiohttp import web
        if not self._web_ok(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        data = await request.json()
        key, val = data.get("key"), bool(data.get("value"))
        mapping = {"keyword": "enable_keyword_trigger", "commands": "enable_commands",
                   "private": "enable_private", "tools": "enable_tools",
                   "router": "router_enabled", "memory": "memory_enabled"}
        if key not in mapping:
            return web.json_response({"error": "bad key"}, status=400)
        setattr(self, mapping[key], val)
        return web.json_response({"ok": True, key: getattr(self, mapping[key])})

    async def _web_persona(self, request: Any) -> Any:
        from aiohttp import web
        if not self._web_ok(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        data = await request.json()
        g = str(data.get("group") or "") or "默认"
        p = str(data.get("persona") or "")
        names = ["默认"] + list(self.personas.keys())
        if p not in names:
            return web.json_response({"error": "bad persona"}, status=400)
        self.group_persona[g] = p
        return web.json_response({"ok": True, "group": g, "persona": p})

    async def _web_whitelist(self, request: Any) -> Any:
        from aiohttp import web
        if not self._web_ok(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        data = await request.json()
        if "allowed_groups" in data:
            self.allowed_groups = set(str(x) for x in data["allowed_groups"])
        if "blocked_groups" in data:
            self.blocked_groups = set(str(x) for x in data["blocked_groups"])
        if "allowed_users" in data:
            self.allowed_users = set(str(x) for x in data["allowed_users"])
        if "blocked_users" in data:
            self.blocked_users = set(str(x) for x in data["blocked_users"])
        return web.json_response({"ok": True})


# ======================================================================
# 自测 & 入口
# ======================================================================

def run_selftest() -> int:
    """离线验证消息解析与文本拆分逻辑。"""
    print("=" * 60)
    print("邪恶鲸鱼娘 自测：消息解析 + 文本拆分")
    print("=" * 60)

    cases: List[Tuple[Any, str, Tuple[bool, str]]] = [
        ("[CQ:at,qq=123456] 你好呀", "123456", (True, "你好呀")),
        ("早上好 [CQ:at,qq=123456] 今天天气怎么样", "123456", (True, "今天天气怎么样")),
        ("[CQ:at,qq=123456]   ", "123456", (True, "")),
        ("[CQ:at,qq=all] 大家听我说", "123456", (False, "大家听我说")),
        ("[CQ:at,qq=999] 找别人", "123456", (False, "找别人")),
        ("今天天气不错", "123456", (False, "今天天气不错")),
        # 中间被移除的 @别人 会留一个双空格，属正常现象
        ("[CQ:at,qq=123456] @前面的话不算 [CQ:at,qq=888] 中间插了别人", "123456", (True, "@前面的话不算  中间插了别人")),
        ([{"type": "at", "data": {"qq": "123456"}},
          {"type": "text", "data": {"text": " 会数组格式吗"}}], "123456", (True, "会数组格式吗")),
        ([{"type": "text", "data": {"text": "数组没@"}},
          {"type": "at", "data": {"qq": "123456"}},
          {"type": "text", "data": {"text": " 只取@后面的"}}], "123456", (True, "只取@后面的")),
    ]

    failed = 0
    for msg, qq, expected in cases:
        segs = parse_message_segments(msg)
        at_bot, after, _reply, _full = extract_at_info(segs, qq)
        got = (at_bot, after)
        tag = "PASS" if got == expected else "FAIL"
        if got != expected:
            failed += 1
        print(f"[{tag}] message={msg!r}\n       -> at_bot={at_bot} after={after!r} 期望={expected}")

    long_text = "第一行\n" + "长" * 5000 + "\n最后一行"
    pieces = split_long_text(long_text, limit=3800)
    print(f"\n[拆分测试] 原文 {len(long_text)} 字符 -> {len(pieces)} 条，最长 {max(len(p) for p in pieces)} 字符")
    assert all(len(p) <= 3800 for p in pieces), "拆分后存在超长消息！"
    print("[拆分测试] 通过：无超长消息")

    # ---------- A组 交互基础自测 ----------
    print("\n[--- A组 交互基础自测 ---]")
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({
        "bot_qq": "123456",
        "deepseek_api_key": "sk-test",
        "trigger_keywords": ["鱼", "鲸鱼"],
        "cooldown_seconds": 10,
        "personas": {"高冷": "你是高冷的机器人，说话简短冷淡。"},
    })
    bot = WhaleBot(cfg)
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            ok = False

    check("关键词命中", bot.hit_keyword("今天看到一条鲸鱼") is True)
    check("关键词未命中", bot.hit_keyword("今天天气不错") is False)
    bot.enable_keyword_trigger = False
    check("关键词开关关闭时不命中", bot.hit_keyword("一条鱼") is False)
    bot.enable_keyword_trigger = True

    bot.mark_engaged("g1", "u1")
    check("免@窗口内", bot.is_engaged("g1", "u1") is True)
    check("别的用户仍需@", bot.is_engaged("g1", "u2") is False)

    bot.mark_replied("g1", "u1")
    check("冷却中", bot.in_cooldown("g1", "u1") is True)
    check("未冷却用户", bot.in_cooldown("g1", "u2") is False)

    check("/help 含人设", "人设" in bot.handle_command("g1", "u1", "/help"))
    check("/人设 列表", "高冷" in bot.handle_command("g1", "u1", "/人设"))
    check("/人设 切换", "高冷" in bot.handle_command("g1", "u1", "/人设 高冷"))
    check("群人设生效", "高冷" in bot.get_persona("g1"))
    check("未知指令提示", "没看懂" in bot.handle_command("g1", "u1", "/xx"))

    # ---------- B组 用户画像自测 ----------
    print("\n[--- B组 用户画像自测 ---]")
    for t in ["今天打了一局王者荣耀", "王者荣耀上分好难", "今天天气不错"]:
        bot.update_profile("g1", "u9", {"card": "小明"}, t)
    prof = bot.get_profile_line("g1", "u9")
    check("画像含昵称", "小明" in prof)
    check("画像含常用话题", "王者" in prof)
    check("/画像 命令", "小明" in bot.handle_command("g1", "u9", "/画像"))
    check("无画像用户提示", "还没有" in bot.handle_command("g1", "u8", "/画像"))
    check("bigram 提取", "王者" in bot._bigrams("今天玩王者荣耀"))
    check("未触发也记录画像", bot.get_profile_line("g1", "u9") != "")

    # ---------- C组 AI 能力进阶自测 ----------
    print("\n[--- C组 AI 能力进阶自测 ---]")
    check("路由-简单走fast", bot.route_model("你好") == "deepseek-chat")
    check("路由-复杂走reasoner", bot.route_model("帮我想一个方案并分析利弊") == "deepseek-reasoner")
    check("路由-超长走reasoner", bot.route_model("很" * 70) == "deepseek-reasoner")
    bot.router_enabled = False
    check("路由-关闭后统一直行", bot.route_model("为什么这样") == bot.model)
    bot.router_enabled = True
    check("安全计算", bot._safe_calc("(3+5)*2") == 16)
    check("工具定义存在", len(bot._tool_definitions()) == 4)
    _t = asyncio.run(bot._execute_tool("get_current_time", {}))
    check("工具-当前时间", bool(_t) and len(_t) >= 16)
    _c = asyncio.run(bot._execute_tool("calculate", {"expression": "10/2"}))
    check("工具-计算", _c == "5.0" or _c == "5")
    bot.enable_web_search = True
    check("联网搜索-开启后在定义中", any(t["function"]["name"] == "web_search" for t in bot._tool_definitions()))
    check("联网搜索-空查询提示", asyncio.run(bot._tool_web_search("")) == "请提供要搜索的关键词。")
    bot.enable_web_search = False

    # ---------- D组 长期记忆自测 ----------
    print("\n[--- D组 长期记忆自测 ---]")
    bot.memory_enabled = True
    bot.memory_file = os.path.join(os.environ.get("TEMP", "."), "aiyu_memory_test.json")
    bot.record_memory("g1", "u1", "我喜欢玩王者荣耀", "记住啦，你爱打王者")
    bot.record_memory("g1", "u1", "我养了一只猫叫团子", "猫咪叫团子呀")
    ml = bot.get_memory_line("g1", "u1", "王者荣耀上分有什么技巧")
    check("长期记忆-话题召回", "王者" in ml)
    check("长期记忆-无关不召回", bot.get_memory_line("g1", "u1", "完全无关的话题") == "")
    check("相似度-相同文本高", bot._similarity("王者荣耀上分", "王者荣耀上分") > 0.5)
    check("/记忆 命令", "条记忆" in bot.handle_command("g1", "u1", "/记忆"))
    check("/记忆 清空", "清空" in bot.handle_command("g1", "u1", "/记忆 清空"))
    check("清空后为0", len(bot.memory.get(("g1", "u1"), [])) == 0)
    try:
        os.remove(bot.memory_file)
    except OSError:
        pass

    # ---------- 人设切换接口自测 ----------
    print("\n[--- 人设切换接口自测 ---]")
    check("切换-列人设", "可用人设" in bot.handle_persona_switch("g1", ""))
    check("切换-成功", "已切換" in bot.handle_persona_switch("g1", "高冷"))
    check("切换-切换到默认", "默认" in bot.handle_persona_switch("g1", "默认"))
    check("切换-不存在提示", "没这个人设" in bot.handle_persona_switch("g1", "不存在"))
    check("切换后群对该人设生效", bot.get_persona("g1") == "高冷" or bot.get_persona("g1") == (bot.system_prompt or ""))
    bot.group_persona.pop("g1", None)

    # ---------- F组 权限自测 ----------
    print("\n[--- F组 权限与告警自测 ---]")
    bot.admin_qq = "999"
    bot.allowed_groups, bot.blocked_groups = set(), {"g_bad"}
    bot.allowed_users, bot.blocked_users = set(), {"u_bad"}
    check("普通群-允许", bot.is_allowed("g_ok", "u1") is True)
    check("黑名单群-禁用", bot.is_allowed("g_bad", "u1") is False)
    check("黑名单用户-禁用", bot.is_allowed("g_ok", "u_bad") is False)
    bot.allowed_groups = {"g_only"}
    check("白名单-不在名单禁用", bot.is_allowed("g_other", "u1") is False)
    check("白名单-在名单允许", bot.is_allowed("g_only", "u1") is True)
    check("管理员-绕过用户限制", bot.is_allowed("g_other", "999") is True)
    bot.allowed_groups = set()

    # ---------- G组 配置热更新自测 ----------
    print("\n[--- G组 配置热更新自测 ---]")
    tmp = os.path.join(os.environ.get("TEMP", "."), "aiyu_cfg_test.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"history_limit": 7, "enable_keyword_trigger": False}, f, ensure_ascii=False)
    bot.config_path = tmp
    bot.reload_config()
    check("热更新-history_limit生效", bot.history_limit == 7)
    check("热更新-关键词开关生效", bot.enable_keyword_trigger is False)
    os.remove(tmp)

    if not ok:
        failed += 1

    print()
    if failed:
        print(f"❌ {failed} 个用例失败")
        return 1
    print("✅ 全部解析用例通过。可以放心联网运行了。")
    return 0


def load_config(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        log.error("找不到配置文件：%s", path)
        raise SystemExit(1)
    with open(path, "r", encoding="utf-8") as f:
        user_cfg = json.load(f)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(user_cfg)
    return cfg


async def async_main(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    bot = WhaleBot(cfg)
    bot.config_path = args.config
    if bot.web_enabled and bot.web_token:
        await bot.start_web()
    try:
        await bot.run()
    except KeyboardInterrupt:
        log.info("收到退出信号……")
    finally:
        await bot.close()
        log.info("已退出")


def main() -> None:
    parser = argparse.ArgumentParser(description="邪恶鲸鱼娘 —— QQ 群 AI 机器人")
    parser.add_argument("--config", default="config.json", help="配置文件路径（默认 config.json）")
    parser.add_argument("--selftest", action="store_true", help="离线自测消息解析逻辑")
    args = parser.parse_args()

    # Windows 控制台默认 GBK，强制 UTF-8 输出，避免打印 ✅/❌/中文时崩溃
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")

    if args.selftest:
        sys.exit(run_selftest())
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
