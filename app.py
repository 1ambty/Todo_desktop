# -*- coding: utf-8 -*-
"""待办 —— 入口。

用法:
    pythonw app.py            普通启动(悬浮窗)
    pythonw app.py --hidden   静默启动(仅后台,用热键 Ctrl+Alt+T 呼出)
    pythonw app.py --selftest 构建自检(不出窗口)
"""
import ctypes
import datetime
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MUTEX_NAME = "TodoApp.SingleInstance.Mutex"


def install_crash_log():
    """pythonw 没有控制台,未捕获异常落到 data/error.log 便于排查。"""
    def hook(t, v, tb):
        try:
            log = os.path.join(APP_DIR, "data", "error.log")
            os.makedirs(os.path.dirname(log), exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write("\n[%s]\n" % datetime.datetime.now().isoformat())
                import traceback
                traceback.print_exception(t, v, tb, file=f)
        except Exception:
            pass
    sys.excepthook = hook


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def second_instance_signal():
    """已有实例在跑:写 .show 信号文件让旧实例显示窗口,然后退出。"""
    data_dir = os.path.join(APP_DIR, "data")
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, ".show"), "w") as f:
            f.write("show")
    except Exception:
        pass


def acquire_single_instance():
    ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def main():
    enable_dpi_awareness()
    install_crash_log()
    if not acquire_single_instance():
        second_instance_signal()
        return

    import tkinter as tk
    from store import Store
    from hotkey import HotkeyController
    from tray import TrayIcon
    from ui import TodoApp

    store = Store()
    root = tk.Tk()
    root.withdraw()
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass

    hk = HotkeyController()
    tray = TrayIcon(os.path.join(APP_DIR, "todo.ico"),
                    tip="待办 · 左键显示/隐藏,右键菜单")
    app = TodoApp(root, store, start_hidden="--hidden" in sys.argv,
                  hotkey_ctl=hk, tray_q=tray.q)
    app.tray = tray

    # 默认热键被其他软件占用时,自动改用第一个可注册的候选键
    import hotkey as hk_mod
    cur = store.settings.get("hotkey", "Ctrl+Alt+Space")
    ok = hk.start(cur)
    if not ok:
        for opt in hk_mod.HOTKEY_OPTIONS:
            if opt == cur:
                continue
            if hk.start(opt):
                store.settings["hotkey"] = opt
                store.save_later()
                ok = True
                app.root.after(900, lambda o=opt: app.toast(
                    "默认热键被占用,已自动改用 %s(可在设置中更换)" % o, seconds=5))
                break
    app.hotkey_ok = ok

    def on_close():
        hk.stop()
        store.flush_if_dirty()
        app._save_window_cfg()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    hk.stop()


def selftest():
    """无头自检:构建 UI、模拟常用操作,验证不抛异常。"""
    import tempfile
    os.environ["TODO_DATA_DIR"] = tempfile.mkdtemp(prefix="todo-test-")
    enable_dpi_awareness()
    import tkinter as tk
    from store import Store, today_str, due_overdue
    from ui import TodoApp, due_label, iso_after

    store = Store()
    t1 = store.add("写周报", due=today_str(), priority=2)
    store.add("喝水", daily=True)
    store.add("过期任务", due="2020-01-01")
    store.add("已完成项", priority=1)
    store.toggle(store.tasks[-1]["id"])
    store.add("被删的", notes="备注内容")
    store.delete(store.tasks[-1]["id"])

    root = tk.Tk()
    root.withdraw()
    app = TodoApp(root, store, start_hidden=True)
    for i in range(20):
        root.update()

    # 合成点击事件只送达"已映射"的窗口:以全透明+屏幕外方式映射
    root.geometry("+3200+100")
    root.deiconify()
    try:
        root.attributes("-alpha", 0.0)
    except Exception:
        pass
    for i in range(10):
        root.update()

    # 模拟交互
    app.state["tab"] = "all"; app.draw(); root.update()
    app.state["tab"] = "done"; app.draw(); root.update()
    app.state["tab"] = "trash"; app.draw(); root.update()
    app.state["tab"] = "today"; app.draw(); root.update()
    app.open_edit(t1); root.update()
    app.handle_edit_btn("cancel"); root.update()
    app.state["modal"] = "settings"; app.draw(); root.update()
    app.state["sm_scroll"] = 200; app.draw(); root.update()
    app.close_modal(); root.update()
    for theme in [t["id"] for t in app._themes_cache]:
        app.apply_theme(theme); root.update()
    app.apply_theme("sage")
    # 皮肤脚本:圆形时钟应绑定 draw 钩子并改窗体;切回后完全卸载
    assert "clock" in [t["id"] for t in app._themes_cache], "皮肤主题未被扫描到"
    app.apply_theme("clock")
    assert app.skin == "clock" and "draw_surface" in app._skin_bound, "皮肤钩子未绑定"
    assert app.win_radius == 180, "皮肤未生效窗体形状"
    for i in range(10):
        root.update()
    app.apply_theme("sage")
    assert app.skin is None and app.win_radius == 16 and not app._skin_bound, \
        "皮肤未完全卸载"
    for i in range(10):
        root.update()
    # 时钟皮肤把窗口改小过,恢复默认尺寸,保证后续点击用例的列表可视范围
    app.set_window_shape(w=360, h=620)
    root.update()
    app.store.toggle(store.get(t1["id"])["id"])  # 打勾
    app.draw(); root.update()
    app.toast("测试提示", action=("del", 9999)); root.update()
    app.state["search_open"] = True; app.draw(); root.update()
    app.state["search_open"] = False; app.draw(); root.update()
    for i in range(10):
        root.update()
    store.flush_if_dirty()

    # 数据完整性
    assert store.get(t1["id"])["done"] is True
    assert len(store.trash()) == 1
    dn, total = store.today_progress()
    assert total >= 3, "今日进度统计异常"

    # ---- 合成点击走真实交互链路 ----
    def click_tag(tag, expect=None):
        items = app.canvas.find_withtag(tag)
        if not items:
            print("  [click] 目标不存在:", tag)
            return False
        x1, y1, x2, y2 = app.canvas.bbox(items[0])
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        picked = app._pick(cx, cy)
        if expect and picked != expect:
            print("  [click] 命中不符: 想点 %s, 实际 %s @(%d,%d)" % (tag, picked, cx, cy))
        app.canvas.event_generate("<Button-1>", x=cx, y=cy)
        app.canvas.event_generate("<ButtonRelease-1>", x=cx, y=cy)
        root.update()
        return True

    app.state["tab"] = "today"
    app.draw()
    root.update()
    # 找一个未完成普通任务的勾选框点一下
    todo_row = next(t for t in store.tasks
                    if not t["deleted"] and not t["daily"] and not t["done"])
    assert click_tag("task:%d:check" % todo_row["id"]), "找不到勾选框"
    assert store.get(todo_row["id"])["done"], "点击勾选未生效"
    # 再点一下取消
    click_tag("task:%d:check" % todo_row["id"])
    assert not store.get(todo_row["id"])["done"], "取消勾选未生效"
    # 截止日历:点"截止"芯片 → 日历选今天 → 分钟+5 → 确定 → 添加任务带 "今天 09:05"
    app.quick["due"] = None
    assert click_tag("chip:quick-due"), "找不到截止芯片"
    assert app.popover and app.popover["kind"] == "calendar", "日历未打开"
    assert app.pop_rect[3] < app.layout["composer"][1] + app.m(40), "日历压到输入区"
    assert click_tag("pop:cal-day-" + today_str()), "日历日期格缺失"
    assert click_tag("pop:cal-min-up"), "分钟步进缺失"
    assert click_tag("pop:cal-ok"), "确定按钮缺失"
    expect_due = "%s 09:05" % today_str()
    assert app.popover is None and app.quick["due"] == expect_due, "日历选择未生效"
    app._entry_placeholder = False
    app.entry.delete(0, "end")
    app.entry.insert(0, "带截止任务")
    app.add_quick()
    added = next(t for t in store.tasks if t["title"] == "带截止任务")
    assert added["due"] == expect_due, "截止日期没有落到任务上"
    assert due_label(added["due"]) == "今天 09:05", "截止显示未带时间"
    # 逾期判断:纯日期看整天,带时刻看具体时间
    assert due_overdue("2000-01-01") is True, "过去日期未被判定逾期"
    assert due_overdue("2000-01-01 23:59") is True, "过去时刻未被判定逾期"
    assert due_overdue(iso_after(1)) is False, "明天被误判逾期"
    assert due_overdue(iso_after(1) + " 00:00") is False, "明天时刻被误判逾期"
    app.quick["due"] = None
    # 点选项卡
    assert click_tag("tab:all") and app.state["tab"] == "all", "选项卡点击未生效"
    # 打开设置,点主题卡
    app.state["modal"] = "settings"
    app.draw()
    root.update()
    assert click_tag("theme:mist") and store.settings["theme"] == "mist", "主题切换未生效"
    app.apply_theme("sage")
    app.close_modal()
    root.update()
    # 底部输入框加任务
    app._entry_placeholder = False
    app.entry.delete(0, "end")
    app.entry.insert(0, "自检新增任务")
    app.add_quick()
    assert any(t["title"] == "自检新增任务" for t in store.tasks), "快速添加未生效"

    # 回归:异形皮肤下必须能打开设置并切回普通主题(皮肤 draw 不得吞掉弹窗层)
    app.apply_theme("clock")
    for i in range(8):
        root.update()
    app.state["modal"] = "settings"
    app.draw()
    root.update()
    assert app.state["modal"] == "settings" and click_tag("theme:sage"), \
        "时钟皮肤下设置/主题卡不可用"
    assert app.skin is None and app.win_radius == 16, "时钟下无法切回普通主题"
    # 重置窗口:大小+位置一起恢复默认(按钮在面板下部,先滚下去)
    app.set_window_shape(radius=60, w=420, h=520)
    app.state["modal"] = "settings"
    app.state["sm_scroll"] = 320
    app.draw()
    root.update()
    assert click_tag("act:sm-resetwin", expect="act:sm-resetwin"), "重置按钮不可用"
    assert app.geo["w"] == 360 and app.geo["h"] == 620, "窗口重置未生效"
    app.apply_theme("sage")
    app.close_modal()
    root.update()

    root.destroy()
    print("SELFTEST PASS: 主题 %d 个,任务 %d 项,今日进度 %d/%d,交互链路 OK"
          % (len(app._themes_cache), len(store.tasks), dn, total))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
