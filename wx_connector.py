# -*- coding: utf-8 -*-
"""
微信连接器集合（微信 3.9.12 优先）
按优先级尝试: wxauto → PwaConnector → WxConnector

wxauto:       第三方库，原生支持微信 3.9.x（推荐）
PwaConnector: 基于 pywinauto，直接读主窗口消息（备用）
WxConnector:  底层 uiautomation 备用方案
"""

import time
import logging
import threading
from collections import OrderedDict

logger = logging.getLogger("wx_monitor")


# ============================================================
# 自定义 WxConnector（底层 uiautomation 备用方案）
# ============================================================

class WxConnector:
    """
    自定义微信连接器，不依赖 wxauto4/wxauto/pyweixin
    通过 uiautomation + 键盘模拟操作微信
    """

    def __init__(self, search_timeout=5):
        try:
            import uiautomation as uia
            self.uia = uia
        except ImportError:
            raise ImportError("请安装 uiautomation: pip install uiautomation")

        self.search_timeout = search_timeout
        self.main_window = None
        self.current_chat = None
        self._listen_chats = OrderedDict()
        self._lock = threading.Lock()
        self._connect()

    def _connect(self):
        logger.info("正在连接微信窗口(uiautomation)...")
        uia = self.uia
        self.main_window = self._find_wechat_window()
        if not self.main_window:
            raise ConnectionError("未找到微信窗口！请确保微信已打开并登录，窗口可见（未最小化）")
        try:
            self.main_window.SetFocus()
            time.sleep(0.5)
        except Exception:
            try:
                self.main_window.SwitchToThisWindow()
                time.sleep(0.5)
            except Exception as e:
                logger.warning(f"激活微信窗口失败: {e}")
        logger.info(f"微信窗口连接成功: 标题={self.main_window.Name}, 类名={self.main_window.ClassName}")

    def _find_wechat_window(self):
        uia = self.uia
        for class_name in ["WeChatMainWndForPC", "Chrome_WidgetWin_0"]:
            try:
                wnd = uia.WindowControl(ClassName=class_name, searchDepth=1)
                if wnd.Exists(maxSearchSeconds=2):
                    return wnd
            except Exception:
                continue
        try:
            wnd = uia.WindowControl(Name="微信", searchDepth=1)
            if wnd.Exists(maxSearchSeconds=2):
                return wnd
        except Exception:
            pass
        root = uia.GetRootControl()
        for child in root.GetChildren():
            name = child.Name or ""
            classname = child.ClassName or ""
            if "微信" in name or "WeChat" in classname:
                return child
        return None

    def _ensure_focus(self):
        try:
            self.main_window.SetFocus()
            time.sleep(0.3)
        except Exception:
            try:
                self.main_window.SwitchToThisWindow()
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"无法激活微信窗口: {e}")

    def chat_with(self, name):
        if self.current_chat == name:
            return True
        self._ensure_focus()
        uia = self.uia
        try:
            uia.SendKey(uia.Keys.VK_CONTROL, waitTime=0.05)
            time.sleep(0.1)
            uia.SendKeys("{Ctrl}a", interval=0.02)
            time.sleep(0.1)
            uia.SendKeys(name, interval=0.05)
            time.sleep(1.5)
            uia.SendKey(uia.Keys.VK_RETURN)
            time.sleep(0.5)
            self.current_chat = name
            return True
        except Exception as e:
            logger.error(f"切换聊天失败 [{name}]: {e}")
            return False

    def send_msg(self, text, who=None):
        with self._lock:
            if who and who != self.current_chat:
                self.chat_with(who)
            self._ensure_focus()
            uia = self.uia
            try:
                uia.SendKeys(text, interval=0.02)
                time.sleep(0.2)
                uia.SendKey(uia.Keys.VK_RETURN)
                logger.info(f"消息已发送: {text[:30]}")
                return True
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                return False

    def add_listen_chat(self, who):
        self._listen_chats[who] = None
        logger.info(f"已添加监听: {who}")

    def get_listen_message(self):
        result = {}
        for chat_name in list(self._listen_chats.keys()):
            try:
                if not self.chat_with(chat_name):
                    continue
                time.sleep(0.5)
                messages = self._read_visible_messages()
                if not messages:
                    continue
                last_msg = self._listen_chats[chat_name]
                if last_msg is None:
                    if messages:
                        self._listen_chats[chat_name] = messages[-1].content
                    continue
                new_msgs = []
                found = False
                for msg in messages:
                    if found:
                        new_msgs.append(msg)
                    elif msg.content == last_msg:
                        found = True
                if not found and messages:
                    new_msgs = messages[-3:]
                if new_msgs:
                    self._listen_chats[chat_name] = new_msgs[-1].content
                    class _W:
                        def __init__(s, n): s.who = n
                    result[_W(chat_name)] = new_msgs
            except Exception as e:
                logger.error(f"轮询 [{chat_name}] 失败: {e}")
        return result

    def _read_visible_messages(self):
        uia = self.uia
        messages = []
        try:
            for aid in ["msgListBody", "ChatMsgList", "messageList"]:
                try:
                    ctrl = self.main_window.ListControl(AutomationId=aid)
                    if ctrl.Exists(maxSearchSeconds=0.5):
                        for child in ctrl.GetChildren():
                            name = child.Name or ""
                            if name:
                                class M:
                                    def __init__(s, t, c): s.type, s.content, s.sender = t, c, None
                                messages.append(M("friend", name))
                        break
                except Exception:
                    continue
        except Exception:
            pass
        return messages


# ============================================================
# 统一连接器工厂
# ============================================================

def create_connector():
    """
    创建微信连接器（微信 3.9.12 优先）
    按优先级尝试:
    1. wxauto       - 原生支持微信 3.9.x（推荐，最稳定）
    2. PwaConnector - 基于 pywinauto 的自包含方案（备用）
    3. WxConnector  - 基于 uiautomation 的底层备用方案
    """
    # === 尝试1: wxauto（微信 3.9.x 最佳方案）===
    try:
        from wxauto import WeChat
        wx = WeChat()
        logger.info("wxauto 连接成功（微信 3.9.x 推荐方案）")
        return wx
    except ImportError:
        logger.info("wxauto 未安装，跳过（请运行: pip install wxauto）")
    except Exception as e:
        logger.warning(f"wxauto 连接失败: {e}")

    # === 尝试2: PwaConnector（pywinauto 备用）===
    try:
        from pwa_connector import PwaConnector, check_pwa_available
        if check_pwa_available():
            connector = PwaConnector()
            logger.info("PwaConnector 连接成功（pywinauto 备用方案）")
            return connector
        else:
            logger.info("pywinauto 未安装，跳过 PwaConnector")
    except Exception as e:
        logger.warning(f"PwaConnector 失败: {e}")

    # === 尝试3: 底层 WxConnector ===
    logger.info("所有高级连接器失败，使用底层 WxConnector...")
    try:
        connector = WxConnector()
        logger.info("WxConnector 连接成功")
        return connector
    except Exception as e:
        logger.error(f"WxConnector 也失败: {e}")
        raise ConnectionError(
            "所有连接方式均失败！\n\n"
            "请确保:\n"
            "  1. 已安装 wxauto: pip install wxauto\n"
            "  2. 微信 3.9.12 已打开并登录\n"
            "  3. 微信窗口可见（未最小化）\n"
            f"\n最后错误: {e}"
        )
