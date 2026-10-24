# -*- coding: utf-8 -*-
"""数据层:待办 / 每日任务 / 清单 / 回收站 的存储与业务逻辑。

数据保存在 data/todo.json,窗口几何等保存在 data/window.json。
"""
import json
import os
import threading
import time
import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("TODO_DATA_DIR") or os.path.join(APP_DIR, "data")
DATA_FILE = os.path.join(DATA_DIR, "todo.json")
WINDOW_FILE = os.path.join(DATA_DIR, "window.json")

DEFAULT_SETTINGS = {
    "theme": "sage",          # 当前主题 id(内置或 themes/ 目录里的插件)
    "notify_due": True,       # 打开窗口时提醒今日待办
    "hotkey": "Ctrl+Alt+Space", # 全局显示/隐藏热键
}

DEFAULT_WINDOW = {
    "x": None, "y": None,     # None = 屏幕右上角默认位置
    "w": 360, "h": 620,
    "topmost": True,          # 悬浮置顶
    "opacity": 1.0,           # 0.4 ~ 1.0
}


def today_str():
    return datetime.date.today().isoformat()


def yesterday_str():
    return (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def due_date_part(due):
    """截止的日期部分(兼容 'YYYY-MM-DD' 与 'YYYY-MM-DD HH:MM')。"""
    return (due or "")[:10]


def due_overdue(due):
    """是否已逾期:带时刻的按具体时刻比较,纯日期按当天。"""
    if not due:
        return False
    try:
        if len(due) > 10:
            return datetime.datetime.fromisoformat(due) < datetime.datetime.now()
        return datetime.date.fromisoformat(due) < datetime.date.today()
    except Exception:
        return False


def new_task(tid, title, **kw):
    t = {
        "id": tid,
        "title": title,
        "notes": "",
        "done": False,          # 普通任务是否完成
        "done_at": None,        # 完成时间
        "created": now_str(),
        "due": None,            # 截止日期 'YYYY-MM-DD'
        "priority": 0,          # 0 无 1 中 2 高
        "list_id": "inbox",
        "daily": False,         # 是否每日任务
        "last_done": None,      # 每日任务最近一次打卡日期
        "streak": 0,            # 连续打卡天数
        "best": 0,              # 最好连续纪录
        "deleted": False,       # 回收站标记
        "order": time.time(),   # 手动排序用(浮点,可插入中间值)
    }
    t.update(kw)
    return t


class Store:
    """线程安全的内存模型 + JSON 落盘。"""

    def __init__(self):
        self.lock = threading.RLock()
        self.settings = dict(DEFAULT_SETTINGS)
        self.lists = [{"id": "inbox", "name": "收集箱"}]
        self.tasks = []
        self.seq = 1
        self._dirty = False
        self.load()

    # ---------- 持久化 ----------

    def load(self):
        with self.lock:
            raw = {}
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception:
                raw = {}
            self.settings = {**DEFAULT_SETTINGS, **(raw.get("settings") or {})}
            lists = raw.get("lists")
            self.lists = lists if isinstance(lists, list) and lists else [{"id": "inbox", "name": "收集箱"}]
            tasks = []
            for t in raw.get("tasks") or []:
                base = new_task(t.get("id", 0), t.get("title", ""))
                base.update({k: v for k, v in t.items() if k in base})
                tasks.append(base)
            self.tasks = tasks
            self.seq = raw.get("seq") or (max([t["id"] for t in tasks] or [0]) + 1)
            if not any(l.get("id") == "inbox" for l in self.lists):
                self.lists.insert(0, {"id": "inbox", "name": "收集箱"})

    def save(self):
        with self.lock:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = DATA_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "version": 1,
                    "settings": self.settings,
                    "lists": self.lists,
                    "tasks": self.tasks,
                    "seq": self.seq,
                }, f, ensure_ascii=False, indent=1)
            os.replace(tmp, DATA_FILE)
        self._dirty = False

    def save_later(self):
        self._dirty = True

    @property
    def dirty(self):
        return self._dirty

    def flush_if_dirty(self):
        if self._dirty:
            self.save()

    # ---------- 清单 ----------

    def list_name(self, lid):
        for l in self.lists:
            if l["id"] == lid:
                return l["name"]
        return ""

    def add_list(self, name):
        with self.lock:
            lid = "l%d" % (int(time.time() * 1000) % 1000000000)
            self.lists.append({"id": lid, "name": name})
            self.save_later()
            return lid

    def rename_list(self, lid, name):
        with self.lock:
            for l in self.lists:
                if l["id"] == lid and lid != "inbox":
                    l["name"] = name
                    self.save_later()
                    return True
            return False

    def delete_list(self, lid):
        """删除清单,任务移回收集箱,回收站里的一并移动。"""
        with self.lock:
            if lid == "inbox" or len(self.lists) <= 1:
                return False
            self.lists = [l for l in self.lists if l["id"] != lid]
            for t in self.tasks:
                if t["list_id"] == lid:
                    t["list_id"] = "inbox"
            if self.settings.get("last_list") == lid:
                self.settings["last_list"] = "inbox"
            self.save_later()
            return True

    # ---------- 任务 CRUD ----------

    def get(self, tid):
        for t in self.tasks:
            if t["id"] == tid:
                return t
        return None

    def add(self, title, daily=False, due=None, priority=0, list_id="inbox", notes=""):
        with self.lock:
            t = new_task(self.seq, title, daily=daily, due=due,
                         priority=priority, list_id=list_id, notes=notes)
            self.seq += 1
            self.tasks.append(t)
            self.save_later()
            return t

    def update(self, tid, **patch):
        with self.lock:
            t = self.get(tid)
            if not t:
                return None
            for k, v in patch.items():
                if k in t:
                    t[k] = v
            self.save_later()
            return t

    def delete(self, tid):
        """移入回收站(软删除)。"""
        return self.update(tid, deleted=True)

    def restore(self, tid):
        return self.update(tid, deleted=False)

    def purge(self, tid):
        with self.lock:
            self.tasks = [t for t in self.tasks if t["id"] != tid]
            self.save_later()

    def empty_trash(self):
        with self.lock:
            self.tasks = [t for t in self.tasks if not t["deleted"]]
            self.save_later()

    def clear_done(self):
        """已完成(普通任务)移入回收站。"""
        with self.lock:
            n = 0
            for t in self.tasks:
                if t["done"] and not t["deleted"] and not t["daily"]:
                    t["deleted"] = True
                    n += 1
            self.save_later()
            return n

    # ---------- 打勾与每日任务 ----------

    def is_done_today(self, t):
        if t["daily"]:
            return t["last_done"] == today_str()
        return bool(t["done"])

    def toggle(self, tid):
        """打勾/取消。每日任务按自然日打卡并维护连续天数。"""
        with self.lock:
            t = self.get(tid)
            if not t:
                return t
            if t["daily"]:
                if t["last_done"] == today_str():
                    t["last_done"] = None
                    t["streak"] = max(0, t["streak"] - 1)
                else:
                    prev = t["last_done"]
                    t["last_done"] = today_str()
                    if prev == yesterday_str() or t["streak"] == 0:
                        t["streak"] += 1
                    else:
                        t["streak"] = 1
                    t["best"] = max(t.get("best", 0), t["streak"])
            else:
                t["done"] = not t["done"]
                t["done_at"] = now_str() if t["done"] else None
            self.save_later()
            return t

    # ---------- 视图 ----------

    def visible(self):
        return [t for t in self.tasks if not t["deleted"]]

    def trash(self):
        return [t for t in self.tasks if t["deleted"]]

    def done_normal_today(self):
        today = today_str()
        return [t for t in self.visible()
                if not t["daily"] and t["done"] and (t.get("done_at") or "").startswith(today)]

    def today_sections(self):
        """今日视图:每日打卡 / 待办(逾期在前) / 已完成。"""
        daily = [t for t in self.visible() if t["daily"]]
        daily.sort(key=lambda t: (0 if self.is_done_today(t) else 1, t["order"]))

        todo = [t for t in self.visible() if not t["daily"] and not t["done"]]
        todo.sort(key=lambda t: (t["due"] is None,
                                 t["due"] or "",
                                 t["order"]))
        done = self.done_normal_today()
        done.sort(key=lambda t: t.get("done_at") or "")
        return daily, todo, done

    def all_sections(self, list_id=None, keyword=""):
        """全部视图:按清单分组(可按清单/关键词过滤)。"""
        kw = keyword.strip().lower()
        out = []
        for l in self.lists:
            if list_id and l["id"] != list_id:
                continue
            ts = []
            for t in self.visible():
                if t["list_id"] != l["id"] or t["done"]:
                    continue
                if kw and kw not in t["title"].lower() and kw not in (t["notes"] or "").lower():
                    continue
                ts.append(t)
            ts.sort(key=lambda t: (not t["daily"], t["due"] or "9999", t["order"]))
            if ts:
                out.append((l["name"], ts))
        # 清单被删后遗留的任务归入"其他"
        known = {l["id"] for l in self.lists}
        orphans = [t for t in self.visible()
                   if t["list_id"] not in known and t["list_id"] != "inbox" and not t["done"]]
        orphans = [t for t in orphans
                   if not kw or kw in t["title"].lower() or kw in (t["notes"] or "").lower()]
        if orphans and not list_id:
            orphans.sort(key=lambda t: (not t["daily"], t["due"] or "9999", t["order"]))
            out.append(("其他", orphans))
        # 搜索时也检索已完成
        if kw:
            hit_done = [t for t in self.visible()
                        if t["done"] and (kw in t["title"].lower() or kw in (t["notes"] or "").lower())]
            if hit_done:
                out.append(("已完成的搜索结果", hit_done))
        return out

    # ---------- 今日进度 ----------

    def today_progress(self):
        daily, todo, done = self.today_sections()
        total = len(daily) + len(todo) + len(done)
        done_n = sum(1 for t in daily if self.is_done_today(t)) + len(done)
        return done_n, total

    def due_summary(self):
        """今日待提醒:今天应完成而未完成的数量与逾期数。

        带时刻的截止:日期<=今天算"今天应完成";时刻已过才算逾期。
        纯日期截止:当天(含)以前算应完成,昨天以前算逾期。
        """
        today = today_str()
        undone = [t for t in self.visible()
                  if not t["daily"] and not t["done"] and t["due"]
                  and due_date_part(t["due"]) <= today]
        overdue = [t for t in undone if due_overdue(t["due"])]
        daily_left = [t for t in self.visible() if t["daily"] and not self.is_done_today(t)]
        return len(undone) + len(daily_left), len(overdue)

    # ---------- 拖拽排序 ----------

    def reorder(self, dragged_id, target_id, place_after):
        """把 dragged 插到 target 前/后,取邻居 order 的中值。"""
        with self.lock:
            dragged = self.get(dragged_id)
            target = self.get(target_id)
            if not dragged or not target or dragged is target:
                return
            siblings = sorted([t for t in self.visible()
                               if not t["done"] and t["order"] is not None],
                              key=lambda t: t["order"])
            try:
                i = siblings.index(target)
            except ValueError:
                return
            siblings.remove(dragged) if dragged in siblings else None
            try:
                i = siblings.index(target)
            except ValueError:
                i = 0
            j = i + 1 if place_after else i
            prev_o = siblings[j - 1]["order"] if j > 0 else None
            next_o = siblings[j]["order"] if j < len(siblings) else None
            if prev_o is None and next_o is None:
                dragged["order"] = time.time()
            elif prev_o is None:
                dragged["order"] = next_o - 1.0
            elif next_o is None:
                dragged["order"] = prev_o + 1.0
            else:
                dragged["order"] = (prev_o + next_o) / 2.0
            self.save_later()

    # ---------- 导入导出 ----------

    def export_payload(self):
        with self.lock:
            return {
                "version": 1,
                "settings": self.settings,
                "lists": self.lists,
                "tasks": self.tasks,
                "seq": self.seq,
                "exported_at": now_str(),
            }

    def import_payload(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
            raise ValueError("文件格式不对:缺少 tasks 列表")
        with self.lock:
            self.settings = {**DEFAULT_SETTINGS, **(payload.get("settings") or {})}
            lists = payload.get("lists")
            self.lists = lists if isinstance(lists, list) and lists else [{"id": "inbox", "name": "收集箱"}]
            tasks = []
            for t in payload["tasks"]:
                base = new_task(t.get("id", 0), t.get("title", ""))
                base.update({k: v for k, v in t.items() if k in base})
                tasks.append(base)
            self.tasks = tasks
            self.seq = payload.get("seq") or (max([t["id"] for t in tasks] or [0]) + 1)
            if not any(l.get("id") == "inbox" for l in self.lists):
                self.lists.insert(0, {"id": "inbox", "name": "收集箱"})
            self.save()
