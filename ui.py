# -*- coding: utf-8 -*-
"""待办 —— 悬浮窗 UI。

无边框透明窗(不在任务栏/Alt-Tab 显示),标题栏拖动,窗口八边拖拽缩放,
全部界面元素绘制在一张 Canvas 上,图标为矢量绘制,随主题换色。
"""
import datetime
import json
import os
import calendar
import time
import tkinter as tk
from tkinter import font as tkfont, filedialog

import theme_api
import hotkey as hk_mod
from store import today_str, due_overdue, WINDOW_FILE, DATA_DIR
from ui_widgets import (rrect, clamp, ic_search, ic_pin, ic_gear, ic_minus, ic_plus,
                        ic_repeat, ic_flag, ic_trash, ic_pencil, ic_restore, ic_x,
                        ic_sprout, ic_fire, ic_calendar, ic_chevron, ic_check,
                        checkbox, toggle, text_h)

TRANS_KEY = "#FE01FE"
WEEK_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
MIN_W, MIN_H, MAX_W, MAX_H = 300, 460, 1000, 1500

TAG_PREFIX = ("act", "task", "tab", "theme", "tgl", "hs", "chip", "pop",
              "sm", "em", "toast", "pb")


def due_label(due):
    if not due:
        return None
    time_part = ""
    try:
        if len(due) > 10:
            dt = datetime.datetime.fromisoformat(due)
            d, time_part = dt.date(), " %02d:%02d" % (dt.hour, dt.minute)
        else:
            d = datetime.date.fromisoformat(due)
    except Exception:
        return due
    today = datetime.date.today()
    diff = (d - today).days
    if diff == 0:
        label = "今天"
    elif diff == 1:
        label = "明天"
    elif diff == 2:
        label = "后天"
    elif 0 < diff <= 6:
        label = WEEK_CN[d.weekday()]
    elif d.year == today.year:
        label = "%d月%d日" % (d.month, d.day)
    else:
        label = "%d/%d/%d" % (d.year, d.month, d.day)
    return label + time_part


def iso_after(days):
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def next_weekday(target_wd):
    today = datetime.date.today()
    diff = (target_wd - today.weekday()) % 7
    if diff == 0:
        diff = 7
    return (today + datetime.timedelta(days=diff)).isoformat()


DUE_PRESETS = [
    ("今天", lambda: iso_after(0)),
    ("明天", lambda: iso_after(1)),
    ("后天", lambda: iso_after(2)),
    ("下周一", lambda: next_weekday(0)),
    ("下周六", lambda: next_weekday(5)),
    ("清除截止", lambda: None),
]


class TodoApp:
    def __init__(self, root, store, start_hidden=False, hotkey_ctl=None, tray_q=None):
        self.root = root
        self.store = store
        self.hk = hotkey_ctl
        self.tray_q = tray_q
        self.tray = None          # app.py 里赋值,退出时用来卸载图标
        self.hotkey_ok = True

        self._pick_font()
        self.scl = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self._mkfonts()

        self.T = theme_api.get_theme(store.settings.get("theme"))
        self.V = self.T["vars"]

        self.geo = self._load_window_cfg()
        self.state = dict(tab="today", search_open=False, show_done=True,
                          modal=None, toast=None,
                          hover_task=None, scroll=0, sm_scroll=0,
                          flash_input=False)
        self.popover = None
        self.pop_rect = None
        self._expanded = set()
        self.quick = dict(daily=False, due=None, pri=0,
                          list=store.settings.get("last_list") or "inbox")
        self.edit = None
        self.edit_title = None
        self.edit_notes = None
        self.prompt = None
        self.prompt_entry = None
        self._prompt_back = None
        self.drag = None
        self.drag_task = None
        self._drag_y = None
        self.drop_hint = None
        self.card_geo = {}
        self._today = today_str()
        self._themes_cache = theme_api.scan_themes()[0]

        root.overrideredirect(True)
        root.attributes("-transparentcolor", TRANS_KEY)
        root.configure(bg=TRANS_KEY)
        root.minsize(MIN_W, MIN_H)
        root.maxsize(MAX_W, MAX_H)

        self.canvas = tk.Canvas(root, bg=TRANS_KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.W = root.winfo_width()
        self.H = root.winfo_height()
        self.layout = {}

        # 常驻输入框(每次重绘重新嵌入 canvas)
        self.entry = tk.Entry(self.canvas, font=self.f_base, relief="flat",
                              highlightthickness=0, bd=0,
                              fg=self.V["muted"], insertbackground=self.V["ink"])
        self.entry.insert(0, "记点什么… Enter 添加")
        self._entry_placeholder = True
        self.entry.bind("<Return>", lambda e: self.add_quick())
        self.entry.bind("<FocusIn>", lambda e: self._ph_clear(self.entry, "entry"))
        self.entry.bind("<FocusOut>", lambda e: self._ph_restore(self.entry, "entry"))

        self.search_entry = tk.Entry(self.canvas, font=self.f_small, relief="flat",
                                     highlightthickness=0, bd=0,
                                     fg=self.V["muted"], insertbackground=self.V["ink"])
        self.search_entry.insert(0, "搜索待办…")
        self._search_placeholder = True
        self.search_entry.bind("<KeyRelease>", self._search_changed)
        self.search_entry.bind("<FocusIn>", lambda e: self._ph_clear(self.search_entry, "search"))
        self.search_entry.bind("<FocusOut>", lambda e: self._ph_restore(self.search_entry, "search"))

        self._bind_events()
        self._apply_geometry()
        if not start_hidden:
            root.deiconify()
        self._apply_topmost()
        self._apply_opacity()
        root.update_idletasks()
        self.W = root.winfo_width()
        self.H = root.winfo_height()
        self.draw()

        if not start_hidden and store.settings.get("notify_due"):
            root.after(700, self._notify_due_today)
        self.tick()

    # ---------------------------------------------------------------- 基础

    def m(self, v):
        return int(round(v * self.scl))

    def _pick_font(self):
        fams = set()
        try:
            fams = set(tkfont.families(self.root))
        except Exception:
            pass
        for f in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "SimHei"):
            if f in fams:
                self.font_family = f
                return
        self.font_family = tkfont.nametofont("TkDefaultFont").actual("family")

    def _mkfonts(self):
        fam = self.font_family

        def F(size, bold=False):
            return tkfont.Font(family=fam, size=size,
                               weight="bold" if bold else "normal")

        self.f_big = F(12, True)
        self.f_title = F(11, True)
        self.f_btn = F(10, True)
        self.f_base = F(10)
        self.f_small = F(9)
        self.f_tiny = F(8)

    def _load_window_cfg(self):
        cfg = dict(x=None, y=None, w=360, h=620, topmost=True, opacity=1.0)
        try:
            with open(WINDOW_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = int(clamp(cfg["w"], MIN_W, MAX_W))
        h = int(clamp(cfg["h"], MIN_H, MAX_H))
        x, y = cfg["x"], cfg["y"]
        if x is None:
            x = sw - w - 48
        if y is None:
            y = max(40, (sh - h) // 2 - 60)
        x = int(clamp(x, -w + 100, sw - 100))
        y = int(clamp(y, 0, max(0, sh - 60)))
        return dict(x=x, y=y, w=w, h=h,
                    topmost=bool(cfg["topmost"]),
                    opacity=float(clamp(cfg["opacity"], 0.4, 1.0)))

    def _save_window_cfg(self):
        try:
            g = self.geo
            g["x"], g["y"] = self.root.winfo_x(), self.root.winfo_y()
            g["w"], g["h"] = self.root.winfo_width(), self.root.winfo_height()
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(WINDOW_FILE, "w", encoding="utf-8") as f:
                json.dump(g, f, ensure_ascii=False)
        except Exception:
            pass

    def _apply_geometry(self):
        g = self.geo
        self.root.geometry("%dx%d+%d+%d" % (g["w"], g["h"], g["x"], g["y"]))

    def _apply_topmost(self):
        self.root.attributes("-topmost", bool(self.geo["topmost"]))

    def _apply_opacity(self):
        try:
            self.root.attributes("-alpha", float(self.geo["opacity"]))
        except Exception:
            pass

    def _ph_clear(self, w, which):
        if which == "entry" and self._entry_placeholder:
            w.delete(0, "end")
            w.config(fg=self.V["ink"])
            self._entry_placeholder = False
        elif which == "search" and self._search_placeholder:
            w.delete(0, "end")
            w.config(fg=self.V["ink"])
            self._search_placeholder = False

    def _ph_restore(self, w, which):
        if which == "entry":
            if not w.get().strip():
                w.delete(0, "end")
                w.insert(0, "记点什么… Enter 添加")
                w.config(fg=self.V["muted"])
                self._entry_placeholder = True
        else:
            if not w.get().strip():
                w.delete(0, "end")
                w.insert(0, "搜索待办…")
                w.config(fg=self.V["muted"])
                self._search_placeholder = True

    # ---------------------------------------------------------------- 事件

    def _bind_events(self):
        c = self.canvas
        c.bind("<Button-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_motion)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Motion>", self.on_hover)
        c.bind("<MouseWheel>", self.on_wheel)
        c.bind("<Configure>", self.on_resize)
        self.root.bind("<Escape>", self.on_esc)

    def on_resize(self, e):
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if getattr(self, "_last_wh", None) != (w, h) and w > 10:
            self._last_wh = (w, h)
            self.W, self.H = w, h
            self.draw()

    def on_esc(self, e):
        if self.popover:
            self.popover = None
        elif self.state["modal"] == "edit":
            self.close_edit()
            return
        elif self.state["modal"] in ("settings", "prompt"):
            self.close_modal()
            return
        elif self.state["search_open"]:
            self.state["search_open"] = False
            self.state["search"] = ""
        else:
            return
        self.draw()

    def on_wheel(self, e):
        delta = -1 if e.delta > 0 else 1
        if self.state["modal"] == "settings":
            self.state["sm_scroll"] = max(0, self.state["sm_scroll"] + delta * self.m(34))
        elif not self.state["modal"]:
            self.state["scroll"] = max(0, self.state["scroll"] + delta * self.m(46))
        else:
            return
        self.draw()

    def _search_changed(self, e):
        if self._search_placeholder:
            return
        self.state["search"] = self.search_entry.get()
        self.state["scroll"] = 0
        self.draw()

    # ---------------------------------------------------------------- 主循环

    def tick(self):
        try:
            # 托盘与全局热键的事件统一在这里消费(主线程)
            for q in ([self.hk.q] if self.hk else []) + \
                     ([self.tray_q] if self.tray_q else []):
                try:
                    while True:
                        msg = q.get_nowait()
                        if msg == "toggle":
                            self.toggle_visible()
                        elif msg == "quit":
                            self.quit_app()
                except Exception:
                    pass
            self.store.flush_if_dirty()
            show_file = os.path.join(DATA_DIR, ".show")
            try:
                if os.path.exists(show_file):
                    os.remove(show_file)
                    self.show_window()
            except Exception:
                pass
            if self._today != today_str():
                self._today = today_str()
                self.toast("新的一天,继续加油")
                self.draw()
            t = self.state.get("toast")
            if t and time.time() > t["until"]:
                self.state["toast"] = None
                self.draw()
        finally:
            try:
                self.root.after(1000, self.tick)
            except Exception:
                pass

    def toggle_visible(self):
        if self.root.state() == "withdrawn":
            self.show_window()
        else:
            self.hide_window()

    def show_window(self):
        self.store.flush_if_dirty()
        self.store.load()
        self._refresh_theme()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = int(clamp(self.root.winfo_width(), MIN_W, MAX_W))
        h = int(clamp(self.root.winfo_height(), MIN_H, MAX_H))
        x = int(clamp(self.root.winfo_x(), -w + 120, sw - 120))
        y = int(clamp(self.root.winfo_y(), 0, max(0, sh - 80)))
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.root.deiconify()
        self.root.lift()
        self._apply_topmost()
        self.root.focus_force()
        self.draw()
        if not getattr(self, "_hint_shown", False):
            self._hint_shown = True
            self.root.after(600, lambda: self.toast("按 %s 可随时显示/隐藏窗口" % self.store.settings.get("hotkey"), seconds=5))
        if self.store.settings.get("notify_due"):
            self.root.after(300, self._notify_due_today)

    def hide_window(self):
        self.store.flush_if_dirty()
        self._save_window_cfg()
        self.root.withdraw()

    def _notify_due_today(self):
        n, overdue = self.store.due_summary()
        if n <= 0:
            return
        msg = "今天有 %d 项待完成" % n
        if overdue:
            msg += ",其中 %d 项已逾期" % overdue
        self.toast(msg)

    def toast(self, text, action=None, seconds=3.5):
        self.state["toast"] = {"text": text, "until": time.time() + seconds,
                               "action": action}
        self.draw()

    # ---------------------------------------------------------------- 主题

    def _refresh_theme(self):
        self.T = theme_api.get_theme(self.store.settings.get("theme"))
        self.V = self.T["vars"]
        self.entry.config(fg=self.V["ink"] if not self._entry_placeholder else self.V["muted"])
        self.search_entry.config(fg=self.V["ink"] if not self._search_placeholder else self.V["muted"])
        self._themes_cache = theme_api.scan_themes()[0]

    def apply_theme(self, tid):
        self.store.settings["theme"] = tid
        self.store.save_later()
        self._refresh_theme()
        self.draw()

    def rescan_themes(self):
        themes, bad = theme_api.scan_themes()
        self._themes_cache = themes
        if bad:
            self.toast("有 %d 个主题文件无法识别" % len(bad))
        else:
            self.toast("已扫描,共 %d 个主题" % len(themes))
        self.draw()

    # ---------------------------------------------------------------- 命中与路由

    def _in_rect(self, x, y, rect):
        if not rect:
            return False
        x1, y1, x2, y2 = rect
        return x1 <= x <= x2 and y1 <= y <= y2

    def _pick(self, x, y):
        ids = self.canvas.find_overlapping(x, y, x, y)
        for i in sorted(ids, reverse=True):
            for t in self.canvas.gettags(i):
                if ":" in t and t.split(":", 1)[0] in TAG_PREFIX:
                    return t
        return None

    def _edge_at(self, x, y):
        e = self.m(6)
        W, H = getattr(self, "W", 0), getattr(self, "H", 0)
        if W < 10 or H < 10:
            return None
        if x > W - e and y > H - e:
            return "se"
        if x < e and y > H - e:
            return "sw"
        if x > W - e and y < e:
            return "ne"
        if x < e and y < e:
            return "nw"
        if x > W - e:
            return "e"
        if x < e:
            return "w"
        if y > H - e:
            return "s"
        if y < e:
            return "n"
        return None

    def on_press(self, e):
        x, y = e.x, e.y
        if self.popover:
            tag = self._pick(x, y)
            if tag and tag.startswith("pop:"):
                self.dispatch(tag, x, y, e)
                return
            self.popover = None
            self.draw()
            return
        if not self.state["modal"]:
            edge = self._edge_at(x, y)
            if edge:
                self.drag = {"kind": "resize", "edge": edge,
                             "sx": e.x_root, "sy": e.y_root,
                             "geo": (self.root.winfo_x(), self.root.winfo_y(),
                                     self.root.winfo_width(), self.root.winfo_height())}
                return
        tag = self._pick(x, y)
        if tag:
            self.dispatch(tag, x, y, e)
            return
        if self._in_rect(x, y, self.layout.get("tb")) and not self.state["modal"]:
            self.drag = {"kind": "move", "dx": x, "dy": y}
        elif self._in_rect(x, y, self.layout.get("list")) and not self.state["modal"]:
            self.state["hover_task"] = None
            self.draw()

    def dispatch(self, tag, x, y, e):
        p, _, rest = tag.partition(":")
        if p in ("sm", "em"):
            if rest == "back":
                if self.state["modal"] == "edit":
                    self.close_edit()
                else:
                    self.close_modal()
            return
        if p == "toast":
            if rest == "undo":
                act = (self.state.get("toast") or {}).get("action")
                if act and act[0] == "del":
                    self.store.restore(act[1])
                    self.state["toast"] = None
                    self.draw()
            return
        if p == "pop":
            self.handle_popover(rest)
            return
        if p == "hs":
            if rest == "opacity":
                self.drag = {"kind": "opacity"}
                self.set_opacity_from_x(x)
            return
        if p == "tgl":
            self.handle_toggle(rest)
            return
        if p == "theme":
            self.apply_theme(rest)
            return
        if p == "tab":
            self.state["tab"] = rest
            self.state["scroll"] = 0
            self.state["hover_task"] = None
            self.draw()
            return
        if p == "chip":
            self.handle_chip(rest, x, y)
            return
        if p == "task":
            self.handle_task(rest, x, y)
            return
        if p == "pb":
            if rest == "done-toggle":
                self.state["show_done"] = not self.state["show_done"]
                self.draw()
            return
        if p == "act":
            self.handle_act(rest, x, y)
            return

    # ---------------------------------------------------------------- 动作

    def handle_act(self, rest, x, y):
        st = self.state
        if rest == "tb":
            self.drag = {"kind": "move", "dx": x, "dy": y}
        elif rest == "btn-search":
            st["search_open"] = not st["search_open"]
            st["search"] = ""
            if st["search_open"]:
                self.search_entry.delete(0, "end")
                self.search_entry.insert(0, "搜索待办…")
                self.search_entry.config(fg=self.V["muted"])
                self._search_placeholder = True
                self.draw()
                self.search_entry.focus_set()
            else:
                self.draw()
        elif rest == "search-clear":
            self.search_entry.delete(0, "end")
            self.search_entry.insert(0, "搜索待办…")
            self.search_entry.config(fg=self.V["muted"])
            self._search_placeholder = True
            st["search"] = ""
            self.draw()
        elif rest == "btn-pin":
            self.geo["topmost"] = not self.geo["topmost"]
            self._apply_topmost()
            self._save_window_cfg()
            self.toast("已置顶" if self.geo["topmost"] else "已取消置顶")
        elif rest == "btn-settings":
            st["modal"] = "settings"
            st["sm_scroll"] = 0
            self._themes_cache = theme_api.scan_themes()[0]
            self.draw()
        elif rest == "btn-hide":
            self.hide_window()
        elif rest == "add":
            self.add_quick()
        elif rest.startswith("sm-"):
            self.handle_settings(rest[3:], x, y)
        elif rest.startswith("em-"):
            self.handle_edit_btn(rest[3:])
        elif rest.startswith("prompt-"):
            self.handle_prompt(rest[7:])
        elif rest.startswith("list-del-"):
            lid = rest[len("list-del-"):]
            if self.store.delete_list(lid):
                self.toast("清单已删除,任务移回收集箱")
                self.draw()
        elif rest == "list-new":
            self.open_prompt("新建清单", self._create_list_done)

    def _create_list_done(self, name):
        name = (name or "").strip()
        if not name:
            return
        lid = self.store.add_list(name)
        self.toast("已创建清单「%s」" % name)
        if self.edit and self.state["modal"] == "edit":
            self.edit["list_id"] = lid
        else:
            self.quick["list"] = lid

    def handle_toggle(self, key):
        if key == "topmost":
            self.geo["topmost"] = not self.geo["topmost"]
            self._apply_topmost()
            self._save_window_cfg()
        elif key == "autostart":
            want = not get_autostart()
            if set_autostart(want):
                self.toast("已开启开机自启(静默后台)" if want else "已关闭开机自启")
            else:
                self.toast("设置自启失败")
        elif key == "notify_due":
            self.store.settings["notify_due"] = not self.store.settings.get("notify_due")
            self.store.save_later()
        self.draw()

    def handle_settings(self, rest, x, y):
        if rest == "close":
            self.close_modal()
        elif rest == "rescan":
            self.rescan_themes()
        elif rest == "hotkey-next":
            self._cycle_hotkey(1)
        elif rest == "hotkey-prev":
            self._cycle_hotkey(-1)
        elif rest == "export":
            self.export_data()
        elif rest == "import":
            self.import_data()
        elif rest == "folder":
            try:
                os.startfile(DATA_DIR)
            except Exception:
                self.toast("无法打开文件夹")
        elif rest == "resetwin":
            self.geo = self._load_window_cfg()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.geo["x"] = sw - self.geo["w"] - 48
            self.geo["y"] = max(40, (sh - self.geo["h"]) // 2 - 60)
            self._apply_geometry()
            self._apply_topmost()
            self._apply_opacity()
            self._save_window_cfg()
            self.draw()
        elif rest == "clear-done":
            n = self.store.clear_done()
            self.toast(("已把 %d 个已完成项移入回收站" % n) if n else "没有已完成项")
            self.draw()
        elif rest == "empty-trash":
            n = len(self.store.trash())
            self.store.empty_trash()
            self.toast(("已清空回收站(%d 项)" % n) if n else "回收站已经是空的")
            self.draw()
        elif rest == "quit":
            self.quit_app()

    def _cycle_hotkey(self, step):
        opts = hk_mod.HOTKEY_OPTIONS
        cur = self.store.settings.get("hotkey", "Ctrl+Alt+T")
        try:
            i = opts.index(cur)
        except ValueError:
            i = 0
        new = opts[(i + step) % len(opts)]
        ok = False
        if self.hk:
            ok = self.hk.start(new)
        if ok:
            self.store.settings["hotkey"] = new
            self.store.save_later()
            self.hotkey_ok = True
            self.toast("显示/隐藏热键:%s" % new)
        else:
            self.toast("「%s」注册失败,可能被占用" % new)
            # 换键失败要回滚,否则旧热键也没了
            if self.hk:
                self.hotkey_ok = self.hk.start(
                    self.store.settings.get("hotkey", "Ctrl+Alt+Space"))
        self.draw()

    def export_data(self):
        fn = filedialog.asksaveasfilename(
            defaultextension=".json", initialfile="待办备份-%s.json" % today_str(),
            filetypes=[("JSON 备份", "*.json")], parent=self.root)
        if not fn:
            return
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(self.store.export_payload(), f, ensure_ascii=False, indent=1)
            self.toast("已导出:%s" % os.path.basename(fn))
        except Exception as ex:
            self.toast("导出失败:%s" % ex)

    def import_data(self):
        fn = filedialog.askopenfilename(filetypes=[("JSON 备份", "*.json")],
                                        parent=self.root)
        if not fn:
            return
        try:
            with open(fn, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.store.import_payload(payload)
            self._refresh_theme()
            self.toast("导入成功,共 %d 项任务" % len(self.store.tasks))
            self.draw()
        except Exception as ex:
            self.toast("导入失败:%s" % ex)

    def quit_app(self):
        self.store.flush_if_dirty()
        self._save_window_cfg()
        if self.tray:
            self.tray.stop()
        if self.hk:
            self.hk.stop()
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    def close_modal(self):
        kind = self.state["modal"]
        self.state["modal"] = None
        self.state["sm_scroll"] = 0
        if kind == "prompt":
            self.close_prompt()
        self.draw()

    # ---------------------------------------------------------------- 快速添加

    def add_quick(self):
        title = self.entry.get().strip()
        if self._entry_placeholder or not title:
            self.state["flash_input"] = True
            self.draw()
            self.root.after(500, self._unflash)
            return
        self.store.add(title, daily=self.quick["daily"], due=self.quick["due"],
                       priority=self.quick["pri"], list_id=self.quick["list"])
        self.store.settings["last_list"] = self.quick["list"]
        self.entry.delete(0, "end")
        self.draw()

    def _unflash(self):
        if self.state["flash_input"]:
            self.state["flash_input"] = False
            self.draw()

    def handle_chip(self, rest, x, y):
        ctx, _, what = rest.partition("-")
        if what == "daily":
            if ctx == "quick":
                self.quick["daily"] = not self.quick["daily"]
            elif self.edit:
                self.edit["daily"] = not self.edit["daily"]
            self.draw()
        elif what == "pri":
            if ctx == "quick":
                self.quick["pri"] = (self.quick["pri"] + 1) % 3
            elif self.edit:
                self.edit["pri"] = (self.edit["pri"] + 1) % 3
            self.draw()
        elif what == "due":
            self.open_popover("calendar", ctx, x, y)
        elif what == "list":
            self.open_popover("list", ctx, x, y)

    def open_popover(self, kind, ctx, x, y):
        self.popover = {"kind": kind, "ctx": ctx, "x": x, "y": y}
        self.draw()

    def _commit_due(self, value):
        """日历面板确认截止,写回快捷栏或编辑弹窗。"""
        pop = self.popover
        self.popover = None
        if pop and pop.get("ctx") == "em" and self.edit:
            self.edit["due"] = value
        else:
            self.quick["due"] = value
        self.draw()

    def handle_calendar(self, pop, action):
        if action in ("prev", "next"):
            y, mth = pop["year"], pop["month"]
            mth += 1 if action == "next" else -1
            if mth == 0:
                mth, y = 12, y - 1
            elif mth == 13:
                mth, y = 1, y + 1
            pop["year"], pop["month"] = y, mth
        elif action == "cur":
            t = datetime.date.today()
            pop["year"], pop["month"] = t.year, t.month
        elif action.startswith("day-"):
            pop["sel"] = action[4:]
        elif action == "hour-up":
            pop["hour"] = (pop["hour"] + 1) % 24
        elif action == "hour-down":
            pop["hour"] = (pop["hour"] - 1) % 24
        elif action == "min-up":
            pop["minute"] = (pop["minute"] + 5) % 60
        elif action == "min-down":
            pop["minute"] = (pop["minute"] - 5) % 60
        elif action == "ok":
            if not pop.get("sel"):
                self.popover = None
                self.toast("先在日历上选一天")
                self.draw()
                return
            self._commit_due("%s %02d:%02d" % (pop["sel"], pop["hour"], pop["minute"]))
            return
        elif action == "clear":
            self._commit_due(None)
            return
        elif action.startswith("p") and action[1:].isdigit():
            idx = int(action[1:])
            if idx < len(DUE_PRESETS):
                self._commit_due(DUE_PRESETS[idx][1]())
            return
        self.draw()

    def handle_popover(self, rest):
        pop = self.popover or {}
        kind = pop.get("kind")
        if kind == "calendar":
            if rest.startswith("cal-"):
                self.handle_calendar(pop, rest[4:])
            return
        ctx = pop.get("ctx")
        options = pop.get("options") or []
        val = options[int(rest)] if rest.isdigit() and int(rest) < len(options) else None
        self.popover = None
        if kind == "list":
            if val == "__new__":
                back = self.state["modal"] if self.state["modal"] in ("edit", "settings") else None
                self.open_prompt("新建清单", self._create_list_done, back)
                return
            if ctx == "em" and self.edit:
                self.edit["list_id"] = val
            else:
                self.quick["list"] = val
        self.draw()

    def open_prompt(self, title, on_ok, back=None):
        self._prompt_back = back
        self.state["modal"] = "prompt"
        self.prompt = {"title": title, "on_ok": on_ok}
        self.prompt_entry = tk.Entry(self.canvas, font=self.f_base, relief="flat",
                                     highlightthickness=0, bd=0,
                                     fg=self.V["ink"], insertbackground=self.V["ink"])
        self.draw()
        self.prompt_entry.focus_set()

    def handle_prompt(self, rest):
        if not self.prompt:
            return
        if rest == "ok":
            val = self.prompt_entry.get()
            cb = self.prompt.get("on_ok")
            self.close_prompt()
            back = self._prompt_back
            self._prompt_back = None
            if back:
                self.state["modal"] = back
            if cb:
                cb(val)
            self.draw()
        elif rest == "cancel":
            self.close_prompt()
            back = self._prompt_back
            self._prompt_back = None
            if back:
                self.state["modal"] = back
            self.draw()

    def close_prompt(self):
        if self.prompt_entry:
            try:
                self.prompt_entry.destroy()
            except Exception:
                pass
            self.prompt_entry = None
        self.prompt = None

    # ---------------------------------------------------------------- 任务操作

    def handle_task(self, rest, x, y):
        tid_s, _, part = rest.partition(":")
        try:
            tid = int(tid_s)
        except ValueError:
            return
        t = self.store.get(tid)
        if not t:
            return
        if part == "check":
            was_daily = t["daily"]
            self.store.toggle(tid)
            t2 = self.store.get(tid)
            if was_daily and self.store.is_done_today(t2):
                self.toast("打卡成功 · 已连续 %d 天" % t2["streak"])
            self.draw()
        elif part == "edit":
            self.open_edit(tid)
        elif part == "del":
            self.store.delete(tid)
            if self.edit and self.edit.get("id") == tid:
                self.close_edit()
            self.toast("已移入回收站", action=("del", tid))
            self.draw()
        elif part == "restore":
            self.store.restore(tid)
            self.draw()
        elif part == "purge":
            self.store.purge(tid)
            self.draw()
        else:
            geo = self.card_geo.get(tid)
            grab = (y - geo[0]) if geo else self.m(16)
            self.drag = {"kind": "task", "tid": tid, "sx": x, "sy": y,
                         "moved": False, "grab": grab}

    def open_edit(self, tid):
        t = self.store.get(tid)
        if not t:
            return
        self.edit = {"id": tid, "daily": t["daily"], "due": t["due"],
                     "pri": t["priority"], "list_id": t["list_id"]}
        self.state["modal"] = "edit"
        self.popover = None
        self.edit_title = tk.Entry(self.canvas, font=self.f_base, relief="flat",
                                   highlightthickness=0, bd=0,
                                   fg=self.V["ink"], insertbackground=self.V["ink"])
        self.edit_title.insert(0, t["title"])
        self.edit_notes = tk.Text(self.canvas, font=self.f_small, relief="flat",
                                  highlightthickness=0, bd=0, wrap="word",
                                  fg=self.V["ink_soft"], insertbackground=self.V["ink"],
                                  height=3)
        self.edit_notes.insert("1.0", t.get("notes") or "")
        self.draw()
        self.edit_title.focus_set()
        try:
            self.edit_title.icursor("end")
        except Exception:
            pass

    def close_edit(self):
        self.edit = None
        self.state["modal"] = None
        for name in ("edit_title", "edit_notes"):
            w = getattr(self, name, None)
            if w:
                try:
                    w.destroy()
                except Exception:
                    pass
                setattr(self, name, None)
        self.draw()

    def handle_edit_btn(self, rest):
        if not self.edit:
            return
        if rest == "save":
            title = self.edit_title.get().strip()
            notes = self.edit_notes.get("1.0", "end").strip("\n")
            if title:
                self.store.update(self.edit["id"], title=title, notes=notes,
                                  daily=self.edit["daily"], due=self.edit["due"],
                                  priority=self.edit["pri"], list_id=self.edit["list_id"])
                self.store.settings["last_list"] = self.edit["list_id"]
            self.close_edit()
        elif rest == "delete":
            tid = self.edit["id"]
            self.store.delete(tid)
            self.close_edit()
            self.toast("已移入回收站", action=("del", tid))
        elif rest == "cancel":
            self.close_edit()

    # ---------------------------------------------------------------- 悬停/拖动/缩放

    def on_motion(self, e):
        """按住拖动(B1-Motion)与悬停共用同一处理器。"""
        self.on_hover(e)

    def on_hover(self, e):
        x, y = e.x, e.y
        if self.drag:
            d = self.drag
            if d["kind"] == "resize":
                self.do_resize(e)
            elif d["kind"] == "move":
                self.root.geometry("+%d+%d" % (e.x_root - d["dx"], e.y_root - d["dy"]))
            elif d["kind"] == "opacity":
                self.set_opacity_from_x(x)
            elif d["kind"] == "task":
                if abs(x - d["sx"]) > self.m(5) or abs(y - d["sy"]) > self.m(5):
                    d["moved"] = True
                if d["moved"]:
                    self.drag_task = d["tid"]
                    self._drag_y = y - d["grab"]
                    self.draw()
            return
        cur = ""
        if not self.state["modal"]:
            edge = self._edge_at(x, y)
            cur = {"e": "sb_h_double_arrow", "w": "sb_h_double_arrow",
                   "s": "sb_v_double_arrow", "n": "sb_v_double_arrow",
                   "ne": "top_right_corner", "nw": "top_left_corner",
                   "se": "bottom_right_corner", "sw": "bottom_left_corner"}.get(edge, "")
            if not cur:
                tag = self._pick(x, y)
                if tag:
                    if tag.split(":", 1)[0] in ("act", "task", "tab", "chip", "pop",
                                                "theme", "tgl", "toast", "pb", "hs"):
                        cur = "hand2"
        if self.canvas.cget("cursor") != cur:
            self.canvas.config(cursor=cur)
        if self.state["modal"]:
            return
        tag = self._pick(x, y)
        hid = None
        if tag and tag.startswith("task:"):
            try:
                hid = int(tag.split(":")[1])
            except Exception:
                hid = None
        if hid != self.state["hover_task"]:
            self.state["hover_task"] = hid
            self.draw()

    def on_release(self, e):
        d = self.drag
        self.drag = None
        if not d:
            return
        if d["kind"] == "move":
            self._save_window_cfg()
        elif d["kind"] == "resize":
            self.geo["x"], self.geo["y"] = self.root.winfo_x(), self.root.winfo_y()
            self.geo["w"], self.geo["h"] = self.root.winfo_width(), self.root.winfo_height()
            self._save_window_cfg()
            self.draw()
        elif d["kind"] == "task":
            tid = d["tid"]
            self.drag_task = None
            self._drag_y = None
            if not d["moved"]:
                if tid in self._expanded:
                    self._expanded.discard(tid)
                else:
                    self._expanded.add(tid)
                self.draw()
            else:
                hint = self.drop_hint
                if hint and hint[0] != tid:
                    self.store.reorder(tid, hint[0], hint[1])
                self.drop_hint = None
                self.draw()

    def do_resize(self, e):
        d = self.drag
        gx, gy, gw, gh = d["geo"]
        dx = e.x_root - d["sx"]
        dy = e.y_root - d["sy"]
        x, y, w, h = gx, gy, gw, gh
        edge = d["edge"]
        if "e" in edge:
            w = gw + dx
        if "w" in edge:
            w = gw - dx
        if "s" in edge:
            h = gh + dy
        if "n" in edge:
            h = gh - dy
        w = int(clamp(w, MIN_W, MAX_W))
        h = int(clamp(h, MIN_H, MAX_H))
        if "w" in edge:
            x = gx + (gw - w)
        if "n" in edge:
            y = gy + (gh - h)
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def set_opacity_from_x(self, x):
        tr = getattr(self, "_opacity_track", None)
        if not tr:
            return
        x1, x2 = tr
        ratio = clamp((x - x1) / float(max(1, x2 - x1)), 0.0, 1.0)
        self.geo["opacity"] = round(0.4 + ratio * 0.6, 2)
        self._apply_opacity()
        self._save_window_cfg()
        self.draw()

    # ================================================================ 绘制

    def draw(self):
        c = self.canvas
        W = self.root.winfo_width()
        H = self.root.winfo_height()
        if W < 30 or H < 30:
            return
        self.W, self.H = W, H
        V = self.V
        c.delete("all")
        self.layout = {}

        rrect(c, 0, 0, W - 1, H - 1, self.m(16),
              fill=V["bg"], outline=V["border"], width=1.5)
        rrect(c, 2, 2, W - 3, H - 3, self.m(15), fill="", outline=V["chip"], width=1)

        self.draw_titlebar()
        y = self.m(46)
        if self.state["search_open"]:
            self.draw_searchbar(y)
            y += self.m(38)
        self.draw_progress(y)
        y += self.m(32)
        y = self.draw_tabs(y)
        self.layout["list"] = (self.m(10), y, W - self.m(18), H - self.m(100))
        self.draw_list(*self.layout["list"])
        self.draw_composer(H)
        self.draw_scrollbar()

        if self.state["toast"]:
            self.draw_toast()
        if self.state["modal"] == "settings":
            self.draw_settings()
        elif self.state["modal"] == "edit":
            self.draw_edit_modal()
        elif self.state["modal"] == "prompt":
            self.draw_prompt()
        if self.popover:
            self.draw_popover()

    # ---- 标题栏 ----

    def draw_titlebar(self):
        c, V, W = self.canvas, self.V, self.W
        th = self.m(46)
        self.layout["tb"] = (0, 0, W, th)
        t = V.get("title", "待办")
        bx = self.m(16)
        ic_sprout(c, bx + self.m(9), th / 2, self.m(16), V["accent"], V["accent_deep"],
                  tags=("act:tb",))
        c.create_text(bx + self.m(26), th / 2, text=t, anchor="w",
                      font=self.f_title, fill=V["ink"], tags=("act:tb",))
        now = datetime.datetime.now()
        date_txt = "%d月%d日 · %s" % (now.month, now.day, WEEK_CN[now.weekday()])
        # 日期放不下时省略(窄窗口),进度行右侧也会显示
        date_x = bx + self.m(26) + self.f_title.measure(t) + self.m(10)
        icons_x0 = W - self.m(16) - 4 * self.m(27)
        if date_x + self.f_tiny.measure(date_txt) < icons_x0 - self.m(10):
            c.create_text(date_x, th / 2 + 1, text=date_txt, anchor="w",
                          font=self.f_tiny, fill=V["muted"], tags=("act:tb",))
        c.create_rectangle(0, 0, W - len("btns") * 0, th, fill="", outline="", width=0,
                           tags=("act:tb",))
        by = th / 2
        btns = ["search", "pin", "settings", "hide"]
        x = W - self.m(16) - len(btns) * self.m(27)
        for name in btns:
            tags = ("act:btn-" + name,)
            if name == "search":
                ic_search(c, x + self.m(13), by, self.m(14), V["ink_soft"], tags)
            elif name == "pin":
                on = self.geo["topmost"]
                ic_pin(c, x + self.m(13), by, self.m(15),
                       V["accent_deep"] if on else V["muted"], tags)
            elif name == "settings":
                ic_gear(c, x + self.m(13), by, self.m(14), V["ink_soft"], tags)
            else:
                ic_minus(c, x + self.m(13), by, self.m(14), V["ink_soft"], tags)
            c.create_rectangle(x, by - self.m(13), x + self.m(27), by + self.m(13),
                               fill="", outline="", width=0, tags=tags)
            x += self.m(27)

    # ---- 搜索条 ----

    def draw_searchbar(self, y):
        c, V, W = self.canvas, self.V, self.W
        if self.state["modal"] or self.popover:
            return  # 弹窗/弹层打开时不嵌入输入控件(widget 永远浮在画布元素之上)
        x1 = self.m(12)
        x2 = W - self.m(12)
        h = self.m(30)
        rrect(c, x1, y, x2, y + h, self.m(15), fill=V["panel"], outline=V["line"], width=1)
        c.create_window(x1 + self.m(12), y + h / 2, window=self.search_entry, anchor="w",
                        width=x2 - x1 - self.m(46), height=h - self.m(8))
        ic_x(c, x2 - self.m(14), y + h / 2, self.m(10), V["muted"], tags=("act:search-clear",))
        c.create_rectangle(x2 - self.m(26), y, x2, y + h, fill="", outline="", width=0,
                           tags=("act:search-clear",))

    # ---- 进度 ----

    def draw_progress(self, y):
        c, V, W = self.canvas, self.V, self.W
        done_n, total = self.store.today_progress()
        _, overdue = self.store.due_summary()
        x1 = self.m(16)
        c.create_text(x1, y + self.m(10), text="今日进度", anchor="w",
                      font=self.f_tiny, fill=V["muted"])
        c.create_text(x1 + self.f_tiny.measure("今日进度") + self.m(6), y + self.m(10),
                      text="%d/%d" % (done_n, total), anchor="w",
                      font=self.f_tiny, fill=V["accent_deep"])
        now = datetime.datetime.now()
        date_txt = "%d月%d日 · %s" % (now.month, now.day, WEEK_CN[now.weekday()])
        right_x = W - self.m(16)
        if overdue:
            c.create_text(right_x, y + self.m(10), text="逾期 %d 项" % overdue,
                          anchor="e", font=self.f_tiny, fill=V["danger"])
            right_x -= self.f_tiny.measure("逾期 %d 项" % overdue) + self.m(12)
        c.create_text(right_x, y + self.m(10), text=date_txt, anchor="e",
                      font=self.f_tiny, fill=V["muted"])
        bar_y = y + self.m(19)
        bx1, bx2 = x1, W - self.m(16)
        rrect(c, bx1, bar_y, bx2, bar_y + self.m(5), 2, fill=V["chip"], outline="")
        if total > 0:
            fill_w = max(self.m(5), (bx2 - bx1) * done_n / float(total))
            rrect(c, bx1, bar_y, bx1 + fill_w, bar_y + self.m(5), 2,
                  fill=V["accent"], outline="")

    # ---- 选项卡 ----

    def draw_tabs(self, y):
        c, V, W = self.canvas, self.V, self.W
        tabs = [("today", "今日"), ("all", "全部"), ("done", "已完成"), ("trash", "回收站")]
        trash_n = len(self.store.trash())
        seg = (W - self.m(20)) / float(len(tabs))
        x = self.m(10)
        h = self.m(28)
        for tid, label in tabs:
            active = self.state["tab"] == tid
            txt = label + (" %d" % trash_n if tid == "trash" and trash_n else "")
            if active:
                rrect(c, x + 2, y, x + seg - 2, y + h, self.m(14),
                      fill=V["accent_soft"], outline="")
            c.create_text(x + seg / 2, y + h / 2, text=txt, font=self.f_small,
                          fill=V["accent_deep"] if active else V["muted"],
                          tags=("tab:" + tid,))
            c.create_rectangle(x, y, x + seg, y + h, fill="", outline="", width=0,
                               tags=("tab:" + tid,))
            x += seg
        return y + h + self.m(6)

    # ---- 列表 ----

    def build_rows(self):
        st = self.state
        kw = (st.get("search") or "").strip().lower()

        def match(t):
            if not kw:
                return True
            return kw in t["title"].lower() or kw in (t.get("notes") or "").lower()

        rows = []
        if st["tab"] == "today":
            daily, todo, done = self.store.today_sections()
            daily = [t for t in daily if match(t)]
            todo = [t for t in todo if match(t)]
            done = [t for t in done if match(t)]
            if daily:
                dn = sum(1 for t in daily if self.store.is_done_today(t))
                rows.append(("section", "每日打卡", "%d/%d" % (dn, len(daily))))
                rows += [("task", t) for t in daily]
            if todo:
                rows.append(("section", "待办", str(len(todo))))
                rows += [("task", t) for t in todo]
            if done:
                rows.append(("sec-toggle", "今日已完成", str(len(done)), st["show_done"]))
                if st["show_done"]:
                    rows += [("task", t, "done") for t in done]
            if not rows:
                rows.append(("empty", "today"))
        elif st["tab"] == "all":
            for name, ts in self.store.all_sections(keyword=kw):
                rows.append(("section", name, str(len(ts))))
                rows += [("task", t) for t in ts]
            if not rows:
                rows.append(("empty", "all"))
        elif st["tab"] == "done":
            done = [t for t in self.store.visible()
                    if t["done"] and not t["daily"] and match(t)]
            done.sort(key=lambda t: t.get("done_at") or "", reverse=True)
            if done:
                rows.append(("section", "已完成", str(len(done))))
                rows += [("task", t, "done") for t in done]
            else:
                rows.append(("empty", "done"))
        elif st["tab"] == "trash":
            ts = [t for t in self.store.trash() if match(t)]
            if ts:
                rows.append(("section", "回收站", str(len(ts))))
                rows += [("task", t, "trash") for t in ts]
            else:
                rows.append(("empty", "trash"))
        return rows

    def draw_list(self, lx, ly, lw, ly2):
        c, V = self.canvas, self.V
        self.card_geo = {}
        rows = self.build_rows()
        gap = self.m(6)
        view_h = ly2 - ly
        content_top = ly + self.m(2) - self.state["scroll"]
        drag_tid = self.drag_task

        heights = []
        for row in rows:
            if row[0] == "task":
                heights.append(self.card_height(row[1], row[2] if len(row) > 2 else "", lw))
            elif row[0] in ("section", "sec-toggle"):
                heights.append(self.m(22))
            else:
                heights.append(self.m(80))

        # 拖拽目标计算
        self.drop_hint = None
        if drag_tid and self._drag_y is not None:
            yy = content_top
            for row, hgt in zip(rows, heights):
                if row[0] == "task" and row[1]["id"] != drag_tid:
                    if yy <= self._drag_y <= yy + hgt - gap:
                        self.drop_hint = (row[1]["id"], self._drag_y > yy + (hgt - gap) / 2)
                        break
                yy += hgt

        yy = content_top
        for row, hgt in zip(rows, heights):
            kind = row[0]
            # 顶边溢出的卡片直接跳过(避免盖住标题栏/选项卡),底边由遮罩裁剪
            if yy >= ly - self.m(2) and yy <= ly2:
                if kind == "section":
                    self.draw_section(yy, row[1], row[2])
                elif kind == "sec-toggle":
                    self.draw_sec_toggle(yy, row[1], row[2], row[3])
                elif kind == "task":
                    if drag_tid and row[1]["id"] == drag_tid:
                        pass  # 拖拽中的卡片最后浮层绘制
                    else:
                        self.draw_task(row[1], yy, lw, row[2] if len(row) > 2 else "")
                elif kind == "empty":
                    self.draw_empty(yy, row[1])
            yy += hgt
        content_h = yy - content_top + self.m(4)
        self._list_content_h = content_h
        self._list_view_h = view_h
        max_scroll = max(0, content_h - view_h)
        if self.state["scroll"] > max_scroll:
            self.state["scroll"] = max_scroll

        # 底部遮罩(裁掉溢出到输入区的卡片)
        c.create_rectangle(0, ly2, self.W, self.H, fill=V["bg"], outline="", tags=("mask",))

        # 拖拽中的卡片浮层 + 插入线
        if drag_tid and self._drag_y is not None:
            t = self.store.get(drag_tid)
            if t:
                self.draw_task(t, self._drag_y, lw, "", shadow=True)
            hint = self.drop_hint
            if hint:
                yy = content_top
                for row, hgt in zip(rows, heights):
                    if row[0] == "task" and row[1]["id"] == hint[0]:
                        line_y = yy + hgt - gap if hint[1] else yy
                        c.create_line(lx + 2, line_y, lx + lw - 2, line_y,
                                      fill=V["accent"], width=2, dash=(4, 3))
                        break
                    yy += hgt

    def card_height(self, t, mode, card_w):
        base = self.m(38)
        has_meta = bool(t.get("due") or t.get("priority") or t["daily"]
                        or (t.get("list_id") and t["list_id"] != "inbox"))
        if has_meta:
            base += self.m(15)
        if mode != "done" and t.get("notes") and t["id"] in self._expanded:
            tw = card_w - self.m(64)
            base += self.m(6) + text_h(self.f_small, t["notes"], tw)
        return base + self.m(6)

    def draw_section(self, y, label, count):
        c, V = self.canvas, self.V
        x = self.m(16)
        c.create_text(x, y + self.m(9), text=label, anchor="w",
                      font=self.f_tiny, fill=V["ink_soft"])
        if count:
            c.create_text(x + self.f_tiny.measure(label) + self.m(6), y + self.m(9),
                          text=count, anchor="w", font=self.f_tiny, fill=V["muted"])

    def draw_sec_toggle(self, y, label, count, open_):
        c, V = self.canvas, self.V
        x = self.m(16)
        tags = ("pb:done-toggle",)
        tw = self.f_tiny.measure(label)
        c.create_text(x, y + self.m(9), text=label, anchor="w",
                      font=self.f_tiny, fill=V["muted"], tags=tags)
        c.create_text(x + tw + self.m(6), y + self.m(9),
                      text=count, anchor="w", font=self.f_tiny, fill=V["muted"], tags=tags)
        ic_chevron(c, x + tw + self.f_tiny.measure(count) + self.m(20),
                   y + self.m(9), self.m(10), V["muted"], tags, down=not open_)
        c.create_rectangle(x - 4, y, x + tw + self.m(60), y + self.m(20),
                           fill="", outline="", width=0, tags=tags)

    def draw_empty(self, y, kind):
        c, V = self.canvas, self.V
        cx = self.W / 2
        ic_sprout(c, cx, y + self.m(24), self.m(24), V["accent"], V["accent_deep"])
        msgs = {"today": "今天没有待办,安心休息",
                "done": "还没有已完成的事项",
                "trash": "回收站是空的",
                "all": "还没有任务,在下方添加一条吧"}
        c.create_text(cx, y + self.m(52), text=msgs.get(kind, "空空如也"),
                      font=self.f_small, fill=V["muted"])

    def fit_text(self, text, font, maxw):
        if font.measure(text) <= maxw:
            return text
        while text and font.measure(text + "…") > maxw:
            text = text[:-1]
        return text + "…"

    def draw_task(self, t, y, w, mode="", shadow=False):
        c, V = self.canvas, self.V
        lx = self.layout["list"][0]
        x1, x2 = lx, lx + w
        h = self.card_height(t, mode, w) - self.m(6)
        tid = t["id"]
        body = "task:%d" % tid
        hover = (self.state["hover_task"] == tid and not self.drag_task) or shadow
        fill = V["card_hover"] if hover else V["card"]
        radius = self.T.get("radius", 12)
        rrect(c, x1, y, x2, y + h, radius, fill=fill,
              outline=V["accent"] if shadow else V["line"],
              width=1.4 if shadow else 1, tags=(body,))
        self.card_geo[tid] = (y, y + h)

        done_now = self.store.is_done_today(t)
        cy = y + h / 2 if mode in ("done", "trash") else y + self.m(19)
        cx = x1 + self.m(20)
        checkbox(c, cx, cy, self.m(8), done_now, V["accent"], V["muted"],
                 daily=t["daily"], bg=fill, tags=(body + ":check",))

        tx = cx + self.m(15)
        ax = x2 - self.m(16)
        show_actions = hover and not shadow
        if mode == "trash":
            tit_col = V["muted"]
            if show_actions:
                ic_restore(c, ax - self.m(26), y + self.m(19), self.m(12), V["accent_deep"],
                           tags=(body + ":restore",))
                ic_trash(c, ax, y + self.m(19), self.m(12), V["danger"], tags=(body + ":purge",))
                for off, part in ((self.m(26), "restore"), (0, "purge")):
                    c.create_rectangle(ax - off - self.m(11), y, ax - off + self.m(11),
                                       y + h, fill="", outline="", width=0,
                                       tags=(body + ":" + part,))
        else:
            tit_col = V["muted"] if (done_now or mode == "done") else V["ink"]
            if show_actions and mode != "done":
                ic_pencil(c, ax - self.m(26), y + self.m(19), self.m(12), V["ink_soft"],
                          tags=(body + ":edit",))
                ic_trash(c, ax, y + self.m(19), self.m(12), V["danger"], tags=(body + ":del",))
                for off, part in ((self.m(26), "edit"), (0, "del")):
                    c.create_rectangle(ax - off - self.m(11), y, ax - off + self.m(11),
                                       y + h, fill="", outline="", width=0,
                                       tags=(body + ":" + part,))
        maxw = (ax - self.m(52)) - tx if show_actions else (x2 - self.m(12)) - tx
        title = self.fit_text(t["title"], self.f_base, maxw)
        c.create_text(tx, cy, text=title, anchor="w", font=self.f_base, fill=tit_col,
                      tags=(body,))

        # 元信息
        meta = []
        if t["daily"]:
            meta.append(("daily", "每日"))
            if t.get("streak"):
                meta.append(("fire", "连续%d天" % t["streak"]))
        if t.get("due"):
            overdue = due_overdue(t["due"]) and not done_now
            meta.append(("due", due_label(t["due"]), overdue))
        if t.get("priority"):
            meta.append(("pri", {1: "中优先", 2: "高优先"}[t["priority"]],
                         {1: "mid", 2: "high"}[t["priority"]]))
        if t.get("list_id") and t["list_id"] != "inbox":
            meta.append(("list", self.store.list_name(t["list_id"]) or "未分类"))
        if mode == "done" and t.get("done_at"):
            meta.append(("time", (t["done_at"] or "")[-5:] + " 完成"))
        if meta:
            my = y + self.m(33)
            cxp = tx
            for item in meta:
                kind, label = item[0], item[1]
                if kind == "daily":
                    col = V["accent_deep"]
                    ic_repeat(c, cxp + self.m(5), my + self.m(1), self.m(10), col, tags=(body,))
                    cxp += self.m(14)
                elif kind == "fire":
                    col = V["due"]
                    ic_fire(c, cxp + self.m(5), my + self.m(2), self.m(10), col, tags=(body,))
                    cxp += self.m(14)
                elif kind == "due":
                    col = V["danger"] if item[2] else V["due"]
                    ic_calendar(c, cxp + self.m(5), my + self.m(1), self.m(10), col, tags=(body,))
                    cxp += self.m(14)
                elif kind == "pri":
                    col = V["danger"] if item[2] == "high" else V["due"]
                    ic_flag(c, cxp + self.m(5), my + self.m(1), self.m(10), col, tags=(body,))
                    cxp += self.m(14)
                elif kind == "list":
                    col = V["muted"]
                    c.create_oval(cxp, my - self.m(1), cxp + self.m(5), my + self.m(4),
                                  fill=V["accent"], outline="", tags=(body,))
                    cxp += self.m(9)
                else:
                    col = V["muted"]
                c.create_text(cxp, my + self.m(1), text=label, anchor="w",
                              font=self.f_tiny, fill=col, tags=(body,))
                cxp += self.f_tiny.measure(label) + self.m(10)

        # 展开的备注
        if mode not in ("done", "trash") and t.get("notes") and tid in self._expanded:
            ny = y + (self.m(50) if meta else self.m(36))
            c.create_text(tx, ny, text=t["notes"], anchor="nw", font=self.f_small,
                          fill=V["ink_soft"], width=w - self.m(56), tags=(body,),
                          justify="left")

    # ---- 滚动条 ----

    def draw_scrollbar(self):
        c, V = self.canvas, self.V
        lx, ly, lw, ly2 = self.layout["list"]
        content = getattr(self, "_list_content_h", 0)
        view = getattr(self, "_list_view_h", 0)
        if content <= view:
            return
        x = lx + lw + self.m(2)
        track_h = ly2 - ly
        th = max(self.m(30), track_h * view / float(content))
        max_sc = max(1, content - view)
        ty = ly + (track_h - th) * (self.state["scroll"] / float(max_sc))
        rrect(c, x, ty, x + self.m(4), ty + th, 2, fill=V["scrollbar"], outline="")

    # ---- 底部输入区 ----

    def draw_composer(self, H):
        c, V, W = self.canvas, self.V, self.W
        ch = self.m(96)
        top = H - ch
        self.layout["composer"] = (0, top, W, H)
        x1 = self.m(12)
        x2 = W - self.m(12)
        cy = top + self.m(6)
        chip_h = self.m(22)
        q = self.quick
        due_txt = due_label(q["due"]) if q["due"] else "截止"
        pri_txt = {0: "优先级", 1: "中", 2: "高"}[q["pri"]]
        lname = self.store.list_name(q["list"]) or "收集箱"
        self.draw_chip_row(x1, x2, cy, chip_h, [
            dict(label="每日", painter=ic_repeat, active=q["daily"],
                 tag="chip:quick-daily"),
            dict(label=due_txt, painter=ic_calendar, active=bool(q["due"]),
                 tag="chip:quick-due", col=V["due"] if q["due"] else None),
            dict(label=pri_txt, painter=ic_flag, active=bool(q["pri"]),
                 tag="chip:quick-pri",
                 col={0: None, 1: V["due"], 2: V["danger"]}[q["pri"]]),
            dict(label=lname, active=q["list"] != "inbox",
                 tag="chip:quick-list", dot=True),
        ])
        iy = cy + chip_h + self.m(8)
        ih = self.m(38)
        flash = self.state["flash_input"]
        rrect(c, x1, iy, x2 - self.m(50), iy + ih, self.m(19),
              fill=V["panel"], outline=V["danger"] if flash else V["line"],
              width=1.4 if flash else 1)
        if not self.state["modal"] and not self.popover:
            # 弹层打开时必须移开输入控件:widget 永远浮在画布元素之上,
            # 否则会挡住/拦截底部弹出的截止、清单选择面板
            c.create_window(x1 + self.m(14), iy + ih / 2, window=self.entry, anchor="w",
                            width=(x2 - self.m(50)) - x1 - self.m(24),
                            height=ih - self.m(10))
        elif not self.entry.get().strip():
            c.create_text(x1 + self.m(14), iy + ih / 2, text="记点什么… Enter 添加",
                          anchor="w", font=self.f_base, fill=V["muted"])
        abx = x2 - self.m(25)
        aby = iy + ih / 2
        r = self.m(18)
        c.create_oval(abx - r, aby - r, abx + r, aby + r, fill=V["accent"], outline="",
                      tags=("act:add",))
        ic_plus(c, abx, aby, self.m(14), "#ffffff", tags=("act:add",))

    def draw_chip_row(self, x1, x2, y, h, chips):
        """一行芯片,空间不足时自动收缩/省略后面的芯片。"""
        cx = x1
        gap = self.m(6)
        n = len(chips)
        for i, ch in enumerate(chips):
            remaining = x2 - cx - (n - 1 - i) * self.m(34)
            if remaining < self.m(30):
                break
            w = self.draw_chip(cx, y, h, ch["label"], ch.get("painter"),
                               active=ch.get("active", False), tag=ch["tag"],
                               col=ch.get("col"), dot=ch.get("dot", False),
                               maxw=max(self.m(26), remaining - self.m(24)))
            cx += w + gap

    def draw_chip(self, x, y, h, label, painter, active=False, tag="", col=None,
                  dot=False, maxw=200):
        c, V = self.canvas, self.V
        pad = self.m(9)
        icon_w = self.m(16) if (painter or dot) else 0
        label = self.fit_text(label, self.f_tiny, maxw)
        w = pad * 2 + icon_w + self.f_tiny.measure(label)
        fill = V["accent_soft"] if active else V["chip"]
        rrect(c, x, y, x + w, y + h, h / 2, fill=fill, outline="", tags=(tag,))
        tx = x + pad
        if painter:
            painter(c, tx + self.m(5), y + h / 2, self.m(10),
                    col or (V["accent_deep"] if active else V["muted"]), tags=(tag,))
            tx += icon_w
        elif dot:
            c.create_oval(tx, y + h / 2 - self.m(2.5), tx + self.m(5), y + h / 2 + self.m(2.5),
                          fill=col or V["accent"], outline="", tags=(tag,))
            tx += icon_w
        c.create_text(tx, y + h / 2, text=label, anchor="w", font=self.f_tiny,
                      fill=col or (V["accent_deep"] if active else V["ink_soft"]),
                      tags=(tag,))
        c.create_rectangle(x, y, x + w, y + h, fill="", outline="", width=0, tags=(tag,))
        return w

    # ---- popover ----

    def draw_popover(self):
        c, V, W, H = self.canvas, self.V, self.W, self.H
        pop = self.popover
        if pop["kind"] == "calendar":
            self.draw_calendar(pop)
            return
        opts = [(l["name"], l["id"]) for l in self.store.lists]
        opts.append(("＋ 新建清单…", "__new__"))
        pop["options"] = [v for _, v in opts]
        labels = [l for l, _ in opts]
        row_h = self.m(27)
        w = self.m(128)
        h = row_h * len(labels) + self.m(10)
        px = clamp(pop["x"] - self.m(10), self.m(8), W - w - self.m(8))
        py = pop["y"] - self.m(10)
        composer = self.layout.get("composer")
        if composer and pop["y"] >= composer[1] - self.m(2):
            # 从底部芯片行打开:整体放到芯片行上方,避开输入框
            py = composer[1] - h - self.m(4)
        py = clamp(py, self.m(52), H - h - self.m(8))
        self.pop_rect = (px, py, px + w, py + h)
        rrect(c, px, py, px + w, py + h, self.m(10), fill=V["panel"],
              outline=V["line"], width=1)
        for i, label in enumerate(labels):
            yy = py + self.m(5) + i * row_h
            prefix = ""
            cur = self.edit["list_id"] if (pop.get("ctx") == "em" and self.edit) \
                else self.quick["list"]
            if pop["options"][i] == cur:
                prefix = "✓ "
            tags = ("pop:%d" % i,)
            c.create_text(px + self.m(12), yy + row_h / 2, text=prefix + label,
                          anchor="w", font=self.f_small, fill=V["ink"], tags=tags)
            c.create_rectangle(px + 2, yy, px + w - 2, yy + row_h,
                               fill="", outline="", width=0, tags=tags)

    # ---- 日历选截止 ----

    def draw_calendar(self, pop):
        c, V, W, H = self.canvas, self.V, self.W, self.H
        today = datetime.date.today()
        if "year" not in pop:
            cur = self.edit["due"] if (pop.get("ctx") == "em" and self.edit) \
                else self.quick["due"]
            base = None
            if cur:
                try:
                    base = datetime.datetime.fromisoformat(cur)
                except Exception:
                    base = None
            anchor = base or datetime.datetime.now()
            pop["year"], pop["month"] = anchor.year, anchor.month
            pop["sel"] = base.date().isoformat() if base else None
            pop["hour"] = base.hour if base else 9
            pop["minute"] = base.minute if base else 0
        year, month = pop["year"], pop["month"]
        first_wd, days = calendar.monthrange(year, month)
        weeks = (first_wd + days + 6) // 7

        cell_w, cell_h = self.m(29), self.m(24)
        pad = self.m(8)
        head_h, wk_h = self.m(24), self.m(18)
        time_h, btn_h = self.m(30), self.m(26)
        w = cell_w * 7 + pad * 2
        h = pad * 2 + head_h + wk_h + weeks * cell_h + time_h + btn_h + self.m(4)
        px = clamp(pop["x"] - self.m(20), self.m(8), W - w - self.m(8))
        py = pop["y"] - self.m(10)
        composer = self.layout.get("composer")
        if composer and pop["y"] >= composer[1] - self.m(2):
            py = composer[1] - h - self.m(4)
        py = clamp(py, self.m(52), H - h - self.m(8))
        self.pop_rect = (px, py, px + w, py + h)

        rrect(c, px, py, px + w, py + h, self.m(10), fill=V["panel"],
              outline=V["line"], width=1)

        # 头部:‹ 2026年10月 › (点月份文字回到本月)
        hy = py + pad + head_h / 2
        nav_l = px + pad + self.m(9)
        nav_r = px + w - pad - self.m(9)
        for x, tg in ((nav_l, "pop:cal-prev"), (nav_r, "pop:cal-next")):
            s = -1 if x == nav_l else 1
            c.create_line(x + s * 4, hy - 5, x - s * 4, hy, x + s * 4, hy + 5,
                          fill=V["ink_soft"], width=1.6, capstyle="round",
                          joinstyle="round", tags=tg)
            c.create_rectangle(x - self.m(11), hy - self.m(10), x + self.m(11),
                               hy + self.m(10), fill="", outline="", width=0, tags=tg)
        label = "%d年%d月" % (year, month)
        lx = px + w / 2
        c.create_text(lx, hy, text=label, font=self.f_small, fill=V["ink"],
                      tags=("pop:cal-cur",))
        c.create_rectangle(lx - self.m(42), hy - self.m(11), lx + self.m(42),
                           hy + self.m(11), fill="", outline="", width=0,
                           tags=("pop:cal-cur",))

        # 星期表头(周一开头),周末用截止色
        wy = py + pad + head_h
        for i, name in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
            c.create_text(px + pad + i * cell_w + cell_w / 2, wy + wk_h / 2,
                          text=name, font=self.f_tiny,
                          fill=V["due"] if i >= 5 else V["muted"])

        # 日期格子
        grid_y = wy + wk_h
        sel = pop.get("sel")
        for i in range(days):
            d = datetime.date(year, month, i + 1)
            iso = d.isoformat()
            row, col = (first_wd + i) // 7, (first_wd + i) % 7
            x1 = px + pad + col * cell_w
            y1 = grid_y + row * cell_h
            cx0, cy0 = x1 + cell_w / 2, y1 + cell_h / 2
            is_sel, is_today = sel == iso, d == today
            if is_sel:
                rrect(c, x1 + 1, y1 + 1, x1 + cell_w - 1, y1 + cell_h - 1,
                      self.m(7), fill=V["accent_soft"], outline="")
            elif is_today:
                rrect(c, x1 + 1, y1 + 1, x1 + cell_w - 1, y1 + cell_h - 1,
                      self.m(7), fill="", outline=V["accent"], width=1.2)
            tags = ("pop:cal-day-" + iso,)
            c.create_text(cx0, cy0, text=str(i + 1), font=self.f_small,
                          fill=V["accent_deep"] if is_sel or is_today else V["ink"],
                          tags=tags)
            c.create_rectangle(x1, y1, x1 + cell_w, y1 + cell_h,
                               fill="", outline="", width=0, tags=tags)

        # 时间行: 时间 ▼08▲ : ▼30▲
        ty0 = grid_y + weeks * cell_h
        c.create_line(px + pad, ty0, px + w - pad, ty0, fill=V["line"])
        c.create_text(px + pad + self.m(4), ty0 + time_h / 2 + self.m(2),
                      text="时间", anchor="w", font=self.f_tiny, fill=V["muted"])

        def stepper(x, value, up_tag, down_tag):
            cy = ty0 + time_h / 2 + self.m(2)
            c.create_text(x, cy, text="%02d" % value, font=self.f_small, fill=V["ink"])
            ux = x + self.m(26)
            ic_chevron(c, ux, cy - self.m(6), self.m(9), V["muted"],
                       tags=(up_tag,), down=False)
            ic_chevron(c, ux, cy + self.m(7), self.m(9), V["muted"],
                       tags=(down_tag,), down=True)
            # 命中区:箭头列上半=加,下半=减(两个矩形不得重叠)
            c.create_rectangle(x - self.m(16), ty0 + self.m(2), x + self.m(36),
                               cy - self.m(1), fill="", outline="", width=0,
                               tags=(up_tag,))
            c.create_rectangle(x - self.m(16), cy + self.m(1), x + self.m(36),
                               ty0 + time_h, fill="", outline="", width=0,
                               tags=(down_tag,))

        xh = px + pad + cell_w * 2.1
        stepper(xh, pop["hour"], "pop:cal-hour-up", "pop:cal-hour-down")
        c.create_text(xh + self.m(36), ty0 + time_h / 2 + self.m(2), text=":",
                      font=self.f_small, fill=V["muted"])
        xm = px + pad + cell_w * 4.4
        stepper(xm, pop["minute"], "pop:cal-min-up", "pop:cal-min-down")

        # 底部按钮:快捷 + 清除 + 确定
        by = ty0 + time_h + self.m(4)
        c.create_text(px + pad + self.m(2), by + btn_h / 2, text="今天", font=self.f_tiny,
                      fill=V["accent_deep"], tags=("pop:cal-p0",))
        c.create_rectangle(px + pad - 2, by, px + pad + self.m(26), by + btn_h,
                           fill="", outline="", width=0, tags=("pop:cal-p0",))
        c.create_text(px + pad + self.m(36), by + btn_h / 2, text="明天", font=self.f_tiny,
                      fill=V["accent_deep"], tags=("pop:cal-p1",))
        c.create_rectangle(px + pad + self.m(32), by, px + pad + self.m(60), by + btn_h,
                           fill="", outline="", width=0, tags=("pop:cal-p1",))
        c.create_text(px + pad + self.m(70), by + btn_h / 2, text="下周一", font=self.f_tiny,
                      fill=V["accent_deep"], tags=("pop:cal-p3",))
        c.create_rectangle(px + pad + self.m(66), by, px + pad + self.m(94), by + btn_h,
                           fill="", outline="", width=0, tags=("pop:cal-p3",))
        c.create_text(px + pad + self.m(104), by + btn_h / 2, text="清除", font=self.f_tiny,
                      fill=V["danger"], tags=("pop:cal-clear",))
        c.create_rectangle(px + pad + self.m(100), by, px + pad + self.m(124),
                           by + btn_h, fill="", outline="", width=0,
                           tags=("pop:cal-clear",))
        bw, bh = self.m(44), self.m(22)
        bx2 = px + w - pad
        rrect(c, bx2 - bw, by + (btn_h - bh) / 2, bx2, by + (btn_h + bh) / 2,
              bh / 2, fill=V["accent"], outline="", tags=("pop:cal-ok",))
        c.create_text(bx2 - bw / 2, by + btn_h / 2, text="确定", font=self.f_tiny,
                      fill="#ffffff", tags=("pop:cal-ok",))
        c.create_rectangle(bx2 - bw, by, bx2, by + btn_h, fill="", outline="",
                           width=0, tags=("pop:cal-ok",))

    # ---- toast ----

    def draw_toast(self):
        c, V, W = self.canvas, self.V, self.W
        t = self.state["toast"]
        H = self.H
        ty = H - self.m(108)
        tw = self.f_small.measure(t["text"]) + self.m(30)
        if t.get("action"):
            tw += self.m(44)
        x1 = (W - tw) / 2
        x2 = x1 + tw
        rrect(c, x1, ty, x2, ty + self.m(30), self.m(15), fill=V["ink"], outline="")
        c.create_text(x1 + self.m(15), ty + self.m(15), text=t["text"], anchor="w",
                      font=self.f_small, fill="#ffffff")
        if t.get("action"):
            c.create_text(x2 - self.m(18), ty + self.m(15), text="撤销", anchor="e",
                          font=self.f_small, fill=V["accent_soft"], tags=("toast:undo",))
            c.create_rectangle(x2 - self.m(44), ty, x2, ty + self.m(30),
                               fill="", outline="", width=0, tags=("toast:undo",))

    # ================================================================ 设置面板

    def draw_settings(self):
        c, V, W, H = self.canvas, self.V, self.W, self.H
        pw = min(W - self.m(24), self.m(340))
        px = (W - pw) / 2
        py1 = self.m(10)
        py2 = H - self.m(10)
        c.create_rectangle(0, 0, W, H, fill=V["bg"], outline="", tags=("sm:back",))
        rrect(c, px, py1, px + pw, py2, self.m(14), fill=V["panel"],
              outline=V["line"], width=1, tags=("sm:panel",))
        pad = self.m(14)
        cx = px + pad
        cw = pw - pad * 2
        top_lim = py1 + self.m(36)
        bottom_lim = py2 - self.m(8)
        y = [py1 + self.m(12) - self.state["sm_scroll"]]

        def ok(h):
            return y[0] + h > top_lim and y[0] < bottom_lim

        def need(h):
            y[0] += h

        def label(txt, col=None, font=None, tag=()):
            c.create_text(cx, y[0] + self.m(9), text=txt, anchor="w",
                          font=font or self.f_tiny, fill=col or V["muted"], tags=tag)

        # 标题行
        if ok(self.m(30)):
            c.create_text(cx, y[0] + self.m(12), text="设置", anchor="w",
                          font=self.f_big, fill=V["ink"])
            ic_x(c, px + pw - pad - self.m(8), y[0] + self.m(12), self.m(12), V["muted"],
                 tags=("act:sm-close",))
            c.create_rectangle(px + pw - pad - self.m(24), y[0] - self.m(4),
                               px + pw - pad + self.m(6), y[0] + self.m(28),
                               fill="", outline="", width=0, tags=("act:sm-close",))
        need(self.m(32))
        if ok(2):
            c.create_line(cx, y[0], cx + cw, y[0], fill=V["line"])
        need(self.m(10))

        # 主题
        if ok(self.m(16)):
            label("主题(支持插件,放入 themes 目录即可)")
        need(self.m(16))
        themes = self._themes_cache or theme_api.scan_themes()[0]
        per = 3
        cw_card = (cw - self.m(8) * (per - 1)) / per
        ch_card = self.m(56)
        col_i = 0
        for t in themes:
            x0 = cx + col_i * (cw_card + self.m(8))
            if ok(ch_card):
                sel = t["id"] == self.store.settings.get("theme")
                rrect(c, x0, y[0], x0 + cw_card, y[0] + ch_card, self.m(10),
                      fill=V["card"], outline=V["accent"] if sel else V["line"],
                      width=2 if sel else 1, tags=("theme:" + t["id"],))
                sw = self.m(11)
                sx = x0 + self.m(10)
                for k in theme_api.SWATCH_KEYS[:4]:
                    c.create_oval(sx, y[0] + self.m(9), sx + sw, y[0] + self.m(9) + sw,
                                  fill=t["vars"].get(k, "#cccccc"), outline=V["line"])
                    sx += sw + self.m(4)
                c.create_text(x0 + self.m(9), y[0] + self.m(38),
                              text=self.fit_text(t["name"], self.f_tiny, cw_card - self.m(16)),
                              anchor="w", font=self.f_tiny,
                              fill=V["ink"] if sel else V["ink_soft"],
                              tags=("theme:" + t["id"],))
            col_i += 1
            if col_i >= per:
                col_i = 0
                need(ch_card + self.m(8))
        if col_i:
            need(ch_card + self.m(8))
        if ok(self.m(20)):
            self.text_btn(cx, y[0], "扫描主题文件夹", "act:sm-rescan")
        need(self.m(24))
        if ok(2):
            c.create_line(cx, y[0], cx + cw, y[0], fill=V["line"])
        need(self.m(10))

        # 不透明度
        if ok(self.m(14)):
            label("窗口不透明度")
        need(self.m(16))
        if ok(self.m(22)):
            tx1 = cx
            tx2 = cx + cw - self.m(44)
            self._opacity_track = (tx1, tx2)
            v = (self.geo["opacity"] - 0.4) / 0.6
            kx = tx1 + (tx2 - tx1) * v
            ky = y[0] + self.m(4)
            c.create_line(tx1, ky, tx2, ky, fill=V["chip"], width=self.m(5),
                          capstyle="round")
            c.create_line(tx1, ky, kx, ky, fill=V["accent"], width=self.m(5),
                          capstyle="round", tags=("hs:opacity",))
            r = self.m(7)
            c.create_oval(kx - r, ky - r, kx + r, ky + r, fill=V["accent"], outline="",
                          tags=("hs:opacity",))
            c.create_rectangle(tx1 - self.m(10), ky - self.m(13), tx2 + self.m(10),
                               ky + self.m(13), fill="", outline="", width=0,
                               tags=("hs:opacity",))
            c.create_text(tx2 + self.m(10), ky,
                          text="%d%%" % round(self.geo["opacity"] * 100),
                          anchor="w", font=self.f_tiny, fill=V["ink_soft"])
        need(self.m(24))

        # 开关
        if ok(self.m(20)):
            self.toggle_row(cx, y[0], cw, "悬浮置顶", "topmost", self.geo["topmost"])
        need(self.m(26))
        if ok(self.m(20)):
            self.toggle_row(cx, y[0], cw, "开机自启(静默后台)", "autostart", get_autostart())
        need(self.m(26))
        if ok(self.m(20)):
            self.toggle_row(cx, y[0], cw, "打开时提醒今日待办", "notify_due",
                            bool(self.store.settings.get("notify_due")))
        need(self.m(26))

        # 热键
        if ok(self.m(20)):
            label("显示/隐藏热键")
            hk_txt = self.store.settings.get("hotkey", "Ctrl+Alt+T")
            if not self.hotkey_ok:
                hk_txt += "(未注册)"
            hx = cx + cw - self.m(72)
            c.create_text(hx, y[0] + self.m(9), text=hk_txt, anchor="e",
                          font=self.f_small, fill=V["ink"])
            ic_chevron(c, hx + self.m(16), y[0] + self.m(10), self.m(11), V["muted"],
                       tags=("act:sm-hotkey-prev",), down=True)
            ic_chevron(c, hx + self.m(48), y[0] + self.m(10), self.m(11), V["muted"],
                       tags=("act:sm-hotkey-next",), down=False)
            c.create_rectangle(hx + self.m(4), y[0], cx + cw, y[0] + self.m(20),
                               fill="", outline="", width=0, tags=("act:sm-hotkey-next",))
        need(self.m(28))
        if ok(2):
            c.create_line(cx, y[0], cx + cw, y[0], fill=V["line"])
        need(self.m(10))

        # 清单管理
        if ok(self.m(14)):
            label("清单管理")
        need(self.m(18))
        for l in self.store.lists:
            if ok(self.m(20)):
                c.create_oval(cx, y[0] + self.m(5), cx + self.m(6), y[0] + self.m(11),
                              fill=V["accent"], outline="")
                c.create_text(cx + self.m(12), y[0] + self.m(8), text=l["name"],
                              anchor="w", font=self.f_small, fill=V["ink"])
                if l["id"] != "inbox":
                    dx = cx + cw - self.m(8)
                    tg = "act:list-del-" + l["id"]
                    ic_x(c, dx, y[0] + self.m(8), self.m(9), V["danger"], tags=(tg,))
                    c.create_rectangle(dx - self.m(10), y[0], dx + self.m(10),
                                       y[0] + self.m(20), fill="", outline="", width=0,
                                       tags=(tg,))
            need(self.m(22))
        if ok(self.m(20)):
            self.text_btn(cx, y[0], "＋ 新建清单", "act:list-new")
        need(self.m(24))
        if ok(2):
            c.create_line(cx, y[0], cx + cw, y[0], fill=V["line"])
        need(self.m(10))

        # 数据
        if ok(self.m(14)):
            label("数据")
        need(self.m(18))
        if ok(self.m(20)):
            bx = cx
            bx = self.text_btn(bx, y[0], "导出备份", "act:sm-export") + self.m(10)
            bx = self.text_btn(bx, y[0], "导入备份", "act:sm-import") + self.m(10)
            self.text_btn(bx, y[0], "打开数据文件夹", "act:sm-folder")
        need(self.m(24))
        if ok(self.m(20)):
            bx = cx
            bx = self.text_btn(bx, y[0], "重置窗口位置", "act:sm-resetwin") + self.m(10)
            bx = self.text_btn(bx, y[0], "清空已完成", "act:sm-clear-done") + self.m(10)
            self.text_btn(bx, y[0], "清空回收站", "act:sm-empty-trash")
        need(self.m(28))

        # 退出
        if ok(self.m(30)):
            rrect(c, cx, y[0], cx + cw, y[0] + self.m(30), self.m(15), fill="",
                  outline=V["danger"], tags=("act:sm-quit",))
            c.create_text(cx + cw / 2, y[0] + self.m(15), text="退出应用",
                          font=self.f_btn, fill=V["danger"], tags=("act:sm-quit",))
            c.create_rectangle(cx, y[0], cx + cw, y[0] + self.m(30), fill="",
                               outline="", width=0, tags=("act:sm-quit",))
        need(self.m(38))
        if ok(self.m(14)):
            c.create_text(cx + cw / 2, y[0], anchor="center", font=self.f_tiny,
                          fill=V["muted"],
                          text="数据在 data/todo.json · 关闭按钮 = 隐藏到后台")

    def text_btn(self, x, y, text, tag):
        c, V = self.canvas, self.V
        c.create_text(x, y + self.m(8), text=text, anchor="w", font=self.f_small,
                      fill=V["accent_deep"], tags=(tag,))
        w = self.f_small.measure(text) + self.m(8)
        c.create_rectangle(x - 2, y, x + w, y + self.m(17), fill="", outline="",
                           width=0, tags=(tag,))
        return x + w

    def toggle_row(self, x, y, w, text, key, on):
        c, V = self.canvas, self.V
        c.create_text(x, y + self.m(9), text=text, anchor="w", font=self.f_small,
                      fill=V["ink"])
        tx2 = x + w
        tx1 = tx2 - self.m(34)
        toggle(c, tx1, y + self.m(1), tx2, y + self.m(17), on,
               V["accent"], V["chip"], tags=("tgl:" + key,))

    # ================================================================ 编辑弹窗

    def draw_edit_modal(self):
        c, V, W, H = self.canvas, self.V, self.W, self.H
        lx, ly, lw, ly2 = self.layout["list"]
        pw = min(lw - self.m(8), self.m(330))
        ph = self.m(288)
        px = lx + (lw - pw) / 2
        py = max(self.m(8), ly + (ly2 - ly - ph) / 2)
        c.create_rectangle(0, 0, W, H, fill=V["bg"], outline="", tags=("em:back",))
        rrect(c, px, py, px + pw, py + ph, self.m(14), fill=V["panel"],
              outline=V["line"], width=1, tags=("em:panel",))
        pad = self.m(14)
        cx = px + pad
        cw = pw - pad * 2
        y = py + self.m(12)
        c.create_text(cx, y + self.m(6), text="编辑任务", anchor="w",
                      font=self.f_big, fill=V["ink"])
        ic_x(c, px + pw - pad - self.m(8), y + self.m(6), self.m(12), V["muted"],
             tags=("em:back",))
        c.create_rectangle(px + pw - pad - self.m(24), y - self.m(8),
                           px + pw - pad + self.m(6), y + self.m(20),
                           fill="", outline="", width=0, tags=("em:back",))
        y += self.m(34)
        rrect(c, cx, y, cx + cw, y + self.m(30), self.m(8), fill=V["card"],
              outline=V["line"])
        if not self.popover:
            c.create_window(cx + self.m(10), y + self.m(15), window=self.edit_title,
                            anchor="w", width=cw - self.m(20), height=self.m(22))
        y += self.m(38)
        rrect(c, cx, y, cx + cw, y + self.m(64), self.m(8), fill=V["card"],
              outline=V["line"])
        if not self.popover:
            c.create_window(cx + self.m(8), y + self.m(6), window=self.edit_notes,
                            anchor="nw", width=cw - self.m(16), height=self.m(52))
        y += self.m(74)
        ch_h = self.m(22)
        due_txt = due_label(self.edit["due"]) if self.edit["due"] else "截止"
        pri_txt = {0: "优先级", 1: "中", 2: "高"}[self.edit["pri"]]
        lname = self.store.list_name(self.edit["list_id"]) or "收集箱"
        self.draw_chip_row(cx, cx + cw, y, ch_h, [
            dict(label="每日", painter=ic_repeat, active=self.edit["daily"],
                 tag="chip:em-daily"),
            dict(label=due_txt, painter=ic_calendar, active=bool(self.edit["due"]),
                 tag="chip:em-due", col=V["due"] if self.edit["due"] else None),
            dict(label=pri_txt, painter=ic_flag, active=bool(self.edit["pri"]),
                 tag="chip:em-pri",
                 col={0: None, 1: V["due"], 2: V["danger"]}[self.edit["pri"]]),
            dict(label=lname, active=self.edit["list_id"] != "inbox",
                 tag="chip:em-list", dot=True),
        ])
        y += ch_h + self.m(16)
        bw = self.m(74)
        bh = self.m(28)
        rrect(c, cx, y, cx + bw, y + bh, bh / 2, fill=V["accent"], outline="",
              tags=("act:em-save",))
        c.create_text(cx + bw / 2, y + bh / 2, text="保存", font=self.f_btn,
                      fill="#ffffff", tags=("act:em-save",))
        c.create_rectangle(cx, y, cx + bw, y + bh, fill="", outline="", width=0,
                           tags=("act:em-save",))
        rrect(c, cx + bw + self.m(10), y, cx + bw * 2 + self.m(10), y + bh, bh / 2,
              fill="", outline=V["danger"], tags=("act:em-delete",))
        c.create_text(cx + bw * 1.5 + self.m(10), y + bh / 2, text="移入回收站",
                      font=self.f_small, fill=V["danger"], tags=("act:em-delete",))
        c.create_rectangle(cx + bw + self.m(10), y, cx + bw * 2 + self.m(10), y + bh,
                           fill="", outline="", width=0, tags=("act:em-delete",))
        c.create_text(cx + cw, y + bh / 2, text="取消", font=self.f_small,
                      fill=V["muted"], anchor="e", tags=("act:em-cancel",))
        c.create_rectangle(cx + cw - self.m(36), y, cx + cw, y + bh, fill="",
                           outline="", width=0, tags=("act:em-cancel",))

    def draw_prompt(self):
        c, V, W, H = self.canvas, self.V, self.W, self.H
        pw = self.m(244)
        ph = self.m(124)
        px = (W - pw) / 2
        py = (H - ph) / 2
        c.create_rectangle(0, 0, W, H, fill=V["bg"], outline="", tags=("sm:back",))
        rrect(c, px, py, px + pw, py + ph, self.m(14), fill=V["panel"],
              outline=V["line"], width=1, tags=("sm:panel",))
        pad = self.m(14)
        cx = px + pad
        cw = pw - pad * 2
        y = py + self.m(12)
        c.create_text(cx, y + self.m(6), text=(self.prompt or {}).get("title", "输入"),
                      anchor="w", font=self.f_big, fill=V["ink"])
        y += self.m(36)
        rrect(c, cx, y, cx + cw, y + self.m(30), self.m(8), fill=V["card"],
              outline=V["line"])
        if not self.popover:
            c.create_window(cx + self.m(10), y + self.m(15), window=self.prompt_entry,
                            anchor="w", width=cw - self.m(20), height=self.m(22))
        y += self.m(42)
        bw = self.m(70)
        bh = self.m(26)
        rrect(c, cx, y, cx + bw, y + bh, bh / 2, fill=V["accent"], outline="",
              tags=("act:prompt-ok",))
        c.create_text(cx + bw / 2, y + bh / 2, text="确定", font=self.f_btn,
                      fill="#ffffff", tags=("act:prompt-ok",))
        c.create_rectangle(cx, y, cx + bw, y + bh, fill="", outline="", width=0,
                           tags=("act:prompt-ok",))
        c.create_text(cx + cw, y + bh / 2, text="取消", font=self.f_small,
                      fill=V["muted"], anchor="e", tags=("act:prompt-cancel",))
        c.create_rectangle(cx + cw - self.m(36), y, cx + cw, y + bh, fill="",
                           outline="", width=0, tags=("act:prompt-cancel",))


# ---------------------------------------------------------------- 自启注册

def set_autostart(enable):
    """写注册表 HKCU Run,指向 pythonw + --hidden。"""
    try:
        import winreg
        import sys
        exe = sys.executable
        if exe.lower().endswith("python.exe"):
            exe = exe[:-10] + "pythonw.exe"
        app_py = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "app.py"))
        val = '"%s" "%s" --hidden' % (exe, app_py)
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, "TodoApp", 0, winreg.REG_SZ, val)
        else:
            try:
                winreg.DeleteValue(key, "TodoApp")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def get_autostart():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.QueryValueEx(key, "TodoApp")
        winreg.CloseKey(key)
        return True
    except Exception:
        return False
