# -*- coding: utf-8 -*-
"""
测试微信消息读取 - 详细版
"""
import sys
import time
import re

try:
    from pywinauto import Application
except ImportError:
    print("请安装 pywinauto")
    sys.exit(1)

def test_message_read():
    print("=" * 60)
    print("微信消息读取测试（详细版）")
    print("=" * 60)
    print()
    print("请确保已手动打开群聊天窗口")
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
        
        # 读取消息
        children = msg_list.children()
        print(f"共 {len(children)} 条消息\n")
        
        # 时间戳过滤
        time_pattern = re.compile(r'^(\d{1,2}:\d{2}|昨天|前天|星期\w|\d{1,2}月\d{1,2}日)$')
        
        for i, child in enumerate(children):
            text = child.window_text()
            
            # 过滤时间戳
            if time_pattern.match(text.strip()):
                print(f"[{i+1}] ⏰ 时间戳: {text}")
                continue
            
            print(f"[{i+1}] 📩 消息: {text[:50]}")
            
            # 查看子控件
            sub_children = child.children()
            if sub_children:
                print(f"    子控件 ({len(sub_children)} 个):")
                for j, sub in enumerate(sub_children[:5]):
                    sub_text = sub.window_text()[:30] if sub.window_text() else ""
                    sub_type = sub.element_info.control_type
                    sub_aid = sub.element_info.automation_id or ""
                    print(f"      [{j}] {sub_type}: \"{sub_text}\" (auto_id={sub_aid})")
            else:
                print("    无子控件")
            print()
        
        print("-" * 40)
        print("测试完成!")
        
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_message_read()
