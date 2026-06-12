# -*- coding: utf-8 -*-
"""
微信UI控件树诊断工具
用于查看微信4.1.10暴露给UIAutomation的控件结构
运行前请确保微信已打开并登录，窗口可见（不能最小化）
"""

import sys
import time


def find_wechat_window():
    """查找微信主窗口"""
    try:
        import uiautomation as uia
    except ImportError:
        print("请先安装 uiautomation: pip install uiautomation")
        sys.exit(1)

    # 尝试多种方式查找微信窗口
    print("=" * 60)
    print("正在查找微信窗口...")
    print("=" * 60)

    # 方式1: 按类名查找
    wechat = None
    for class_name in ["WeChatMainWndForPC", "Chrome_WidgetWin_0", "WeChatLoginWndForPC"]:
        try:
            wnd = uia.WindowControl(ClassName=class_name, searchDepth=1)
            if wnd.Exists(maxSearchSeconds=2):
                print(f"[找到] 类名={class_name}, 标题={wnd.Name}")
                wechat = wnd
                break
        except Exception:
            continue

    # 方式2: 按标题查找
    if not wechat:
        try:
            wnd = uia.WindowControl(Name="微信", searchDepth=1)
            if wnd.Exists(maxSearchSeconds=2):
                print(f"[找到] 标题=微信, 类名={wnd.ClassName}")
                wechat = wnd
        except Exception:
            pass

    # 方式3: 遍历所有顶级窗口
    if not wechat:
        print("\n未通过类名/标题找到微信，遍历所有窗口查找...")
        root = uia.GetRootControl()
        for child in root.GetChildren():
            name = child.Name or ""
            classname = child.ClassName or ""
            if "微信" in name or "wechat" in name.lower() or "WeChat" in classname:
                print(f"[可能匹配] 标题={name}, 类名={classname}")
                if not wechat:
                    wechat = child

    if not wechat:
        print("\n未找到微信窗口！请确保微信已打开并登录。")
        return None, None

    return wechat, uia


def print_control_tree(control, depth=0, max_depth=5):
    """递归打印控件树"""
    if depth > max_depth:
        return

    indent = "  " * depth
    ctrl_type = control.ControlTypeName
    name = control.Name or ""
    automation_id = control.AutomationId or ""
    class_name = control.ClassName or ""

    # 截断过长的名称
    if len(name) > 60:
        name = name[:60] + "..."

    info_parts = [f"[{ctrl_type}]"]
    if name:
        info_parts.append(f'名称="{name}"')
    if automation_id:
        info_parts.append(f'ID="{automation_id}"')
    if class_name:
        info_parts.append(f'类="{class_name}"')

    print(f"{indent}{' '.join(info_parts)}")

    try:
        for child in control.GetChildren():
            print_control_tree(child, depth + 1, max_depth)
    except Exception:
        pass


def find_edit_controls(control, results=None, depth=0, max_depth=8):
    """查找所有可编辑控件（输入框）"""
    if results is None:
        results = []
    if depth > max_depth:
        return results

    try:
        if control.ControlTypeName in ("EditControl", "TextControl"):
            results.append({
                "type": control.ControlTypeName,
                "name": control.Name or "",
                "automation_id": control.AutomationId or "",
                "class_name": control.ClassName or "",
                "depth": depth,
            })
    except Exception:
        pass

    try:
        for child in control.GetChildren():
            find_edit_controls(child, results, depth + 1, max_depth)
    except Exception:
        pass

    return results


def find_list_controls(control, results=None, depth=0, max_depth=8):
    """查找所有列表控件（消息列表、聊天列表等）"""
    if results is None:
        results = []
    if depth > max_depth:
        return results

    try:
        if control.ControlTypeName in ("ListControl", "DataControl"):
            results.append({
                "type": control.ControlTypeName,
                "name": control.Name or "",
                "automation_id": control.AutomationId or "",
                "class_name": control.ClassName or "",
                "depth": depth,
            })
    except Exception:
        pass

    try:
        for child in control.GetChildren():
            find_list_controls(child, results, depth + 1, max_depth)
    except Exception:
        pass

    return results


def main():
    print("微信 UI 控件树诊断工具")
    print("=" * 60)
    print("请确保：")
    print("  1. 微信已打开并登录")
    print("  2. 微信窗口可见（未最小化）")
    print("  3. 微信处于主聊天页面")
    print()

    wechat, uia = find_wechat_window()
    if not wechat:
        return

    print("\n" + "=" * 60)
    print("微信窗口基本信息")
    print("=" * 60)
    print(f"  标题: {wechat.Name}")
    print(f"  类名: {wechat.ClassName}")
    print(f"  进程ID: {wechat.ProcessId}")
    try:
        rect = wechat.BoundingRectangle
        print(f"  位置: ({rect.left}, {rect.top}) - ({rect.right}, {rect.bottom})")
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("控件树（最多5层深度）")
    print("=" * 60)
    print_control_tree(wechat, depth=0, max_depth=5)

    print("\n" + "=" * 60)
    print("可编辑控件（输入框候选）")
    print("=" * 60)
    edits = find_edit_controls(wechat)
    if edits:
        for i, e in enumerate(edits):
            print(f"  [{i}] 类型={e['type']}, 名称={e['name']}, "
                  f"ID={e['automation_id']}, 类={e['class_name']}, 深度={e['depth']}")
    else:
        print("  未找到可编辑控件")

    print("\n" + "=" * 60)
    print("列表控件（消息列表/聊天列表候选）")
    print("=" * 60)
    lists = find_list_controls(wechat)
    if lists:
        for i, l in enumerate(lists):
            print(f"  [{i}] 类型={l['type']}, 名称={l['name']}, "
                  f"ID={l['automation_id']}, 类={l['class_name']}, 深度={l['depth']}")
    else:
        print("  未找到列表控件")

    # 测试 wxauto4 能否连接
    print("\n" + "=" * 60)
    print("测试 wxauto4 连接")
    print("=" * 60)
    try:
        from wxauto4 import WeChat
        wx = WeChat()
        print("  wxauto4 连接成功！")
    except ImportError:
        print("  wxauto4 未安装")
    except Exception as e:
        print(f"  wxauto4 连接失败: {e}")

    # 测试 wxautox4 能否连接
    print("\n" + "=" * 60)
    print("测试 wxautox4 连接（付费版）")
    print("=" * 60)
    try:
        from wxautox4 import WeChat
        wx = WeChat()
        print("  wxautox4 连接成功！")
    except ImportError:
        print("  wxautox4 未安装（如需使用请: pip install wxautox4）")
    except Exception as e:
        print(f"  wxautox4 连接失败: {e}")

    print("\n" + "=" * 60)
    print("诊断完成")
    print("=" * 60)
    print("\n请将以上输出截图发给我，我可以根据控件结构适配连接方案。")


if __name__ == "__main__":
    main()
