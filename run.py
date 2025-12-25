#!/usr/bin/env python
"""
Windows 启动脚本
确保在导入任何模块之前设置正确的事件循环策略
"""
import sys
import platform
import asyncio

# 必须在导入任何其他模块之前设置事件循环策略
if platform.system() == "Windows":
    if sys.version_info >= (3, 8):
        # 使用 ProactorEventLoop 以支持 Playwright 的子进程需求
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        print("✅ 已设置 Windows 事件循环策略: WindowsProactorEventLoopPolicy")

# 现在可以安全地导入应用
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

