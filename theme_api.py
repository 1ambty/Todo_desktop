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
    """内置主题 + themes/ 插件,返回 (主题列表, 无效文件名列表)。

    插件两种形态:
      <id>.json            纯配色主题
      <id>.json + <id>.py  配色 + 皮肤脚本(可覆盖绘制函数,异形 UI)
      <id>.py              纯皮肤脚本,文件内自带 SKIN = {id, name, vars} 元数据
    """
    themes = [_merge(dict(t)) for t in BUILTIN_THEMES]
    bad = []
    seen = {t["id"] for t in themes}
    if os.path.isdir(THEMES_DIR):
        for fn in sorted(os.listdir(THEMES_DIR)):
            stem, ext = os.path.splitext(fn)
            ext = ext.lower()
            path = os.path.join(THEMES_DIR, fn)
            if ext == ".json":
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data["_file"] = path
                    if not isinstance(data, dict):
                        raise ValueError("主题必须是 JSON 对象")
                    data.setdefault("id", stem)
                    if data["id"] in seen:      # 与内置同名 → 允许覆盖内置
                        themes = [t for t in themes if t["id"] != data["id"]]
                    entry = _merge(data)
                    skin_path = os.path.join(THEMES_DIR, stem + ".py")
                    if os.path.exists(skin_path):
                        entry["skin_file"] = skin_path
                    themes.append(entry)
                    seen.add(entry["id"])
                except Exception as e:
                    bad.append("%s(%s)" % (fn, e))
            elif ext == ".py" and not os.path.exists(os.path.join(THEMES_DIR, stem + ".json")):
                # 纯皮肤脚本:执行以读取 SKIN 元数据(出错仅剔除该主题,不影响主程序)
                try:
                    ns = run_skin_file(path)
                    meta = ns.get("SKIN") or {}
                    entry = _merge({"id": meta.get("id") or stem,
                                    "name": meta.get("name") or stem,
                                    "author": meta.get("author", ""),
                                    "vars": meta.get("vars") or {}})
                    entry["skin_file"] = path
                    if entry["id"] in seen:
                        themes = [t for t in themes if t["id"] != entry["id"]]
                    themes.append(entry)
                    seen.add(entry["id"])
                except Exception as e:
                    bad.append("%s(%s)" % (fn, e))
    return themes, bad


def run_skin_file(path):
    """执行皮肤脚本,返回其命名空间(脚本出错抛异常,由调用方处理)。"""
    ns = {"__name__": "todo_skin_" + os.path.splitext(os.path.basename(path))[0],
          "__file__": path}
    with open(path, "r", encoding="utf-8") as f:
        code = f.read()
    exec(compile(code, path, "exec"), ns)
    return ns


def load_skin(entry):
    """执行皮肤脚本,收集钩子 {name: fn} 后交给 UI 绑定。

    钩子:所有 draw_* 前缀函数(覆盖 TodoApp 同名绘制方法)与 on_apply。
    无皮肤文件返回 {}。
    """
    path = entry.get("skin_file")
    if not path:
        return {}
    ns = run_skin_file(path)
    hooks = {}
    for k, v in ns.items():
        if callable(v) and (k == "on_apply" or k == "draw" or k.startswith("draw_")):
            hooks[k] = v
    return hooks


def get_theme(tid):
    themes, _ = scan_themes()
    for t in themes:
        if t["id"] == tid:
            return t
    return themes[0]


def color_ok(c):
    return isinstance(c, str) and len(c) in (4, 7) and c[0] == "#"
