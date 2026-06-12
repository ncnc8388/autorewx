# -*- coding: utf-8 -*-
"""
深度探测微信消息控件结构
查找发送者信息可能存在的位置
"""
import sys
import time

try:
    from pywinauto import Application
except ImportError:
    print("请安装 pywinauto")
    sys.exit(1)


def explore_message_controls():
    print("=" * 60)
    print("微信消息控件深度探测")
    print("=" * 60)
    print()
    print("请确保已打开群聊天窗口，并有一些消息")
    input("按回车继续...")
    
    try:
        # 连接微信
        print("\n连接微信...")
        app = Application(backend="uia").connect(
            class_name="mmui::MainWindow",
            timeout=10
        )
        main_window = app.window(class_name="mmui::MainWindow")
        print("✓ 连接成功")
        
        # 查找消息列表
        msg_list = main_window.child_window(
            auto_id="chat_message_list",
            control_type="List"
        )
        
        if not msg_list.exists(timeout=1):
            print("✗ 未找到消息列表")
            return
        
        print(f"✓ 找到消息列表")
        
        # 获取所有消息
        children = msg_list.children()
        print(f"共 {len(children)} 条消息\n")
        
        # 详细分析每条消息
        for i, child in enumerate(children[:5]):  # 只分析前5条
            text = child.window_text()
            print(f"\n{'='*50}")
            print(f"消息 {i+1}: {text[:40]}")
            print(f"{'='*50}")
            
            # 打印控件基本信息
            print(f"  控件类型: {child.element_info.control_type}")
            print(f"  auto_id: {child.element_info.automation_id}")
            print(f"  class_name: {child.element_info.class_name}")
            
            # 递归打印所有子控件（最多3层）
            def print_all_descendants(wrapper, depth=0, max_depth=3):
                if depth > max_depth:
                    return
                indent = "    " + "  " * depth
                try:
                    sub_text = wrapper.window_text()[:30] if wrapper.window_text() else ""
                    sub_type = wrapper.element_info.control_type
                    sub_aid = wrapper.element_info.automation_id or ""
                    sub_cls = wrapper.element_info.class_name or ""
                    
                    info = f"{indent}[{sub_type}]"
                    if sub_text:
                        info += f' "{sub_text}"'
                    if sub_aid:
                        info += f" aid={sub_aid}"
                    if sub_cls and sub_cls != sub_type:
                        info += f" cls={sub_cls}"
                    
                    print(info)
                    
                    for sub_child in wrapper.children():
                        print_all_descendants(sub_child, depth + 1, max_depth)
                except:
                    pass
            
            print("\n  所有子控件（深度3层）:")
            print_all_descendants(child, 0, 3)
        
        print(f"\n{'='*50}")
        print("探测完成!")
        print("\n请将完整输出发给我，我会分析发送者信息是否存在。")
        
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    explore_message_controls()
