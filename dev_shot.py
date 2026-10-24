# -*- coding: utf-8 -*-
"""开发辅助:启动真实窗口并截图到 dev_shots/(发布前可删除)。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["TODO_DATA_DIR"] = tempfile.mkdtemp(prefix="todo-demo-")
from app import enable_dpi_awareness, APP_DIR  # noqa: E402

enable_dpi_awareness()
import tkinter as tk  # noqa: E402
from store import Store  # noqa: E402
from ui import TodoApp, iso_after  # noqa: E402

OUT = os.path.join(APP_DIR, "dev_shots")
os.makedirs(OUT, exist_ok=True)

store = Store()
t1 = store.add("整理下周会议纪要", due=iso_after(0), priority=2)
t2 = store.add("给绿植浇水", notes="北阳台的两盆,周六早上浇透一次。", priority=1)
t3 = store.add("预约牙医检查", due=iso_after(3))
t4 = store.add("回复张老师的邮件")
t5 = store.add("晚饭后散步半小时")
d1 = store.add("晨间拉伸 10 分钟", daily=True)
d2 = store.add("睡前阅读 30 分钟", daily=True)
store.toggle(d2["id"])
td = store.add("去超市买菜", due=iso_after(0))
store.toggle(td["id"])
tx = store.add("旧版方案草稿", notes="已并入新文档,不再需要。")
store.delete(tx["id"])

root = tk.Tk()
root.withdraw()
app = TodoApp(root, store, start_hidden=False)
for _ in range(40):
    root.update()


def shot(name):
    root.update_idletasks()
    root.update()
    for _ in range(8):
        root.update()
    import PIL.ImageGrab as IG
    x = root.winfo_rootx()
    y = root.winfo_rooty()
    w = root.winfo_width()
    h = root.winfo_height()
    IG.grab(bbox=(x, y, x + w, y + h)).save(os.path.join(OUT, name))
    print("saved", name)


shot("1_today.png")

app.open_edit(t2["id"])
for _ in range(10):
    root.update()
shot("2_edit.png")
app.close_edit()

app.state["modal"] = "settings"
app.draw()
for _ in range(10):
    root.update()
shot("3_settings.png")
app.close_modal()

app.apply_theme("mist")
app.state["tab"] = "all"
app.draw()
shot("4_all_mist.png")

root.geometry("320x560+%d+%d" % (root.winfo_x(), root.winfo_y()))
for _ in range(20):
    root.update()
shot("5_small_mist.png")

app.apply_theme("sage")
app.state["tab"] = "today"
root.geometry("%dx%d+%d+%d" % (app.geo["w"], app.geo["h"], root.winfo_x(), root.winfo_y()))
for _ in range(20):
    root.update()
shot("6_today_sage.png")

root.destroy()
print("DONE ->", OUT)
