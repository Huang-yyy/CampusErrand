# -*- coding: utf-8 -*-
"""CampusErrand 一键启动器:检测端口 -> 延时开浏览器 -> 跑 uvicorn 服务。"""
import os
import sys
import socket
import threading
import time
import webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)

HOST, PORT = "127.0.0.1", 8000
URL = f"http://{HOST}:{PORT}/"


def port_open(host=HOST, port=PORT):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def open_browser_later():
    time.sleep(2.5)
    webbrowser.open(URL)


if port_open():
    print("跑腿平台服务已经在运行,直接为你打开网页...")
    webbrowser.open(URL)
    time.sleep(1.5)
    sys.exit(2)  # 退出码 2 = 已在运行,启动器窗口直接关闭

print("=" * 50)
print("  CampusErrand 校园代跑悬赏平台 正在启动...")
print("  浏览器会自动打开,请勿关闭本窗口。")
print("  关闭这个黑窗口 = 停止服务。")
print("=" * 50)

threading.Thread(target=open_browser_later, daemon=True).start()

from app.db import init_db
init_db()

import uvicorn
uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=False)
