# -*- coding: utf-8 -*-
"""圆形时钟皮肤 —— 异形 UI 示例(B 路线脚本插件)。

整个界面接管为一个圆盘:中央进度环 + 今日待办速览,
点击任务圆点即打勾,底部两个小圆钮 = 设置 / 收起。
悬浮窗本身变成圆形(透明窗体 + 全量自绘),托盘/热键/数据逻辑全部复用。

可覆盖的钩子见 themes/README.md;任何一处出错,主程序自动回落默认绘制。
"""
import datetime

from ui_widgets import ic_gear, ic_minus

WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def on_apply(app):
    # 圆形窗体:尺寸 360x400,圆角拉到一半即近似圆
    app.set_window_shape(radius=180, w=360, h=400)


def draw(app):
    c, V = app.canvas, app.V
    W, H = app.root.winfo_width(), app.root.winfo_height()
    if W < 60 or H < 60:
        return
    app.W, app.H = W, H
    c.delete("all")
    cx, cy = W / 2.0, H / 2.0
    R = min(W, H) / 2.0 - 3
    # 上部 1/4 圆为可拖动区
    app.layout = {"tb": (cx - R, cy - R, cx + R, cy - R * 0.35)}

    # 表盘
    c.create_oval(cx - R, cy - R, cx + R, cy + R, fill=V["bg"],
                  outline=V["border"], width=2)
    c.create_oval(cx - R + 7, cy - R + 7, cx + R - 7, cy + R - 7,
                  outline=V["chip"], width=1)

    now = datetime.datetime.now()
    done_n, total = app.store.today_progress()
    _, overdue = app.store.due_summary()

    # 顶部:标题 + 日期(拖动区)
    c.create_text(cx, cy - R * 0.66, text="待办", font=app.f_title,
                  fill=V["ink"], tags=("act:tb",))
    c.create_text(cx, cy - R * 0.66 + app.m(17),
                  text="%d月%d日 · %s" % (now.month, now.day, WEEK[now.weekday()]),
                  font=app.f_tiny, fill=V["muted"], tags=("act:tb",))

    # 中央进度环(整体上移,给下方任务行留空间)
    ring_cy = cy - R * 0.22
    r1 = R * 0.34
    c.create_oval(cx - r1, ring_cy - r1, cx + r1, ring_cy + r1, outline=V["chip"],
                  width=app.m(5))
    if total:
        c.create_arc(cx - r1, ring_cy - r1, cx + r1, ring_cy + r1, start=90,
                     extent=-360.0 * done_n / total, style="arc",
                     outline=V["accent"], width=app.m(5))
    c.create_text(cx, ring_cy - app.m(4), text="%d/%d" % (done_n, total),
                  font=app.f_big, fill=V["ink"])
    c.create_text(cx, ring_cy + app.m(13), text="今日进度", font=app.f_tiny,
                  fill=V["muted"])
    if overdue:
        c.create_text(cx, ring_cy + app.m(27), text="逾期 %d 项" % overdue,
                      font=app.f_tiny, fill=V["danger"])

    # 今日速览:最多 4 行,点整行即打勾/取消
    rows = []
    for t in app.store.visible():
        if t["daily"]:
            rows.append(t)
    for t in app.store.visible():
        if not t["daily"] and not t["done"]:
            rows.append(t)
    rows.sort(key=lambda t: (0 if not app.store.is_done_today(t) else 1,
                             t["due"] or "9999", t["order"]))
    y = cy + R * 0.20
    max_y = cy + R * 0.60
    for t in rows[:4]:
        if y > max_y:
            break
        done_now = app.store.is_done_today(t)
        dot_x = cx - R * 0.52
        col = V["accent"] if done_now else V["muted"]
        r = app.m(5)
        tag = ("task:%d:check" % t["id"],)
        c.create_oval(dot_x - r, y - r, dot_x + r, y + r,
                      fill=col if done_now else V["card"],
                      outline=V["muted"], width=1.2, tags=tag)
        title = _fit(app, t["title"], R * 0.9)
        c.create_text(dot_x + r + app.m(8), y, text=title, anchor="w",
                      font=app.f_small,
                      fill=V["muted"] if done_now else V["ink"],
                      tags=tag)
        c.create_rectangle(dot_x - r - 3, y - app.m(10), cx + R * 0.55,
                           y + app.m(10), fill="", outline="", width=0, tags=tag)
        y += app.m(22)
    if not rows:
        c.create_text(cx, cy + R * 0.4, text="今天没有待办", font=app.f_small,
                      fill=V["muted"])

    # 底部小圆钮:设置 / 收起
    by = cy + R * 0.78
    for bx, painter, tag in ((cx - R * 0.3, ic_gear, "act:btn-settings"),
                             (cx + R * 0.3, ic_minus, "act:btn-hide")):
        r = app.m(13)
        c.create_oval(bx - r, by - r, bx + r, by + r, fill=V["chip"],
                      outline=V["line"], tags=(tag,))
        painter(c, bx, by, app.m(13), V["ink_soft"], tags=(tag,))


def _fit(app, text, max_px):
    font = app.f_small
    if font.measure(text) <= max_px:
        return text
    while text and font.measure(text + "…") > max_px:
        text = text[:-1]
    return text + "…"
