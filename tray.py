# -*- coding: utf-8 -*-
"""系统托盘图标(仅 Windows,ctypes 零依赖)。

后台线程创建 message-only 窗口接收托盘回调:
    左键单击        -> 队列 "toggle"(显示/悬浮切换)
    右键菜单        -> 显示/隐藏 或 退出
explorer 重启(任务栏崩溃)后自动重新挂载图标。
"""
import ctypes
import queue
import threading
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

# 64 位下指针型参数必须声明类型,否则回调里再传参会溢出
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT,
                                  ctypes.c_long, ctypes.c_long,
                                  ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
user32.TrackPopupMenu.restype = wintypes.BOOL
user32.LoadImageW.restype = wintypes.HANDLE

WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_APP = 0x8000
WM_LBUTTONUP = 0x0203
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0206
WM_CONTEXTMENU = 0x007B

NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10
TPM_RETURNCMD = 0x0100
MF_SEPARATOR = 0x0800
SM_CXSMICON, SM_CYSMICON = 49, 50
IDI_APPLICATION = 32512

TRAY_MSG = WM_APP + 1


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_ubyte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class TrayIcon:
    """用法:TrayIcon("todo.ico");事件从 .q 取("toggle"/"quit")。"""

    def __init__(self, icon_path, tip="待办"):
        self.q = queue.Queue()
        self.tip = tip
        self.icon_path = icon_path
        self.ok = False          # 图标是否成功挂上
        self.hwnd = None
        self._proc_ref = WNDPROC(self._wndproc)   # 防止回调被 GC
        self._taskbar_created = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ---------------- 运行在托盘线程 ----------------

    def _run(self):
        cls_name = "TodoAppTrayWnd"
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(self._proc_ref, ctypes.c_void_p).value
        wc.hInstance = hinst
        wc.lpszClassName = cls_name
        if not user32.RegisterClassW(ctypes.byref(wc)):
            return
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        hwnd = user32.CreateWindowExW(0, cls_name, cls_name, 0,
                                      0, 0, 0, 0, wintypes.HWND(-3), None,
                                      hinst, None)   # HWND_MESSAGE 消息窗口
        if not hwnd:
            return
        self.hwnd = hwnd
        # explorer 可能尚未就绪(如开机自启),重试挂载
        for _ in range(6):
            if self._add_icon(hwnd):
                self.ok = True
                break
            time.sleep(1.0)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self.hwnd = None

    def _load_icon(self):
        size = max(16, user32.GetSystemMetrics(SM_CXSMICON))
        hicon = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, size, size,
                                  LR_LOADFROMFILE)
        if not hicon:   # 图标文件丢失时用系统默认
            hicon = user32.LoadIconW(None, wintypes.LPCWSTR(IDI_APPLICATION))
        return hicon

    def _add_icon(self, hwnd):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = TRAY_MSG
        nid.hIcon = self._load_icon()
        nid.szTip = self.tip
        return bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))

    def _del_icon(self, hwnd):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == TRAY_MSG:
            if lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self.q.put("toggle")
            elif lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._popup_menu(hwnd)
            return 0
        if msg == self._taskbar_created:
            self._add_icon(hwnd)     # explorer 重启后重挂
            return 0
        if msg == WM_DESTROY:
            self._del_icon(hwnd)
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _popup_menu(self, hwnd):
        hmenu = user32.CreatePopupMenu()
        user32.AppendMenuW(hmenu, 0, 1, "显示 / 隐藏待办")
        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(hmenu, 0, 2, "退出")
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(hwnd)   # 让菜单在点击别处时能收起
        cmd = user32.TrackPopupMenu(hmenu, TPM_RETURNCMD, pt.x, pt.y, 0, hwnd, None)
        user32.DestroyMenu(hmenu)
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        if cmd == 1:
            self.q.put("toggle")
        elif cmd == 2:
            self.q.put("quit")

    # ---------------- 主线程调用 ----------------

    def stop(self):
        hwnd = self.hwnd
        if hwnd:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        self._thread.join(timeout=2)
