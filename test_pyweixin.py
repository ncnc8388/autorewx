import sys
import os

# Add pyweixin path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'pywechat-main'))

try:
    import pyweixin
    print("✓ pyweixin 导入成功")
    print(f"  路径: {pyweixin.__file__}")
    
    from pyweixin import Navigator, Monitor, Messages
    print("✓ Navigator, Monitor, Messages 导入成功")
    
    # Check if Monitor has listen_on_chat
    if hasattr(Monitor, 'listen_on_chat'):
        print("✓ Monitor.listen_on_chat 方法存在")
    else:
        print("✗ Monitor.listen_on_chat 方法不存在")
        print(f"  Monitor 方法: {[m for m in dir(Monitor) if not m.startswith('_')]}")
        
except Exception as e:
    print(f"✗ 错误: {e}")
    import traceback
    traceback.print_exc()
