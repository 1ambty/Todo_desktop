# -*- coding: utf-8 -*-
"""主题插件接口。

内置主题在 BUILTIN_THEMES;`themes/` 目录下的每个 *.json 都会被当作主题插件
自动加载,文件格式见 themes/README.md。缺省字段回落到 DEFAULT_VARS,
所以插件只需要写想覆盖的颜色。
"""
import json
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
THEMES_DIR = os.path.join(APP_DIR, "themes")

# 所有可用变量与默认值(青苔,低饱和灰绿)
DEFAULT_VARS = {
    "bg":          "#eef2e8",   # 窗体底色
    "bg2":         "#f4f7ee",   # 窗体渐变辅助色
    "panel":       "#f9fbf5",   # 面板/弹层
    "card":        "#f7faf1",   # 卡片
    "card_hover":  "#eef4e4",   # 卡片悬停
    "chip":        "#e7eedd",   # 小标签底
    "accent_soft": "#dfe9d5",   # 强调弱色(选中态)
    "accent":      "#7fa07a",   # 强调色(勾选/按钮)
    "accent_deep": "#5f8161",   # 强调深色(文字按钮)
    "ink":         "#46523f",   # 主文字
    "ink_soft":    "#6c7a63",   # 次级文字
    "muted":       "#97a58b",   # 弱文字/描边元素
    "line":        "#dde5d0",   # 分隔线/卡片描边
    "border":      "#ccd8bd",   # 窗体外描边
    "due":         "#ab8a5c",   # 截止日期
    "danger":      "#bd8d7d",   # 删除/逾期
    "ok":          "#7fae8a",   # 成功
    "scrollbar":   "#c4d1b4",   # 滚动条
    "radius":      "12",        # 卡片圆角(px)
    "font":        "Microsoft YaHei UI",
    "title":       "待办",
}

# 主题卡片上展示的色板顺序
SWATCH_KEYS = ["bg", "accent", "accent_deep", "ink", "due"]

BUILTIN_THEMES = [
    {"id": "sage", "name": "青苔", "author": "内置", "builtin": True,
     "vars": {},  # 全部走默认
     "desc": "低饱和灰绿 · 默认"},
]


def _merge(t):
    vars_ = dict(DEFAULT_VARS)
    for k, v in (t.get("vars") or {}).items():
        if k in vars_ and isinstance(v, str) and v.strip():
            vars_[k] = v.strip()
    out = {
        "id": t.get("id") or os.path.splitext(os.path.basename(t.get("_file", "x.json")))[0],
        "name": t.get("name") or t.get("id") or "未命名主题",
        "author": t.get("author", ""),
        "vars": vars_,
        "builtin": bool(t.get("builtin")),
    }
    try:
        out["radius"] = max(0, min(18, int(float(vars_.get("radius", 12)))))
    except Exception:
        out["radius"] = 12
    return out


def scan_themes():
    """内置主题 + themes/*.json 插件,返回 (主题列表, 无效文件名列表)。"""
    themes = [_merge(dict(t)) for t in BUILTIN_THEMES]
    bad = []
    seen = {t["id"] for t in themes}
    if os.path.isdir(THEMES_DIR):
        for fn in sorted(os.listdir(THEMES_DIR)):
            if not fn.lower().endswith(".json"):
                continue
            path = os.path.join(THEMES_DIR, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["_file"] = path
                if not isinstance(data, dict):
                    raise ValueError("主题必须是 JSON 对象")
                data.setdefault("id", os.path.splitext(fn)[0])
                if data["id"] in seen:      # 与内置同名 → 允许覆盖内置
                    themes = [t for t in themes if t["id"] != data["id"]]
                themes.append(_merge(data))
                seen.add(data["id"])
            except Exception as e:
                bad.append("%s(%s)" % (fn, e))
    return themes, bad


def get_theme(tid):
    themes, _ = scan_themes()
    for t in themes:
        if t["id"] == tid:
            return t
    return themes[0]


def color_ok(c):
    return isinstance(c, str) and len(c) in (4, 7) and c[0] == "#"
