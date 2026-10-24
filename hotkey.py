# -*- coding: utf-8 -*-
"""全局热键(仅 Windows):ctypes RegisterHotKey,零依赖。

后台线程注册热键并跑消息循环;主线程通过队列接收 "toggle",
用 stop()(PostThreadMessage WM_QUIT)安全换键或退出。
"""
import ctypes
import ctypes.wintypes as wt
import queue
import threading

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

_VK = {
    "space": 0x20, "tab": 0x09, "esc": 0x1B, "enter": 0x0D,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
}
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    _VK[_ch] = ord(_ch)

HOTKEY_OPTIONS = ["Ctrl+Alt+Space", "Ctrl+Alt+T", "Ctrl+Alt+D", "Ctrl+Shift+T", "Ctrl+Alt+Z"]


def parse_accel(accel):
    """'Ctrl+Alt+T' -> (mods, vk);不支持返回 None。"""
    if not accel:
        return None
    mods = 0
    vk = None
    for part in str(accel).split("+"):
        p = part.strip().lower()
        if p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p == "alt":
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p in _VK:
            vk = _VK[p]
        else:
            return None
    if vk is None or not (mods & (MOD_CONTROL | MOD_ALT | MOD_SHIFT)):
        return None
    return mods | MOD_NOREPEAT, vk


class HotkeyController:
    def __init__(self):
        self.q = queue.Queue()
        self._thread = None

    def start(self, accel):
        """返回 True 注册成功,False 失败(比如被别的程序占用)。"""
        self.stop()
        parsed = parse_accel(accel)
        if not parsed:
            return False
        self._thread = threading.Thread(target=self._run, args=parsed, daemon=True)
        self._thread.start()
        try:
            first = self.q.get(timeout=1.0)
        except queue.Empty:
            return False
        return first == "ok"

    def stop(self):
        t = self._thread
        self._thread = None
        if t and t.is_alive():
            try:
                ctypes.windll.kernel32.PostThreadMessageW(t.ident, WM_QUIT, 0, 0)
                t.join(timeout=1.5)
            except Exception:
                pass

    def _run(self, mods, vk):
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, 1, mods, vk):
            self.q.put("fail")
            return
        self.q.put("ok")
        msg = wt.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self.q.put("toggle")
        finally:
            user32.UnregisterHotKey(None, 1)
