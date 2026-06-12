# -*- coding: utf-8 -*-
"""
独立 pywinauto 连接器 - 支持微信 3.9.x 和 4.x
不需要打开独立聊天窗口，用户只需把群聊窗口放在最上面即可

核心原理（微信 3.9.x）：
1. pywinauto UIA 后端连接微信主窗口 (WeChatMainWndForPC)
2. 从 msgListBody 读取消息列表
3. 通过搜索框切换群聊
4. 通过编辑框发送消息

核心原理（微信 4.x）：
1. pywinauto UIA 后端连接微信主窗口 (mmui::MainWindow)
2. 从 chat_message_list 读取消息
3. 通过 session_list 切换群聊
4. 通过 chat_input_field 发送消息
"""

import re
import time
import logging
import threading
import ctypes
from ctypes import wintypes
from collections import OrderedDict

logger = logging.getLogger("wx_monitor")

try:
    from pywinauto import Application
    from pywinauto.keyboard import send_keys
    HAS_PYWINAUTO = True
except ImportError:
    HAS_PYWINAUTO = False


class _SimpleMessage:
    """消息对象（兼容 wxauto 格式）"""
    def __init__(self, content="", sender=None, msg_type="friend"):
        self.content = str(content) if content else ""
        self.sender = sender
        self.type = msg_type

    def __repr__(self):
        return f"Msg({self.type}, {self.sender}: {self.content[:30]})"


class _SimpleChatWindow:
    """聊天窗口标识（兼容 wxauto 格式）"""
    def __init__(self, name):
        self.who = name
    def __repr__(self):
        return f"Chat({self.who})"
    def __hash__(self):
        return hash(self.who)
    def __eq__(self, other):
        return isinstance(other, _SimpleChatWindow) and self.who == other.who


class PwaConnector:
    """
    基于 pywinauto 的微信连接器
    兼容 wxauto 接口: AddListenChat / GetListenMessage / SendMsg
    同时支持微信 3.9.x 和 4.x

    使用方式：用户将群聊窗口保持在微信主窗口最前面，程序直接读取
    """

    def __init__(self):
        if not HAS_PYWINAUTO:
            raise ImportError("请安装 pywinauto: pip install pywinauto")

        self._app = None
        self._main_window = None
        self._listen_groups = OrderedDict()  # {群名: 水印数据}
        self._sent_contents = []  # 最近发送的消息内容（用于识别自己发的消息）
        self._send_lock = threading.Lock()
        self._current_chat = None  # 当前主窗口显示的聊天名
        self._wx_version = None  # '3.9' 或 '4.x'

        self._connect()

    def _connect(self):
        """连接微信主窗口（同时支持 3.9.x 和 4.x）"""
        logger.info("正在通过 pywinauto 连接微信...")

        # 尝试1: 微信 3.9.x（WeChatMainWndForPC）
        try:
            self._app = Application(backend="uia").connect(
                class_name="WeChatMainWndForPC", timeout=10
            )
            self._main_window = self._app.window(class_name="WeChatMainWndForPC")
            self._wx_version = '3.9'
            logger.info("通过类名 WeChatMainWndForPC 连接成功（微信 3.9.x）")
        except Exception as e_39:
            # 尝试2: 微信 4.x（mmui::MainWindow）
            try:
                self._app = Application(backend="uia").connect(
                    class_name="mmui::MainWindow", timeout=10
                )
                self._main_window = self._app.window(class_name="mmui::MainWindow")
                self._wx_version = '4.x'
                logger.info("通过类名 mmui::MainWindow 连接成功（微信 4.x）")
            except Exception as e_4x:
                # 尝试3: 通用标题匹配
                try:
                    self._app = Application(backend="uia").connect(
                        title="微信", timeout=10
                    )
                    self._main_window = self._app.window(title="微信")
                    self._wx_version = '3.9'  # 默认按 3.9 处理
                    logger.info("通过标题 '微信' 连接成功")
                except Exception as e2:
                    raise ConnectionError(
                        f"无法连接微信窗口\n"
                        f"尝试1 (微信 3.9.x WeChatMainWndForPC): {e_39}\n"
                        f"尝试2 (微信 4.x mmui::MainWindow): {e_4x}\n"
                        f"尝试3 (标题 '微信'): {e2}\n"
                        "请确保微信已打开并登录"
                    )

        # 记录当前聊天名
        self._current_chat = self._get_current_chat_name()

        logger.info(f"pywinauto 连接微信成功, 版本: {self._wx_version}, 当前聊天: {self._current_chat or '未知'}")

    def _get_current_chat_name(self):
        """获取当前主窗口显示的聊天名称"""
        if self._wx_version == '3.9':
            return self._get_current_chat_name_39()
        else:
            return self._get_current_chat_name_4x()

    def _get_current_chat_name_39(self):
        """微信 3.9.x: 获取当前聊天名称"""
        try:
            # 3.9.x 中，当前聊天名称通常在主窗口顶部的 Text 控件中
            # 方法1: 查找 title 区域的 Text 控件
            for desc in self._main_window.descendants(control_type="Text"):
                try:
                    name = desc.window_text()
                    # 跳过工具栏按钮文字（通常很短）和空文字
                    if name and name.strip() and len(name.strip()) > 1:
                        # 检查这个控件是否在顶部区域（非消息区域）
                        rect = desc.rectangle()
                        main_rect = self._main_window.rectangle()
                        # 在窗口顶部 80px 以内，且不是工具栏按钮
                        if rect.top < main_rect.top + 80:
                            return name.strip()
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _get_current_chat_name_4x(self):
        """微信 4.x: 获取当前聊天名称"""
        # 方法1: 通过 auto_id 获取
        try:
            label = self._main_window.child_window(
                auto_id="current_chat_name_label", control_type="Text"
            )
            if label.exists(timeout=0.5):
                name = label.window_text()
                if name and name.strip():
                    return name.strip()
        except Exception:
            pass

        # 方法2: 通过标题栏区域搜索（更宽泛）
        try:
            title_area = self._main_window.child_window(
                auto_id="content_view.top_content_view.title_h_view", control_type="Text"
            )
            if title_area.exists(timeout=0.3):
                for child in title_area.descendants():
                    try:
                        aid = child.element_info.automation_id or ""
                        if "current_chat_name" in aid:
                            name = child.window_text()
                            if name and name.strip():
                                return name.strip()
                    except Exception:
                        continue
        except Exception:
            pass

        # 方法3: 搜索所有含 "current_chat_name" 的控件
        try:
            for desc in self._main_window.descendants(control_type="Text"):
                try:
                    aid = desc.element_info.automation_id or ""
                    if "current_chat_name" in aid:
                        name = desc.window_text()
                        if name and name.strip():
                            return name.strip()
                except Exception:
                    continue
        except Exception:
            pass

        return None

    def _type_text_via_clipboard(self, text):
        """通过剪贴板输入文本（ctypes 直接调 Windows API，零编码问题）"""
        if self._set_clipboard_text(text):
            time.sleep(0.15)
            send_keys("^v", pause=0.05)
            time.sleep(0.2)
        else:
            # 兜底: 逐字符输入（中文可能不可靠）
            logger.warning("剪贴板设置失败，尝试 send_keys 兜底")
            try:
                send_keys(text, pause=0.03)
            except Exception:
                pass

    @staticmethod
    def _set_clipboard_text(text):
        """通过 ctypes 调用 Windows 剪贴板 API 设置 Unicode 文本"""
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            # 声明函数签名（64位兼容）
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.EmptyClipboard.restype = wintypes.BOOL
            user32.SetClipboardData.restype = wintypes.HANDLE
            user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
            user32.CloseClipboard.restype = wintypes.BOOL
            kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
            kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            kernel32.GlobalLock.restype = wintypes.LPVOID
            kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalUnlock.restype = wintypes.BOOL
            kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalFree.restype = wintypes.HGLOBAL
            kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002

            # UTF-16LE 编码 + 两字节 null 终止符
            data = text.encode("utf-16-le") + b"\x00\x00"

            if not user32.OpenClipboard(0):
                return False
            try:
                user32.EmptyClipboard()
                h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                if not h_mem:
                    return False
                ptr = kernel32.GlobalLock(h_mem)
                if not ptr:
                    kernel32.GlobalFree(h_mem)
                    return False
                ctypes.memmove(ptr, data, len(data))
                kernel32.GlobalUnlock(h_mem)
                user32.SetClipboardData(CF_UNICODETEXT, h_mem)
                return True
            finally:
                user32.CloseClipboard()
        except Exception as e:
            logger.debug(f"ctypes 剪贴板失败: {e}")
            return False

    def _switch_to_group(self, group_name):
        """
        切换到指定群聊
        3.9.x: 通过搜索框搜索群名并回车进入
        4.x:   通过会话列表点击
        """
        current = self._get_current_chat_name()
        if current and group_name in current:
            return True

        logger.info(f"切换到群聊: {group_name}")

        if self._wx_version == '3.9':
            return self._switch_to_group_39(group_name)
        else:
            return self._switch_to_group_4x(group_name)

    def _switch_to_group_39(self, group_name):
        """微信 3.9.x: 通过搜索框切换群聊"""
        try:
            self._main_window.set_focus()
            time.sleep(0.2)

            # 3.9.x 使用 Ctrl+F 打开搜索，输入群名，回车
            send_keys("^f", pause=0.1)
            time.sleep(0.5)

            # 通过剪贴板输入群名
            self._type_text_via_clipboard(group_name)
            time.sleep(1.5)

            # 回车选中第一个搜索结果
            send_keys("{ENTER}", pause=0.1)
            time.sleep(0.5)

            self._current_chat = self._get_current_chat_name()
            logger.info(f"已切换到: {self._current_chat}")
            return True

        except Exception as e:
            logger.error(f"切换群聊失败 [{group_name}]: {e}")
            return False

    def _switch_to_group_4x(self, group_name):
        """微信 4.x: 通过会话列表点击切换"""
        try:
            self._main_window.set_focus()
            time.sleep(0.2)

            session_list = self._main_window.child_window(
                auto_id="session_list", control_type="List"
            )
            if not session_list.exists(timeout=1.0):
                logger.warning("未找到会话列表")
                return False

            items = session_list.children(control_type="ListItem")
            for item in items:
                try:
                    item_text = item.window_text() or ""
                    if group_name in item_text.split("\n")[0]:
                        item.click_input()
                        time.sleep(0.5)
                        self._current_chat = self._get_current_chat_name()
                        logger.info(f"已切换到: {self._current_chat}")
                        return True
                except Exception:
                    continue

            logger.warning(f"在会话列表中未找到: {group_name}")
            return False

        except Exception as e:
            logger.error(f"切换群聊失败 [{group_name}]: {e}")
            return False

    # ============================================================
    # 消息读取核心
    # ============================================================

    # 时间戳正则（各种格式）
    _TIME_PATTERN = re.compile(
        r'^(\d{1,2}:\d{2}(:\d{2})?'  # 14:30 / 14:30:05
        r'|昨天|前天'  # 昨天 / 前天
        r'|星期\w'  # 星期一
        r'|\d{1,2}月\d{1,2}日'  # 6月11日
        r'|\d{4}年'  # 2026年
        r')'
    )

    # 系统消息关键词
    _SYS_KEYWORDS = ["撤回", "以上为", "以下为", "加入群聊", "修改群名", "移出群聊"]

    @staticmethod
    def _is_garbled_text(text):
        """
        检测是否为乱码文本（剪贴板操作或UI读取异常产生的垃圾数据）
        特征: 包含私用区字符、CJK兼容区罕见字、控制字符等
        """
        if not text or len(text.strip()) <= 1:
            return True
        for ch in text:
            cp = ord(ch)
            # 控制字符（换行/回车/制表符除外）
            if cp < 32 and ch not in ('\n', '\r', '\t'):
                return True
            # Unicode 私用区 (Private Use Area)
            if 0xE000 <= cp <= 0xF8FF:
                return True
            if 0xF0000 <= cp <= 0xFFFFF:
                return True
            # CJK 兼容象形文字区 (U+3300-U+33FF)
            if 0x3300 <= cp <= 0x33FF:
                return True
            # CJK 兼容汉字 (U+F900-U+FAFF) - 极少正常使用
            if 0xF900 <= cp <= 0xFAFF:
                return True
        return False

    def _read_messages(self):
        """
        从主窗口读取当前可见消息（自动适配 3.9.x / 4.x）
        返回: [_SimpleMessage, ...]
        """
        if self._wx_version == '3.9':
            return self._read_messages_39()
        else:
            return self._read_messages_4x()
    
    def _read_messages_39(self):
        """
        微信 3.9.x: 从 msgListBody 读取消息
        3.9.x 的消息列表 AutomationId 为 'msgListBody' 或 'ChatMsgList'
        """
        messages = []
        try:
            # 尝试多个可能的消息列表控件 ID
            msg_list_ctrl = None
            for aid in ["msgListBody", "ChatMsgList", "messageList"]:
                try:
                    ctrl = self._main_window.child_window(
                        auto_id=aid, control_type="List"
                    )
                    if ctrl.exists(timeout=1.0):
                        msg_list_ctrl = ctrl
                        break
                except Exception:
                    continue
    
            # 再尝试用 ClassName 查找
            if not msg_list_ctrl:
                try:
                    msg_list_ctrl = self._main_window.ListControl(Name="消息")
                    if not msg_list_ctrl.exists(timeout=0.5):
                        msg_list_ctrl = None
                except Exception:
                    msg_list_ctrl = None
    
            if not msg_list_ctrl:
                logger.debug("未找到消息列表控件")
                return messages
    
            children = msg_list_ctrl.children()
            if not children:
                return messages
    
            logger.debug(f"消息列表: {len(children)} 个子项")
    
            for child in children:
                try:
                    text = child.window_text()
                    if not text or not text.strip():
                        continue
    
                    text = text.strip()
                    cls = child.element_info.class_name or ""
                    aid = child.element_info.automation_id or ""
    
                    # 时间消息：跳过
                    if self._TIME_PATTERN.match(text):
                        continue
    
                    # 系统消息（撤回、进群等）
                    if any(kw in text for kw in self._SYS_KEYWORDS):
                        sender_match = re.match(r'^["\u201c\u300c](.+?)["\u201d\u300d]', text)
                        sender = sender_match.group(1) if sender_match else None
                        messages.append(_SimpleMessage(text, sender=sender, msg_type="sys"))
                        continue
    
                    # 3.9.x 中，群消息格式通常为 "发送者\n消息内容"
                    # class name 中含 "Self" 表示自己发的消息
                    is_self = "Self" in cls or "self" in aid
                    if is_self:
                        msg_type = "self"
                    else:
                        msg_type = "friend"
    
                    # 提取发送者和内容
                    sender = None
                    content = text
    
                    if "\n" in text:
                        lines = text.split("\n")
                        if len(lines) >= 2:
                            sender = lines[0].strip()
                            content = "\n".join(lines[1:]).strip()
                            if not content:
                                content = text
                    elif "：" in text:
                        parts = text.split("：", 1)
                        if len(parts) == 2 and len(parts[0]) <= 10:
                            sender = parts[0].strip()
                            content = parts[1].strip()
                            if not content:
                                content = text
    
                    # 过滤乱码
                    if self._is_garbled_text(content):
                        logger.debug(f"跳过乱码消息: {content[:20]}")
                        continue
    
                    messages.append(_SimpleMessage(content, sender=sender, msg_type=msg_type))
    
                except Exception as e:
                    logger.debug(f"解析消息失败: {e}")
                    continue
    
        except Exception as e:
            logger.debug(f"读取消息失败: {e}")
    
        return messages
    
    def _read_messages_4x(self):
        """
        微信 4.x: 从 chat_message_list 读取消息
        """
        messages = []
        try:
            msg_list_ctrl = self._main_window.child_window(
                auto_id="chat_message_list", control_type="List"
            )
            if not msg_list_ctrl.exists(timeout=1.0):
                logger.debug("chat_message_list 不存在")
                return messages
    
            children = msg_list_ctrl.children()
            if not children:
                return messages
    
            logger.debug(f"消息列表: {len(children)} 个子项")
    
            for child in children:
                try:
                    text = child.window_text()
                    if not text or not text.strip():
                        continue
    
                    text = text.strip()
                    cls = child.element_info.class_name or ""
    
                    # 1) 系统消息: ChatItemView + 含系统关键词
                    if "ChatItemView" in cls:
                        if any(kw in text for kw in self._SYS_KEYWORDS):
                            sender_match = re.match(r'^["\u201c\u300c](.+?)["\u201d\u300d]', text)
                            sender = sender_match.group(1) if sender_match else None
                            messages.append(_SimpleMessage(text, sender=sender, msg_type="sys"))
                            continue
                        if self._TIME_PATTERN.match(text):
                            continue
                        continue
    
                    # 2) 文本消息: ChatTextItemView
                    if "ChatTextItemView" in cls or "ChatBubble" in cls or "chat_bubble" in (child.element_info.automation_id or ""):
                        if self._is_garbled_text(text):
                            logger.debug(f"跳过乱码消息: {text[:20]}")
                            continue
    
                        msg_type = "friend"
                        if self._is_self_message(text):
                            msg_type = "self"
    
                        sender = None
                        content = text
    
                        if "\n" in text:
                            lines = text.split("\n")
                            if len(lines) >= 2:
                                sender = lines[0].strip()
                                content = "\n".join(lines[1:]).strip()
                                if not content:
                                    content = text
                        elif "：" in text:
                            parts = text.split("：", 1)
                            if len(parts) == 2 and len(parts[0]) <= 10:
                                sender = parts[0].strip()
                                content = parts[1].strip()
                                if not content:
                                    content = text
    
                        messages.append(_SimpleMessage(content, sender=sender, msg_type=msg_type))
                        continue
    
                    # 3) 其他类型
                    if text and len(text) > 1:
                        messages.append(_SimpleMessage(text, msg_type="friend"))
    
                except Exception as e:
                    logger.debug(f"解析消息失败: {e}")
                    continue
    
        except Exception as e:
            logger.debug(f"读取消息失败: {e}")
    
        return messages

    def _is_self_message(self, text):
        """检查是否是自己发的消息（精确匹配 + 前缀匹配兜底）"""
        text_stripped = text.strip()
        # 清理已发送记录中过期的（超过60秒）
        now = time.time()
        self._sent_contents = [(t, c) for t, c in self._sent_contents if now - t < 60]
        # 精确匹配
        for _, content in self._sent_contents:
            if text_stripped == content:
                return True
        # 前缀匹配兜底（防止剪贴板损坏导致个别字符丢失/变化）
        for _, content in self._sent_contents:
            if len(content) >= 3 and text_stripped.startswith(content[:3]):
                return True
        return False

    # ============================================================
    # 兼容 wxauto 的公共接口
    # ============================================================

    def AddListenChat(self, who):
        """
        添加监听的群（不打开独立窗口，仅记录群名）
        用户需要手动把该群聊放在微信主窗口最前面
        """
        if who in self._listen_groups:
            logger.info(f"已在监听列表中: {who}")
            return

        self._listen_groups[who] = None  # watermark = None 表示首次扫描
        logger.info(f"已添加监听: {who}")

        # 检查当前是否已经在该群
        current = self._get_current_chat_name()
        if current and who in current:
            logger.info(f"当前主窗口已在 [{who}]")
        else:
            # 尝试通过会话列表切换
            if not self._switch_to_group(who):
                logger.warning(
                    f"请手动将 [{who}] 群聊窗口放在微信最前面！"
                    f" 当前显示: {current or '未知'}"
                )

    def add_listen_chat(self, who):
        """小写别名"""
        self.AddListenChat(who)

    def GetListenMessage(self):
        """
        获取监听群的新消息
        直接从主窗口的 chat_message_list 读取
        返回: {ChatWindow: [Message, ...]}
        """
        WATERMARK_SIZE = 5
        result = {}

        # 检查当前聊天
        current_chat = self._get_current_chat_name()
        if not current_chat:
            logger.debug("无法获取当前聊天名")
            return result

        # 找到匹配的监听群
        matched_group = None
        for group_name in self._listen_groups:
            if group_name in current_chat:
                matched_group = group_name
                break

        if not matched_group:
            # 当前不在任何监听群中
            logger.debug(f"当前聊天 [{current_chat}] 不在监听列表中")
            return result

        # 读取消息
        all_messages = self._read_messages()
        if not all_messages:
            return result

        # 过滤掉 sys 和 self 类型，只保留 friend
        friend_messages = [m for m in all_messages if m.type == "friend"]
        if not friend_messages:
            return result

        # 构建指纹: (sender, content) 元组列表
        current_fingerprints = [
            (m.sender or "", m.content.strip()) for m in friend_messages
        ]

        # 获取水印
        watermark = self._listen_groups.get(matched_group)

        if watermark is None:
            # 首次扫描，记录水印但不返回消息
            self._listen_groups[matched_group] = current_fingerprints[-WATERMARK_SIZE:]
            logger.info(f"{matched_group}: 首次扫描，记录水印（{len(current_fingerprints)}条消息）")
            return result

        # 检测新消息
        new_messages = []

        if watermark:
            last_wm_item = watermark[-1]
            found_pos = -1

            # 从后往前找水印最后一条
            for i in range(len(current_fingerprints) - 1, -1, -1):
                if current_fingerprints[i] == last_wm_item:
                    # 验证连续匹配
                    match_count = 0
                    for j in range(min(len(watermark), i + 1)):
                        wm_idx = len(watermark) - 1 - j
                        cur_idx = i - j
                        if cur_idx >= 0 and current_fingerprints[cur_idx] == watermark[wm_idx]:
                            match_count += 1
                        else:
                            break
                    if match_count >= min(2, len(watermark)):
                        found_pos = i
                        break
                    elif match_count >= 1 and len(watermark) == 1:
                        found_pos = i
                        break

            if found_pos >= 0 and found_pos < len(current_fingerprints) - 1:
                for i in range(found_pos + 1, len(current_fingerprints)):
                    new_messages.append(friend_messages[i])
            elif found_pos < 0:
                # 水印未找到，保守取最后1条
                if current_fingerprints[-1] != watermark[-1]:
                    new_messages = [friend_messages[-1]]
                    logger.debug(f"{matched_group}: 水印未找到，回退取最后1条")

        # 更新水印
        self._listen_groups[matched_group] = current_fingerprints[-WATERMARK_SIZE:]

        if new_messages:
            logger.info(f"{matched_group}: 检测到 {len(new_messages)} 条新消息")
            for msg in new_messages:
                sender_info = f"[{msg.sender}]" if msg.sender else "[未知发送者]"
                logger.info(f"  -> {sender_info} {msg.content[:60]}")
            result[_SimpleChatWindow(matched_group)] = new_messages

        return result

    def get_listen_message(self):
        """小写别名"""
        return self.GetListenMessage()

    def SendMsg(self, msg, who=None, clear=True, at=None):
        """
        发送消息到指定群
        Args:
            msg: 消息文本
            who: 发送目标（群名）
        """
        with self._send_lock:
            target = who or (list(self._listen_groups.keys())[0] if self._listen_groups else None)
            if not target:
                logger.error("无法确定发送目标")
                return

            try:
                # 确保目标群在主窗口显示
                current = self._get_current_chat_name()
                if not current or target not in current:
                    if not self._switch_to_group(target):
                        logger.error(f"无法切换到 [{target}]，发送失败")
                        return

                self._main_window.set_focus()
                time.sleep(0.2)

                # 查找输入框（兼容 3.9.x 和 4.x）
                input_edit = None
                if self._wx_version == '3.9':
                    # 3.9.x: 尝试多个可能的输入框 ID
                    for aid in ["41045", "ChatInputEditor", "input_box"]:
                        try:
                            ie = self._main_window.child_window(
                                auto_id=aid, control_type="Edit"
                            )
                            if ie.exists(timeout=0.5):
                                input_edit = ie
                                break
                        except Exception:
                            continue
                    # 备用：按 ClassName 查找
                    if not input_edit:
                        try:
                            ie = self._main_window.EditControl(ClassName="ChatContactMenu")
                            if ie.exists(timeout=0.5):
                                input_edit = ie
                        except Exception:
                            pass
                else:
                    # 4.x: chat_input_field
                    try:
                        input_edit = self._main_window.child_window(
                            auto_id="chat_input_field", control_type="Edit"
                        )
                        if not input_edit.exists(timeout=1.0):
                            input_edit = None
                    except Exception:
                        input_edit = None

                if input_edit:
                    input_edit.click_input()
                    time.sleep(0.2)
                else:
                    logger.warning("未找到输入框，尝试直接输入")

                # 通过剪贴板输入
                self._type_text_via_clipboard(msg)
                time.sleep(0.2)

                # 回车发送
                send_keys("{ENTER}", pause=0.05)
                logger.info(f"消息已发送: [{target}] -> {msg[:30]}")

                # 记录已发送消息（用于识别自己发的消息）
                self._sent_contents.append((time.time(), msg.strip()))
                now = time.time()
                self._sent_contents = [(t, c) for t, c in self._sent_contents if now - t < 60]

            except Exception as e:
                logger.error(f"发送消息失败 [{target}]: {e}")
                raise

    def send_msg(self, text, who=None):
        """小写别名"""
        self.SendMsg(text, who=who)


def check_pwa_available():
    """检查 pywinauto 是否可用"""
    return HAS_PYWINAUTO
