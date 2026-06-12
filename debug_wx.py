# -*- coding: utf-8 -*-
"""
微信窗口诊断工具 - 强力版
尝试多种方式找到微信窗口
"""
import sys
import time
import subprocess

try:
    from pywinauto import Application, Desktop
except ImportError:
    print("请先安装 pywinauto: pip install pywinauto")
    sys.exit(1)


def check_wechat_running():
    """检查微信进程是否运行"""
    try:
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5
        )
        
        # 在 CSV 格式输出中查找 WeChat
        wechat_found = False
        for line in result.stdout.split('\n'):
            if 'wechat' in line.lower() or 'WeChat' in line:
                wechat_found = True
                # 提取进程名和PID
                parts = line.replace('"', '').split(',')
                if len(parts) >= 2:
                    print(f"✓ 微信进程运行中: {parts[0]} (PID: {parts[1]})")
                break
        
        if wechat_found:
            return True
        else:
            # 使用 PowerShell 备选方案
            try:
                result2 = subprocess.run(
                    ["powershell", "-command", 
                     "Get-Process | Where-Object {$_.ProcessName -like '*wechat*' -or $_.ProcessName -like '*WeChat*'} | Select-Object Name,Id"],
                    capture_output=True, text=True, timeout=5
                )
                if 'wechat' in result2.stdout.lower() or 'WeChat' in result2.stdout:
                    print(f"✓ 微信进程运行中 (PowerShell检测)")
                    print(result2.stdout.strip())
                    return True
                else:
                    print("⚠ 未检测到微信进程，但仍会尝试连接窗口...")
                    return None
            except:
                print("⚠ 进程检查失败，继续尝试连接窗口...")
                return None
                
    except Exception as e:
        print(f"检查进程失败: {e}")
        print("继续尝试连接窗口...")
        return None


def find_wechat_windows():
    """查找所有微信相关窗口"""
    print("\n--- 查找所有窗口 ---")
    
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        
        # 获取所有顶级窗口
        windows = desktop.windows()
        print(f"系统共有 {len(windows)} 个窗口")
        
        wechat_windows = []
        for w in windows:
            try:
                title = w.window_text()
                class_name = w.element_info.class_name or ""
                
                # 检查是否是微信相关窗口
                if any(kw in title.lower() for kw in ["微信", "wechat"]) or \
                   any(kw in class_name.lower() for kw in ["wechat", "chrome_widget"]):
                    print(f"\n找到微信相关窗口:")
                    print(f"  标题: \"{title}\"")
                    print(f"  类名: {class_name}")
                    print(f"  可见: {w.is_visible()}")
                    print(f"  最小化: {w.is_minimized()}")
                    wechat_windows.append(w)
            except:
                continue
        
        if not wechat_windows:
            print("\n未找到微信相关窗口")
            print("\n所有窗口列表:")
            for i, w in enumerate(windows[:30]):  # 只显示前30个
                try:
                    title = w.window_text()[:30] if w.window_text() else ""
                    class_name = w.element_info.class_name or ""
                    if title or class_name:
                        print(f"  [{i}] \"{title}\" ({class_name})")
                except:
                    continue
        
        return wechat_windows
        
    except Exception as e:
        print(f"查找窗口失败: {e}")
        return []


def try_connect_methods():
    """尝试多种连接方法"""
    print("\n--- 尝试多种连接方式 ---")
    
    methods = [
        ("类名 Chrome_WidgetWin_0", {"class_name": "Chrome_WidgetWin_0"}),
        ("类名 WeChatMainWndForPC", {"class_name": "WeChatMainWndForPC"}),
        ("标题包含'微信'", {"title_re": ".*微信.*"}),
        ("标题包含'WeChat'", {"title_re": ".*WeChat.*"}),
        ("标题='微信'", {"title": "微信"}),
    ]
    
    app = None
    main_window = None
    
    for name, params in methods:
        print(f"\n尝试: {name}")
        try:
            app = Application(backend="uia").connect(**params, timeout=3)
            if params.get("title_re"):
                main_window = app.window(**params)
            else:
                main_window = app.window(**params)
            
            if main_window.exists():
                print(f"  ✓ 成功！")
                print(f"  窗口标题: {main_window.window_text()}")
                print(f"  窗口类名: {main_window.element_info.class_name}")
                return app, main_window
            else:
                print(f"  ✗ 窗口不存在")
        except Exception as e:
            print(f"  ✗ 失败: {str(e)[:50]}")
    
    return None, None


def analyze_window(window, max_depth=3):
    """分析窗口控件结构"""
    print("\n" + "=" * 60)
    print("窗口控件树")
    print("=" * 60)
    
    def print_children(wrapper, depth=0):
        if depth > max_depth:
            return
        
        indent = "  " * depth
        try:
            name = wrapper.window_text()[:40] if wrapper.window_text() else ""
            ctrl_type = wrapper.element_info.control_type or "?"
            auto_id = wrapper.element_info.automation_id or ""
            
            info = f"{indent}[{ctrl_type}]"
            if name:
                info += f' "{name}"'
            if auto_id:
                info += f" (auto_id={auto_id})"
            
            print(info)
            
            for child in wrapper.children():
                print_children(child, depth + 1)
                
        except Exception as e:
            print(f"{indent}[Error]")
    
    print_children(window, 0)
    
    # 查找特定控件
    print("\n--- 查找 List 控件 ---")
    try:
        lists = window.descendants(control_type="List")
        if lists:
            for i, lst in enumerate(lists[:5]):
                name = lst.window_text()[:20] if lst.window_text() else ""
                auto_id = lst.element_info.automation_id or ""
                count = len(lst.children())
                print(f"  List {i+1}: \"{name}\" auto_id={auto_id} 子项={count}")
        else:
            print("  未找到 List 控件")
    except Exception as e:
        print(f"  查找失败: {e}")
    
    print("\n--- 查找 Edit 控件 ---")
    try:
        edits = window.descendants(control_type="Edit")
        if edits:
            for i, edit in enumerate(edits[:5]):
                name = edit.window_text()[:20] if edit.window_text() else ""
                auto_id = edit.element_info.automation_id or ""
                print(f"  Edit {i+1}: \"{name}\" auto_id={auto_id}")
        else:
            print("  未找到 Edit 控件")
    except Exception as e:
        print(f"  查找失败: {e}")


def main():
    print("微信窗口诊断工具")
    print("=" * 60)
    
    # 检查微信进程
    print("\n[步骤1] 检查微信进程...")
    wechat_status = check_wechat_running()
    if wechat_status == False:
        print("\n请先启动微信并登录！")
        return
    
    # 查找窗口
    print("\n[步骤2] 查找微信窗口...")
    wechat_windows = find_wechat_windows()
    
    # 尝试连接
    print("\n[步骤3] 尝试连接微信...")
    app, main_window = try_connect_methods()
    
    if main_window:
        # 分析窗口
        print("\n[步骤4] 分析窗口结构...")
        
        # 如果窗口最小，先恢复
        try:
            if main_window.is_minimized():
                main_window.restore()
            main_window.set_focus()
            time.sleep(0.5)
        except:
            pass
        
        analyze_window(main_window, max_depth=4)
    else:
        print("\n" + "=" * 60)
        print("无法连接到微信窗口！")
        print("=" * 60)
        print("\n可能的原因:")
        print("1. 微信未启动或未登录")
        print("2. 微信窗口被最小化到系统托盘")
        print("3. 微信版本不兼容")
        print("\n解决方法:")
        print("1. 启动微信并登录")
        print("2. 确保微信窗口可见（从任务栏点击微信图标）")
        print("3. 不要最小化到托盘")


if __name__ == "__main__":
    print("请确保微信已打开并登录...")
    time.sleep(2)
    main()
    print("\n完成！将以上输出发给我。")
