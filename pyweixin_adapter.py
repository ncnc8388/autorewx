# -*- coding: utf-8 -*-
"""
pyweixin 适配器 - 将 pyweixin (微信4.1+) 的 API 封装为与 wxauto 兼容的接口
这样 main.py 中的监控和回复逻辑无需大改

pyweixin 基于 pywinauto 实现 RPA 自动化（无 Hook 注入）
支持: 微信 4.1.6+ ~ 4.1.10+，Windows 7/10/11
安装: git clone https://github.com/Hello-Mr-Crab/pywechat.git
"""

import os
import sys
import time
import logging

logger = logging.getLogger("wx_monitor")

# pyweixin 源码路径（从 git clone 获取）
PYWEIXIN_REPO_NAMES = ["pywechat-main", "pywechat"]


def _find_pyweixin_path():
    """查找 pyweixin 模块路径"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for name in PYWEIXIN_REPO_NAMES:
        candidate = os.path.join(base_dir, name)
        if os.path.isdir(candidate):
            # 检查 pyweixin 子目录是否存在
            pyweixin_dir = os.path.join(candidate, "pyweixin")
            if os.path.isdir(pyweixin_dir):
                return candidate
    return None


def check_pyweixin_available():
    """检查 pyweixin 是否可用"""
    path = _find_pyweixin_path()
    if path:
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            import pyweixin  # noqa: F401
            return True
        except ImportError:
            return False
    return False


class _PyWeixinMessage:
    """
    兼容 wxauto 消息格式的消息对象
    - .type   : 'sys' / 'self' / 'friend' / 'time'
    - .content: 消息文本
    - .sender : 发送者名称
    """
    def __init__(self, content="", sender=None, raw_type=None):
        self.content = str(content) if content else ""
        self.sender = sender

        # 将 pyweixin 的 type 映射为 wxauto 风格
        if raw_type in ("sys", "SYS", "system", "System"):
            self.type = "sys"
        elif raw_type in ("self", "Self", "me", "Me"):
            self.type = "self"
        elif raw_type in ("time", "Time", "TIME"):
            self.type = "time"
        elif raw_type in ("recall", "Recall"):
            self.type = "recall"
        else:
            self.type = "friend"

    def __repr__(self):
        return f"Msg({self.type}, {self.sender}: {self.content[:30]})"


class _PyWeixinChatWindow:
    """兼容 wxauto ChatWindow 格式的聊天窗口标识"""
    def __init__(self, name):
        self.who = name

    def __repr__(self):
        return f"Chat({self.who})"

    def __hash__(self):
        return hash(self.who)

    def __eq__(self, other):
        if isinstance(other, _PyWeixinChatWindow):
            return self.who == other.who
        return False


class PyWeixinAdapter:
    """
    pyweixin 适配器，提供与 wxauto 兼容的接口:
      - AddListenChat(who=群名)
      - GetListenMessage() -> {ChatWindow: [Message, ...]}
      - SendMsg(msg, who=群名)
    """

    def __init__(self, listen_duration="5s"):
        """
        Args:
            listen_duration: 每次监听的时间窗口（pyweixin 格式，如 '3s', '5s', '1min'）
        """
        self._listen_duration = listen_duration
        self._dialog_windows = {}  # {group_name: dialog_window_object}
        self._navigator = None
        self._monitor = None
        self._messages = None
        self._auto_reply = None

        self._init_pyweixin()

    def _init_pyweixin(self):
        """初始化 pyweixin 模块"""
        path = _find_pyweixin_path()
        if not path:
            raise ImportError(
                "未找到 pyweixin 模块！\n"
                "请先运行以下命令下载:\n"
                "  git clone https://github.com/Hello-Mr-Crab/pywechat.git pywechat-main"
            )

        if path not in sys.path:
            sys.path.insert(0, path)

        try:
            from pyweixin import Navigator, Monitor, Messages
            self._navigator = Navigator
            self._monitor = Monitor
            self._messages = Messages
            logger.info("pyweixin 模块加载成功 (微信4.1+)")
        except ImportError as e:
            raise ImportError(f"pyweixin 模块导入失败: {e}")

        # 尝试导入 AutoReply（可选）
        try:
            from pyweixin import AutoReply
            self._auto_reply = AutoReply
        except ImportError:
            pass

    def AddListenChat(self, who):
        """
        添加监听的聊天群/好友（兼容 wxauto 接口）
        会打开该群的独立聊天窗口用于监听
        """
        if who in self._dialog_windows:
            logger.info(f"已在监听列表中: {who}")
            return

        dialog = None
        
        # 方法1: 尝试 pyweixin 的 Navigator
        try:
            dialog = self._navigator.open_seperate_dialog_window(
                friend=who,
                window_minimize=True,
                close_weixin=False
            )
            logger.info(f"[pyweixin] Navigator 打开成功: {who}")
        except Exception as e:
            logger.warning(f"[pyweixin] Navigator 失败 [{who}]: {e}")

        # 方法2: 直接用 pywinauto 查找已打开的聊天窗口
        if not dialog:
            try:
                from pywinauto import Application
                # 通过 Application 连接（与 pyweixin 兼容）
                app = Application(backend="uia").connect(
                    class_name="mmui::MainWindow", timeout=3
                )
                
                # 查找独立聊天窗口
                try:
                    dialog = app.window(
                        class_name="mmui::ChatSingleWindow",
                        title=who,
                        timeout=5
                    )
                    if dialog.exists():
                        logger.info(f"[pyweixin] 找到独立聊天窗口: {who}")
                except Exception as e:
                    logger.debug(f"[pyweixin] 未找到独立窗口: {e}")
                    
            except Exception as e:
                logger.error(f"[pyweixin] 查找窗口失败: {e}")

        if dialog:
            self._dialog_windows[who] = dialog
            logger.info(f"[pyweixin] 已添加监听: {who}")
        else:
            logger.error(f"[pyweixin] 无法找到聊天窗口: {who}")

    def add_listen_chat(self, who):
        """小写别名（兼容自定义连接器接口）"""
        self.AddListenChat(who)

    def GetListenMessage(self):
        """
        获取所有监听聊天的新消息（兼容 wxauto 接口）
        返回: {ChatWindow: [Message, ...]}
        """
        result = {}

        for group_name, dialog in list(self._dialog_windows.items()):
            try:
                # 调用 pyweixin 的 Monitor 监听消息
                raw_result = self._monitor.listen_on_chat(
                    dialog,
                    duration=self._listen_duration
                )

                if not raw_result:
                    continue

                # pyweixin 返回字典格式:
                # {'新消息总数':x, '文本数量':x, '文本内容':[], '消息发送人':[], ...}
                contents = []
                senders = []

                if isinstance(raw_result, dict):
                    contents = raw_result.get('文本内容', [])
                    senders = raw_result.get('消息发送人', [])
                elif isinstance(raw_result, tuple):
                    # 兼容旧的元组格式
                    if len(raw_result) >= 2:
                        contents = raw_result[0] if isinstance(raw_result[0], list) else []
                        senders = raw_result[1] if isinstance(raw_result[1], list) else []

                if not contents:
                    continue

                # 转换为兼容格式的消息列表
                messages = []
                for i, content in enumerate(contents):
                    sender = senders[i] if i < len(senders) else None
                    msg = _PyWeixinMessage(
                        content=content,
                        sender=sender,
                        raw_type="friend"
                    )
                    messages.append(msg)

                if messages:
                    chat_window = _PyWeixinChatWindow(group_name)
                    result[chat_window] = messages
                    logger.debug(f"[pyweixin] {group_name}: 新消息 {len(messages)} 条")

            except Exception as e:
                logger.error(f"[pyweixin] 监听 {group_name} 失败: {e}")

        return result

    def get_listen_message(self):
        """小写别名"""
        return self.GetListenMessage()

    def SendMsg(self, msg, who=None, clear=True, at=None):
        """
        发送消息（兼容 wxauto 接口）
        Args:
            msg: 消息文本
            who: 发送目标（群名/好友名）
        """
        target = who
        if not target and self._dialog_windows:
            # 没指定目标时，发送到第一个监听的群
            target = list(self._dialog_windows.keys())[0]

        if not target:
            logger.error("[pyweixin] 无法确定发送目标")
            return

        try:
            self._messages.send_messages_to_friend(
                friend=target,
                messages=[msg],
                close_weixin=False
            )
        except Exception as e:
            logger.error(f"[pyweixin] 发送消息失败 [{target}]: {e}")
            raise

    def send_msg(self, text, who=None):
        """小写别名"""
        self.SendMsg(text, who=who)
