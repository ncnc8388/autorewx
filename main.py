# -*- coding: utf-8 -*-
"""
微信群消息监控自动回复工具
- 监控指定群中指定人员的消息
- 监控消息中的关键字（如地名、事件名等）
- 拟人化随机延迟后自动回复
- 配置文件 config.json 支持热加载
"""

import json
import os
import sys
import time
import random
import threading
import logging
import hashlib
from datetime import datetime
from pathlib import Path

# ============================================================
# 日志配置
# ============================================================
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            LOG_DIR / f"wx_monitor_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("wx_monitor")

# ============================================================
# 配置管理（支持热加载）
# ============================================================
CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config():
    """加载配置文件"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        logger.info("配置文件加载成功")
        return config
    except FileNotFoundError:
        logger.error(f"配置文件不存在: {CONFIG_PATH}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"配置文件格式错误: {e}")
        sys.exit(1)


def get_config_mtime():
    """获取配置文件的修改时间"""
    try:
        return os.path.getmtime(CONFIG_PATH)
    except OSError:
        return 0


def get_enabled_groups(config):
    """获取所有启用的群及其配置（成员列表 + 关键字列表）"""
    groups = {}
    for group_name, group_info in config.get("groups", {}).items():
        if group_info.get("enabled", True):
            groups[group_name] = {
                "members": group_info.get("members", []),
                "keywords": group_info.get("keywords", []),
            }
    return groups


def print_config_summary(config):
    """打印当前配置摘要"""
    groups = get_enabled_groups(config)
    global_kw = config.get("global_keywords", [])
    logger.info("=" * 50)
    logger.info("当前监控配置:")
    for group_name, info in groups.items():
        members = info["members"]
        keywords = info["keywords"]
        member_str = ', '.join(members) if members else '无'
        kw_str = ', '.join(keywords) if keywords else '无'
        logger.info(f"  群: {group_name}")
        logger.info(f"    监控人员: {member_str}")
        logger.info(f"    监控关键字: {kw_str}")
    if global_kw:
        logger.info(f"  全局关键字: {', '.join(global_kw)}")
    delay = config.get("delay", {"min": 15, "max": 70})
    logger.info(f"  回复延迟: {delay.get('min', 15)}~{delay.get('max', 70)} 秒")
    logger.info(f"  群冷却时间: {config.get('group_cooldown', 10)} 秒（防抖）")
    logger.info(f"  人员回复语池: {config.get('replies', ['收到'])}")
    logger.info(f"  关键字回复语池: {config.get('keyword_replies', ['收到'])}")
    logger.info("=" * 50)


# ============================================================
# 微信自动化核心
# ============================================================


def init_wechat():
    """初始化微信连接（优先wxauto系列，失败则用自定义连接器）"""
    try:
        from wx_connector import create_connector
        wx = create_connector()
        return wx
    except ConnectionError as e:
        logger.error(f"所有连接方式失败: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"初始化微信连接异常: {e}")
        sys.exit(1)


def setup_listeners(wx, groups):
    """
    设置消息监听（兼容 wxauto 和自定义连接器）
    wxauto 3.9.x 需要为每个群打开独立聊天窗口(ChatWnd)才能监听
    """
    for group_name in groups:
        success = False

        # === 方式1: 直接 AddListenChat ===
        if hasattr(wx, 'AddListenChat'):
            try:
                wx.AddListenChat(who=group_name)
                logger.info(f"已添加监听(wxauto): {group_name}")
                success = True
            except Exception as e1:
                logger.warning(f"AddListenChat 首次失败 [{group_name}]: {e1}")
                logger.info(f"尝试手动打开聊天窗口后重试...")

                # 手动兜底：先用 ChatWith 切换到该群，再打开独立窗口
                try:
                    _open_chat_window(wx, group_name)
                    time.sleep(1.0)
                    wx.AddListenChat(who=group_name)
                    logger.info(f"已添加监听(wxauto重试): {group_name}")
                    success = True
                except Exception as e2:
                    logger.error(f"重试 AddListenChat 仍失败 [{group_name}]: {e2}")

        # === 方式2: 自定义连接器 add_listen_chat ===
        if not success and hasattr(wx, 'add_listen_chat'):
            try:
                wx.add_listen_chat(group_name)
                logger.info(f"已添加监听(自定义连接器): {group_name}")
                success = True
            except Exception as e:
                logger.error(f"添加监听失败 [{group_name}]: {e}")

        if not success:
            logger.error(
                f"无法添加监听 [{group_name}]！\n"
                f"  请手动双击打开该群的独立聊天窗口，然后重启程序。"
            )


def _open_chat_window(wx, group_name):
    """
    手动打开群的独立聊天窗口（wxauto 3.9.x 兜底）
    原理：先用 ChatWith 搜索并切换到该群，然后模拟双击打开独立窗口
    """
    import uiautomation as uia

    # 先确保主窗口在前台
    try:
        wx._show()
    except Exception:
        pass

    time.sleep(0.3)

    # 尝试多种方法找到并双击该群
    opened = False

    # 方法1：直接在会话列表中找（群名可能包含额外信息，用 RegexName）
    try:
        import re as _re
        escaped = _re.escape(group_name)
        item = wx.SessionBox.ListItemControl(RegexName=escaped, searchDepth=20)
        if item.Exists(maxSearchSeconds=2):
            item.DoubleClick(simulateMove=False)
            logger.info(f"双击会话列表打开独立窗口: {group_name}")
            opened = True
    except Exception as e:
        logger.debug(f"方法1(会话列表双击)失败: {e}")

    if not opened:
        # 方法2：用 ChatWith 切换到该群，再用 Ctrl+Enter 或双击打开独立窗口
        try:
            result = wx.ChatWith(group_name)
            time.sleep(0.5)

            # ChatWith 后，群已在主窗口显示，尝试再次双击会话列表项
            import re as _re
            escaped = _re.escape(group_name)
            try:
                item = wx.SessionBox.ListItemControl(RegexName=escaped, searchDepth=20)
                if item.Exists(maxSearchSeconds=2):
                    item.DoubleClick(simulateMove=False)
                    logger.info(f"ChatWith后双击打开独立窗口: {group_name}")
                    opened = True
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"ChatWith 异常: {e}")

    if not opened:
        # 方法3：尝试通过搜索框搜索群名，然后在搜索结果中双击
        try:
            wx._show()
            wx.UiaAPI.SendKeys('{Ctrl}f', waitTime=0.5)
            wx.B_Search.SendKeys(group_name, waitTime=1.5)
            time.sleep(0.5)
            # 在搜索结果中查找并双击
            search_results = wx.SessionBox.GetChildren()
            if len(search_results) > 1:
                # 搜索结果通常在第二个子元素里
                for child in search_results[1].GetChildren():
                    try:
                        if group_name in (child.Name or ''):
                            child.DoubleClick(simulateMove=False)
                            logger.info(f"搜索结果双击打开: {group_name}")
                            opened = True
                            break
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"方法3(搜索双击)失败: {e}")

    if opened:
        time.sleep(1.5)  # 等待独立窗口完全打开
        # 验证 ChatWnd 是否已存在
        chat_wnd = uia.WindowControl(searchDepth=1, ClassName='ChatWnd', Name=group_name)
        if chat_wnd.Exists(maxSearchSeconds=3):
            logger.info(f"独立窗口已就绪: {group_name}")
        else:
            logger.warning(f"ChatWnd 未检测到，但已尝试打开: {group_name}")
    else:
        logger.warning(
            f"无法自动打开独立窗口 [{group_name}]！\n"
            f"  请在微信中手动双击该群聊打开独立窗口。"
        )


# ============================================================
# 消息去重追踪器
# ============================================================


class ProcessedMessageTracker:
    """
    追踪已处理的消息指纹，防止同一条消息被重复处理。
    使用 (群名, 发送者, 内容摘要) 作为指纹，带 TTL 自动过期。
    """

    def __init__(self, ttl=600):
        """
        Args:
            ttl: 指纹保留时间（秒），默认10分钟，超过此时间的记录自动清理
        """
        self.ttl = ttl
        self._fingerprints = {}  # {fingerprint_str: timestamp}
        self._lock = threading.Lock()

    def _make_fingerprint(self, group_name, sender, content):
        """生成消息指纹"""
        raw = f"{group_name}|{sender}|{content[:200]}"
        return hashlib.md5(raw.encode("utf-8", errors="replace")).hexdigest()

    def is_processed(self, group_name, sender, content):
        """检查消息是否已处理过"""
        fp = self._make_fingerprint(group_name, sender, content)
        with self._lock:
            return fp in self._fingerprints

    def mark_processed(self, group_name, sender, content):
        """标记消息为已处理"""
        fp = self._make_fingerprint(group_name, sender, content)
        with self._lock:
            self._fingerprints[fp] = time.time()

    def cleanup(self):
        """清理过期的指纹记录"""
        now = time.time()
        with self._lock:
            expired = [fp for fp, ts in self._fingerprints.items() if now - ts > self.ttl]
            for fp in expired:
                del self._fingerprints[fp]
            if expired:
                logger.debug(f"清理了 {len(expired)} 条过期消息指纹")

    @property
    def size(self):
        with self._lock:
            return len(self._fingerprints)


# ============================================================
# 回复调度器
# ============================================================


class ReplyScheduler:
    """
    管理延迟回复的调度器
    去重策略（不依赖发送者识别，基于消息内容判重）：
      - 群级冷却（短防抖）：防止同一轮次多条消息连续触发
      - 内容去重：同一群内，相同消息内容不重复回复；
        不同内容的消息各自独立触发，互不影响
      - 每组群维护最近 5 条已判定内容（pending + recently sent）
    """

    # 每组群最多追踪的消息内容数
    MAX_CONTENT_TRACKED = 5

    def __init__(self, wx_instance):
        self.wx = wx_instance
        self.lock = threading.Lock()
        # 待回复定时器: key=(群名, content_hash), value=threading.Timer
        self.pending_timers = {}
        # 群级冷却记录: key=群名, value=上次调度时间戳（短防抖）
        self.group_cooldown_records = {}
        # 内容追踪: key=群名, value=[(content, is_pending, timestamp), ...]
        #   is_pending=True: 定时器未触发；is_pending=False: 已发送或已取消
        self.content_records = {}
        # 回复统计
        self.stats = {
            "replied": 0,
            "skipped_group_cooldown": 0,
            "skipped_content_dup": 0,
            "skipped_filter": 0,
            "skipped_duplicate": 0,
        }

    def _get_group_contents(self, group_name):
        """获取某群的内容追踪列表（不创建新列表）"""
        return self.content_records.get(group_name, [])

    def _add_content_record(self, group_name, content):
        """
        记录一条已判定的内容。超出 MAX_CONTENT_TRACKED 时移除最旧的。
        返回当前列表大小。
        """
        if group_name not in self.content_records:
            self.content_records[group_name] = []
        records = self.content_records[group_name]
        records.append((content, True, time.time()))
        # 超出上限，移除最旧的（不管是否 pending）
        if len(records) > self.MAX_CONTENT_TRACKED:
            removed = records.pop(0)
            # 如果移除的是 pending 的，取消对应定时器
            if removed[1]:
                old_hash = hash(removed[0]) % 100000
                old_key = (group_name, old_hash)
                if old_key in self.pending_timers:
                    self.pending_timers[old_key].cancel()
                    del self.pending_timers[old_key]
                    logger.debug(f"超出追踪上限，取消旧定时器: {old_key}")
        return len(records)

    def _has_content_record(self, group_name, content):
        """检查该群是否已有相同内容的记录（pending 或 recently sent 都算）"""
        records = self.content_records.get(group_name, [])
        for rec_content, _, _ in records:
            if rec_content == content:
                return True
        return False

    def _mark_content_sent(self, group_name, content):
        """将指定内容标记为已发送（is_pending=False）"""
        records = self.content_records.get(group_name, [])
        for i, (rec_content, is_pending, ts) in enumerate(records):
            if rec_content == content and is_pending:
                records[i] = (rec_content, False, ts)
                break

    def schedule_reply(self, group_name, sender, config, reason="person",
                        matched_keyword=None, content_str=""):
        """
        安排一个拟人化的延迟回复。

        去重逻辑（基于消息内容，不依赖发送者）：
          1. 群级冷却（短防抖，默认10秒）
          2. 内容去重：同一群内相同内容不重复回复

        Args:
            reason: 触发原因 - "person"(人员触发) 或 "keyword"(关键字触发)
            matched_keyword: 匹配到的关键字（仅 keyword 触发时有值）
            content_str: 原始消息内容（用于内容去重）
        """
        now = time.time()

        # --- 1. 群级冷却（短防抖，仅防止同一轮次连续触发）---
        group_cooldown = config.get("group_cooldown", 10)
        last_group_reply = self.group_cooldown_records.get(group_name, 0)
        if now - last_group_reply < group_cooldown:
            remaining = int(group_cooldown - (now - last_group_reply))
            logger.info(
                f"[群冷却中] {group_name}，"
                f"距离可回复还需 {remaining} 秒"
            )
            self.stats["skipped_group_cooldown"] += 1
            return

        # --- 2. 内容去重：同一群内相同内容不重复回复 ---
        if content_str:
            with self.lock:
                if self._has_content_record(group_name, content_str):
                    logger.info(
                        f"[内容重复跳过] {group_name}: "
                        f"该内容已在追踪列表中，不重复回复"
                    )
                    self.stats["skipped_content_dup"] += 1
                    return

        # 立即记录群冷却（防止同群在定时器触发前也通过检查）
        with self.lock:
            self.group_cooldown_records[group_name] = now

        # 定时器key：用内容hash区分不同消息，使各自有独立的定时器
        content_hash = hash(content_str) % 100000 if content_str else 0
        timer_key = (group_name, content_hash)

        # 取消已有的相同内容定时器（理论上不应存在，但保险起见）
        with self.lock:
            if timer_key in self.pending_timers:
                self.pending_timers[timer_key].cancel()
                logger.debug(f"取消旧定时器: {timer_key}")

        # 计算随机延迟
        delay_cfg = config.get("delay", {"min": 15, "max": 70})
        delay_min = delay_cfg.get("min", 15)
        delay_max = delay_cfg.get("max", 70)
        delay = random.uniform(delay_min, delay_max)

        # 根据触发原因选择回复内容
        if reason == "keyword":
            keyword_replies = config.get("keyword_replies", [])
            if keyword_replies:
                reply_text = random.choice(keyword_replies)
            else:
                reply_text = random.choice(config.get("replies", ["收到"]))
            trigger_label = f"关键字「{matched_keyword}」触发"
        else:
            reply_text = random.choice(config.get("replies", ["收到"]))
            trigger_label = "人员触发"

        logger.info(
            f"[计划回复] {group_name} ({trigger_label}) -> "
            f"{delay:.1f}秒后回复「{reply_text}」"
        )

        # 记录内容追踪
        with self.lock:
            if content_str:
                self._add_content_record(group_name, content_str)

        # 创建定时器（传递 content_str 用于发送后标记）
        timer = threading.Timer(
            delay, self._do_reply,
            args=(timer_key, group_name, reply_text, content_str)
        )
        timer.daemon = True

        with self.lock:
            self.pending_timers[timer_key] = timer

        timer.start()

    def _do_reply(self, key, group_name, reply_text, content_str=""):
        """执行实际的回复操作"""
        with self.lock:
            self.pending_timers.pop(key, None)
            now = time.time()
            self.group_cooldown_records[group_name] = now
            # 标记内容已发送
            if content_str:
                self._mark_content_sent(group_name, content_str)

        try:
            self.wx.SendMsg(reply_text, who=group_name)
            self.stats["replied"] += 1
            logger.info(f"[已回复] {group_name} -> 「{reply_text}」")
        except Exception as e:
            logger.error(f"[回复失败] {group_name}: {e}")

    def cancel_all(self):
        """取消所有待发送的回复"""
        with self.lock:
            for timer in self.pending_timers.values():
                timer.cancel()
            self.pending_timers.clear()
        logger.info("已取消所有待发送回复")

    def print_stats(self):
        """打印统计信息"""
        pending = len(self.pending_timers)
        logger.info(
            f"统计: 已回复={self.stats['replied']}, "
            f"群冷却跳过={self.stats['skipped_group_cooldown']}, "
            f"内容重复跳过={self.stats['skipped_content_dup']}, "
            f"过滤跳过={self.stats['skipped_filter']}, "
            f"重复跳过={self.stats['skipped_duplicate']}, "
            f"待发送={pending}"
        )


# ============================================================
# 消息处理
# ============================================================


def check_keywords(text, group_keywords, global_keywords):
    """
    检查消息文本中是否包含监控关键字
    返回匹配到的第一个关键字，如果没有匹配则返回 None
    """
    if not text:
        return None
    text_lower = str(text).lower()
    # 优先匹配群级别关键字，再匹配全局关键字
    for kw in group_keywords:
        if kw.lower() in text_lower:
            return kw
    for kw in global_keywords:
        if kw.lower() in text_lower:
            return kw
    return None


def process_messages(msgs, enabled_groups, scheduler, config, msg_tracker):
    """
    处理监听到的新消息
    - msgs: GetListenMessage() 返回的消息字典
    - enabled_groups: {群名: {members: [...], keywords: [...]}}
    - msg_tracker: ProcessedMessageTracker 消息去重追踪器
    触发逻辑（OR 关系）：
      1. 发言人在监控人员列表中 → 人员触发回复
      2. 消息内容包含监控关键字 → 关键字触发回复
    """
    global_keywords = config.get("global_keywords", [])

    for chat, msg_list in msgs.items():
        # 获取聊天对象名称（群名或好友名）
        try:
            group_name = chat.who
        except AttributeError:
            group_name = str(chat)

        # 只处理启用的群
        if group_name not in enabled_groups:
            continue

        group_info = enabled_groups[group_name]
        monitored_members = group_info["members"]
        group_keywords = group_info["keywords"]

        for one_msg in msg_list:
            try:
                # 兼容新旧 wxauto 消息格式
                if hasattr(one_msg, "type"):
                    msg_type = one_msg.type
                    msg_content = getattr(one_msg, "content", str(one_msg))
                    msg_sender = getattr(one_msg, "sender", None)
                elif isinstance(one_msg, (list, tuple)) and len(one_msg) >= 2:
                    msg_sender = one_msg[0]
                    msg_content = one_msg[1]
                    msg_type = "friend" if msg_sender not in ("SYS", "Self", "sys", "self") else "sys"
                    if msg_sender in ("Self", "self"):
                        msg_type = "self"
                else:
                    continue

                # 跳过系统消息、自己发的消息、时间消息
                if msg_type in ("sys", "self", "time", "recall"):
                    continue

                # 确定发送者
                if msg_sender and msg_sender not in ("Self", "self", "SYS", "sys"):
                    sender = msg_sender
                else:
                    sender = msg_content.split(":")[0] if ":" in str(msg_content) else None

                content_str = str(msg_content)

                # === 消息去重检查 ===
                sender_for_dedup = sender or "unknown"
                if msg_tracker.is_processed(group_name, sender_for_dedup, content_str):
                    scheduler.stats["skipped_duplicate"] += 1
                    logger.debug(f"[重复消息跳过] {group_name} - {sender_for_dedup}: {content_str[:50]}")
                    continue

                # === 触发判定（OR 逻辑）===
                # 1. 关键字触发：消息包含关键字（优先计算，sender未知时也可靠）
                matched_keyword = check_keywords(content_str, group_keywords, global_keywords)
                is_keyword_match = matched_keyword is not None

                # 2. 人员触发：发言人在监控列表中
                if sender:
                    is_member_match = (not monitored_members) or (sender in monitored_members)
                else:
                    # 无法获取发送者时（微信4.1+ mmui不暴露sender）:
                    # - 如果没有配置监控人员（列表为空=监控所有人），视为匹配
                    # - 如果配置了监控人员，则无法确认，只依赖关键字匹配
                    is_member_match = not monitored_members
                    if monitored_members and not is_keyword_match:
                        logger.debug(
                            f"[未知发送者] {group_name}: 无法确认是否为监控人员，"
                            f"仅关键字可触发 (内容: {content_str[:50]})"
                        )

                # 两者都不匹配则跳过（但先标记已处理，避免重复检测）
                if not is_member_match and not is_keyword_match:
                    msg_tracker.mark_processed(group_name, sender_for_dedup, content_str)
                    scheduler.stats["skipped_filter"] += 1
                    continue

                # 标记消息已处理
                msg_tracker.mark_processed(group_name, sender_for_dedup, content_str)

                # 如果没有发送者，使用消息内容hash作为唯一标识（用于冷却机制）
                if not sender:
                    sender = f"unknown_{hash(content_str) % 10000}"

                # 记录消息
                content_preview = content_str[:80]
                if is_keyword_match:
                    logger.info(
                        f"[关键字命中] {group_name}: {content_preview} "
                        f"(命中: {matched_keyword})"
                    )
                elif is_member_match:
                    logger.info(f"[人员消息] {group_name} - {sender}: {content_preview}")

                # 安排回复：关键字触发优先级高于人员触发
                if is_keyword_match:
                    scheduler.schedule_reply(
                        group_name, sender, config,
                        reason="keyword", matched_keyword=matched_keyword,
                        content_str=content_str
                    )
                else:
                    scheduler.schedule_reply(
                        group_name, sender, config,
                        reason="person",
                        content_str=content_str
                    )

            except Exception as e:
                logger.error(f"处理消息时出错: {e}, 消息: {one_msg}")


# ============================================================
# 主循环
# ============================================================


def main():
    logger.info("微信群消息监控自动回复工具 启动中...")
    logger.info(f"配置文件: {CONFIG_PATH}")

    # 加载配置
    config = load_config()
    print_config_summary(config)

    # 初始化微信
    wx = init_wechat()

    # 获取启用的群
    enabled_groups = get_enabled_groups(config)
    if not enabled_groups:
        logger.error("没有配置任何启用的群，请检查 config.json")
        sys.exit(1)

    # 设置监听
    setup_listeners(wx, enabled_groups)

    # 创建回复调度器
    scheduler = ReplyScheduler(wx)

    # 创建消息去重追踪器
    msg_tracker = ProcessedMessageTracker(ttl=600)

    # 配置热加载
    last_config_mtime = get_config_mtime()
    last_stats_time = time.time()

    logger.info("开始监控消息... (按 Ctrl+C 停止)")
    logger.info("-" * 50)

    try:
        while True:
            # 检查配置文件是否有变更
            current_mtime = get_config_mtime()
            if current_mtime != last_config_mtime:
                last_config_mtime = current_mtime
                new_config = load_config()
                new_enabled = get_enabled_groups(new_config)

                # 检查是否需要更新监听列表
                old_groups = set(enabled_groups.keys())
                new_groups = set(new_enabled.keys())

                # 添加新增的群监听
                for group in new_groups - old_groups:
                    try:
                        if hasattr(wx, 'AddListenChat'):
                            wx.AddListenChat(who=group)
                        elif hasattr(wx, 'add_listen_chat'):
                            wx.add_listen_chat(group)
                        logger.info(f"[热加载] 新增监听: {group}")
                    except Exception as e:
                        logger.error(f"[热加载] 添加监听失败 [{group}]: {e}")

                # 注意: wxauto 不支持移除已添加的监听，但可以在 process_messages 中过滤
                removed = old_groups - new_groups
                if removed:
                    logger.info(f"[热加载] 以下群已禁用（仍会监听但不会回复）: {removed}")

                config = new_config
                enabled_groups = new_enabled
                print_config_summary(config)
                logger.info("[热加载] 配置已更新")

            # 获取监听消息（兼容 wxauto 和自定义连接器）
            try:
                if hasattr(wx, 'GetListenMessage'):
                    msgs = wx.GetListenMessage()
                elif hasattr(wx, 'get_listen_message'):
                    msgs = wx.get_listen_message()
                else:
                    msgs = None
                if msgs:
                    process_messages(msgs, enabled_groups, scheduler, config, msg_tracker)
            except Exception as e:
                logger.error(f"获取消息失败: {e}")

            # 每 60 秒打印一次统计 + 清理过期指纹
            now = time.time()
            if now - last_stats_time >= 60:
                scheduler.print_stats()
                msg_tracker.cleanup()
                logger.debug(f"消息指纹池大小: {msg_tracker.size}")
                last_stats_time = now

            # 休眠
            poll_interval = config.get("poll_interval", 3)
            time.sleep(poll_interval)

    except KeyboardInterrupt:
        logger.info("正在停止...")
        scheduler.cancel_all()
        scheduler.print_stats()
        logger.info("已停止")


if __name__ == "__main__":
    main()
