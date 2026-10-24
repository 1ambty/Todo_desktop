# -*- coding: utf-8 -*-
"""Canvas 基础组件:圆角矩形 + 全套矢量线性图标(随主题色)。"""
import math


def rrect(c, x1, y1, x2, y2, r=10, **kw):
    """圆角矩形(smooth 多边形配方,填充与描边都平滑)。"""
    r = max(0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- 图标
# 约定:ic_xxx(c, cx, cy, s, color, tags=()) —— (cx,cy)为中心, s 为盒尺寸。

def _line(c, x1, y1, x2, y2, col, tags=(), w=None):
    return c.create_line(x1, y1, x2, y2, fill=col, tags=tags, width=w or 1.6,
                         capstyle="round", joinstyle="round")


def ic_search(c, x, y, s, col, tags=()):
    r = s * 0.30
    c.create_oval(x - r * 1.4, y - r * 1.4, x + r * 0.5, y + r * 0.5,
                  outline=col, width=1.6, tags=tags)
    _line(c, x + r * 0.7, y + r * 0.7, x + s * 0.36, y + s * 0.36, col, tags)


def ic_pin(c, x, y, s, col, tags=()):
    """定位钉(置顶)。"""
    r = s * 0.16
    c.create_oval(x - r, y - s * 0.42, x + r, y - s * 0.42 + r * 2, fill=col, outline="", tags=tags)
    c.create_polygon(x - s * 0.17, y - s * 0.10, x + s * 0.17, y - s * 0.10, x, y + s * 0.16,
                     fill=col, outline="", tags=tags)
    _line(c, x, y + s * 0.16, x, y + s * 0.44, col, tags)


def ic_gear(c, x, y, s, col, tags=()):
    r = s * 0.26
    c.create_oval(x - r, y - r, x + r, y + r, outline=col, width=1.6, tags=tags)
    r2 = s * 0.40
    for i in range(8):
        a = i * 3.14159265 / 4
        _line(c, x + r * 0.98 * math.cos(a), y + r * 0.98 * math.sin(a),
              x + r2 * math.cos(a), y + r2 * math.sin(a), col, tags, w=1.8)
    r3 = s * 0.09
    c.create_oval(x - r3, y - r3, x + r3, y + r3, fill=col, outline="", tags=tags)


def ic_minus(c, x, y, s, col, tags=()):
    _line(c, x - s * 0.30, y, x + s * 0.30, y, col, tags, w=2.0)


def ic_plus(c, x, y, s, col, tags=(), w=None):
    _line(c, x - s * 0.30, y, x + s * 0.30, y, col, tags, w or 2.0)
    _line(c, x, y - s * 0.30, x, y + s * 0.30, col, tags, w or 2.0)


def ic_repeat(c, x, y, s, col, tags=()):
    """循环箭头(每日任务)。"""
    r = s * 0.30
    c.create_arc(x - r, y - r, x + r, y + r, start=25, extent=130, style="arc",
                 outline=col, width=1.7, tags=tags)
    c.create_arc(x - r, y - r, x + r, y + r, start=205, extent=130, style="arc",
                 outline=col, width=1.7, tags=tags)
    # 两个小箭头
    c.create_polygon(x + r * 0.92, y - r * 0.38, x + r * 0.28, y - r * 0.48,
                     x + r * 0.62, y + r * 0.05, fill=col, outline="", tags=tags)
    c.create_polygon(x - r * 0.92, y + r * 0.38, x - r * 0.28, y + r * 0.48,
                     x - r * 0.62, y - r * 0.05, fill=col, outline="", tags=tags)


def ic_flag(c, x, y, s, col, tags=()):
    _line(c, x - s * 0.22, y - s * 0.38, x - s * 0.22, y + s * 0.40, col, tags, w=1.8)
    c.create_polygon(x - s * 0.22, y - s * 0.38, x + s * 0.32, y - s * 0.26,
                     x - s * 0.22, y - s * 0.08, fill=col, outline="", tags=tags)


def ic_trash(c, x, y, s, col, tags=()):
    rrect(c, x - s * 0.24, y - s * 0.12, x + s * 0.24, y + s * 0.40, r=3,
          outline=col, width=1.5, tags=tags)
    _line(c, x - s * 0.34, y - s * 0.12, x + s * 0.34, y - s * 0.12, col, tags)
    _line(c, x - s * 0.10, y - s * 0.12, x - s * 0.10, y - s * 0.30, col, tags)
    _line(c, x + s * 0.10, y - s * 0.12, x + s * 0.10, y - s * 0.30, col, tags)
    _line(c, x - s * 0.07, y + 0.0, x - s * 0.07, y + s * 0.26, col, tags)
    _line(c, x + s * 0.07, y + 0.0, x + s * 0.07, y + s * 0.26, col, tags)


def ic_pencil(c, x, y, s, col, tags=()):
    _line(c, x + s * 0.10, y - s * 0.34, x + s * 0.34, y - s * 0.10, col, tags, w=1.8)
    c.create_polygon(x - s * 0.34, y + s * 0.34, x - s * 0.26, y + s * 0.02,
                     x - s * 0.02, y + s * 0.26, fill=col, outline="", tags=tags)
    c.create_polygon(x - s * 0.26, y + s * 0.02, x + s * 0.24, y - s * 0.28,
                     x + s * 0.34, y - s * 0.10, x + s * 0.02, y + s * 0.26,
                     fill=col, outline="", tags=tags)


def ic_restore(c, x, y, s, col, tags=()):
    r = s * 0.32
    c.create_arc(x - r, y - r, x + r, y + r, start=60, extent=260, style="arc",
                 outline=col, width=1.7, tags=tags)
    c.create_polygon(x - r * 0.85, y - r * 0.52, x - r * 0.10, y - r * 0.55,
                     x - r * 0.55, y + r * 0.05, fill=col, outline="", tags=tags)


def ic_x(c, x, y, s, col, tags=()):
    _line(c, x - s * 0.24, y - s * 0.24, x + s * 0.24, y + s * 0.24, col, tags, w=1.8)
    _line(c, x - s * 0.24, y + s * 0.24, x + s * 0.24, y - s * 0.24, col, tags, w=1.8)


def ic_grip(c, x, y, s, col, tags=()):
    r = 1.3
    for row in (-1, 0, 1):
        for colx in (-2.6, 2.6):
            cx = x + colx * s * 0.09
            cy = y + row * s * 0.16
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col, outline="", tags=tags)


def ic_sprout(c, x, y, s, col, col2=None, tags=()):
    """小芽(品牌标)。"""
    col2 = col2 or col
    _line(c, x, y + s * 0.42, x, y - s * 0.02, col, tags, w=2.0)
    r = s * 0.20
    c.create_oval(x - s * 0.40, y - s * 0.30, x - s * 0.02, y + s * 0.08, fill=col, outline="", tags=tags)
    c.create_oval(x + s * 0.02, y - s * 0.42, x + s * 0.40, y - s * 0.04, fill=col2, outline="", tags=tags)


def ic_fire(c, x, y, s, col, tags=()):
    pts = [x, y - s * 0.42, x + s * 0.26, y - s * 0.06, x + s * 0.22, y + s * 0.26,
           x, y + s * 0.42, x - s * 0.22, y + s * 0.26, x - s * 0.26, y - s * 0.06]
    c.create_polygon(pts, smooth=True, fill=col, outline="", tags=tags)
    inner = [x, y - s * 0.02, x + s * 0.11, y + s * 0.12, x, y + s * 0.34, x - s * 0.11, y + s * 0.12]
    c.create_polygon(inner, smooth=True, fill="#ffffff", outline="", tags=tags)


def ic_calendar(c, x, y, s, col, tags=()):
    rrect(c, x - s * 0.32, y - s * 0.26, x + s * 0.32, y + s * 0.40, r=3,
          outline=col, width=1.4, tags=tags)
    _line(c, x - s * 0.32, y - s * 0.04, x + s * 0.32, y - s * 0.04, col, tags, w=1.2)
    _line(c, x - s * 0.14, y - s * 0.36, x - s * 0.14, y - s * 0.18, col, tags)
    _line(c, x + s * 0.14, y - s * 0.36, x + s * 0.14, y - s * 0.18, col, tags)


def ic_chevron(c, x, y, s, col, tags=(), down=True):
    d = 1 if down else -1
    _line(c, x - s * 0.22, y - d * s * 0.10, x, y + d * s * 0.14, col, tags)
    _line(c, x, y + d * s * 0.14, x + s * 0.22, y - d * s * 0.10, col, tags)


def ic_check(c, x, y, s, col, tags=()):
    """勾,中心 x,y,s≈宽度。"""
    k = s * 0.30
    _line(c, x - k, y, x - k * 0.15, y + k * 0.8, col, tags, w=2.2)
    _line(c, x - k * 0.15, y + k * 0.8, x + k * 1.05, y - k * 0.9, col, tags, w=2.2)


def ic_note(c, x, y, s, col, tags=()):
    """备注小图标(便签)。"""
    rrect(c, x - s * 0.28, y - s * 0.34, x + s * 0.28, y + s * 0.34, r=3,
          outline=col, width=1.3, tags=tags)
    _line(c, x - s * 0.15, y - s * 0.12, x + s * 0.15, y - s * 0.12, col, tags, w=1.1)
    _line(c, x - s * 0.15, y + s * 0.04, x + s * 0.10, y + s * 0.04, col, tags, w=1.1)


# ---------------------------------------------------------------- 通用绘制

def checkbox(c, cx, cy, r, done, accent, muted, daily=False, bg="#ffffff", tags=()):
    """圆形勾选框。daily 用虚线外圈区分。"""
    if done:
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=accent, outline="", tags=tags)
        ic_check(c, cx, cy + r * 0.05, r * 1.15, "#ffffff", tags)
    else:
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=bg,
                      outline=muted, width=1.6,
                      dash=(3, 2) if daily else (), tags=tags)
        if daily:
            ic_check(c, cx, cy, r * 0.9, muted, tags)  # 淡淡的勾提示可点
    # 命中区
    hr = r + 4
    c.create_rectangle(cx - hr, cy - hr, cx + hr, cy + hr, fill="", outline="", width=0, tags=tags)


def toggle(c, x1, y1, x2, y2, on, col_on, col_off, knob="#ffffff", tags=()):
    """开关,x1y1-x2y2 为轨道。"""
    c.create_oval(x1, y1, x2, y2, fill=col_on if on else col_off, outline="", tags=tags)
    r = (y2 - y1) / 2.0 - 2
    ky = (y1 + y2) / 2.0
    kx = x2 - r - 2 if on else x1 + r + 2
    c.create_oval(kx - r, ky - r, kx + r, ky + r, fill=knob, outline="", tags=tags)
    hit = 6
    c.create_rectangle(x1 - hit, y1 - hit, x2 + hit, y2 + hit, fill="", outline="", width=0, tags=tags)


def text_h(font, text, width):
    """给定换行宽度,估算 create_text 需要的高度(px)。"""
    lines = 0
    for seg in str(text).split("\n"):
        if not seg:
            lines += 1
            continue
        w = font.measure(seg)
        lines += max(1, -(-w // max(10, width)))
    return lines * font.metrics("linespace")
