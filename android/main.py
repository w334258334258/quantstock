# -*- coding: utf-8 -*-
"""
安卓量化选股 App（Kivy 主程序）
================================
页面：
  1. 选股（全市场筛选）
  2. 单股分析（输入代码）
  3. K线 + 买卖点
  4. 下单清单
  5. 下单记录 + 回测

依赖：kivy + core.py（本目录）
打包：buildozer（Linux/WSL）
"""

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.popup import Popup
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, Line
from kivy.metrics import dp
from kivy.core.window import Window

import threading
import json
import os

import core

# ==================== 中文字体注册 ====================
# 解决安卓上中文显示为方框（乱码）的问题
from kivy.core.text import LabelBase

_FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "simhei.ttf")
if os.path.exists(_FONT_PATH):
    # 注册一个支持中文的字体，并设为默认
    LabelBase.register(name="Roboto", fn_regular=_FONT_PATH)
    LabelBase.register(name="RobotoRegular", fn_regular=_FONT_PATH)
    LabelBase.register(name="DejaVuSans", fn_regular=_FONT_PATH)
else:
    print("警告：未找到中文字体文件 simhei.ttf")

# 颜色
RED = (0.85, 0.33, 0.31, 1)    # 涨/买（红）
GREEN = (0.18, 0.62, 0.35, 1)  # 跌/卖（绿）
BLUE = (0.27, 0.44, 0.76, 1)   # 主色
GRAY = (0.6, 0.6, 0.6, 1)
BG = (0.95, 0.96, 0.98, 1)


class KlineWidget(BoxLayout):
    """K线绘制控件（纯 Kivy 绘图，无 matplotlib）。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.kline = []

    def set_data(self, kline):
        self.kline = kline
        self.canvas.after.clear()
        with self.canvas.after:
            self._draw()

    def _draw(self):
        if not self.kline:
            return
        w, h = self.size
        if w <= 0 or h <= 0:
            return
        k = self.kline
        highs = [x["high"] for x in k]
        lows = [x["low"] for x in k]
        vmax = max(highs)
        vmin = min(lows)
        rng = (vmax - vmin) or 1.0
        n = len(k)
        cw = w / n
        pad = 20
        plot_h = h - pad * 2

        def y(v):
            return pad + (vmax - v) / rng * plot_h

        # 均线
        closes = [x["close"] for x in k]
        for period, color in [(5, (0.94, 0.65, 0.05, 1)), (20, BLUE)]:
            if len(closes) >= period:
                ma = []
                for i in range(period - 1, len(closes)):
                    ma.append(sum(closes[i - period + 1:i + 1]) / period)
                pts = []
                for i, v in enumerate(ma):
                    pts += [i * cw + cw / 2, y(v)]
                if len(pts) >= 4:
                    Color(*color)
                    Line(points=pts, width=1.2)

        # K线实体 + 影线
        for i, x in enumerate(k):
            color = RED if x["close"] >= x["open"] else GREEN
            Color(*color)
            cx = i * cw + cw / 2
            # 影线
            Line(points=[cx, y(x["low"]), cx, y(x["high"])], width=0.8)
            # 实体
            body_low = min(x["open"], x["close"])
            body_high = max(x["open"], x["close"])
            bh = max(y(body_low) - y(body_high), 1.0)
            Color(*color)
            Rectangle(pos=(cx - cw * 0.35, y(body_high)), size=(cw * 0.7, bh))


class StockApp(App):
    title = "量化选股"

    def build(self):
        self.sm = ScreenManager()
        self.sm.add_widget(self._build_select())
        self.sm.add_widget(self._build_analyze())
        self.sm.add_widget(self._build_kline())
        self.sm.add_widget(self._build_order())
        self.sm.add_widget(self._build_trades())
        return self.sm

    # ==================== 通用 ====================

    def _header(self, title):
        box = BoxLayout(size_hint_y=None, height=dp(44), padding=[dp(10), dp(5)])
        with box.canvas.before:
            Color(*BLUE)
            Rectangle(pos=box.pos, size=box.size)
        box.bind(pos=lambda *a: self._redraw(box), size=lambda *a: self._redraw(box))
        lbl = Label(text=title, color=(1, 1, 1, 1), bold=True, size_hint_x=1)
        box.add_widget(lbl)
        return box

    def _redraw(self, widget):
        widget.canvas.before.clear()
        with widget.canvas.before:
            Color(*BLUE)
            Rectangle(pos=widget.pos, size=widget.size)

    def _nav(self, current):
        nav = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(2))
        tabs = [("选股", "select"), ("分析", "analyze"), ("K线", "kline"),
                ("下单", "order"), ("记录", "trades")]
        for name, page in tabs:
            b = Button(text=name, font_size=dp(13))
            b.background_color = BLUE if page == current else (0.85, 0.87, 0.9, 1)
            b.color = (1, 1, 1, 1) if page == current else (0.3, 0.3, 0.3, 1)
            b.bind(on_release=lambda x, p=page: setattr(self.sm, "current", p))
            nav.add_widget(b)
        return nav

    def _run_async(self, fn, callback, error_cb=None):
        def worker():
            try:
                result = fn()
                Clock.schedule_once(lambda dt: callback(result))
            except Exception as e:
                Clock.schedule_once(lambda dt: (error_cb or self._show_error)(str(e)))
        threading.Thread(target=worker, daemon=True).start()

    def _show_error(self, msg):
        popup = Popup(title="错误", content=Label(text=str(msg), text_size=(dp(280), None)),
                      size_hint=(0.8, 0.4))
        popup.open()

    def _toast(self, msg):
        popup = Popup(title="提示", content=Label(text=str(msg), text_size=(dp(280), None)),
                      size_hint=(0.8, 0.4))
        popup.open()

    # ==================== 选股页 ====================

    def _build_select(self):
        screen = Screen(name="select")
        root = BoxLayout(orientation="vertical")
        root.add_widget(self._header("📊 量化选股"))
        root.add_widget(self._nav("select"))

        self.select_status = Label(text="点击下方按钮开始选股", size_hint_y=None, height=dp(40),
                                   color=GRAY, font_size=dp(13))
        root.add_widget(self.select_status)

        btn = Button(text="开始选股（约1分钟）", size_hint_y=None, height=dp(50),
                     background_color=BLUE, color=(1, 1, 1, 1))
        btn.bind(on_release=lambda x: self._do_select())
        root.add_widget(btn)

        self.select_scroll = ScrollView()
        self.select_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(2))
        self.select_box.bind(minimum_height=self.select_box.setter("height"))
        self.select_scroll.add_widget(self.select_box)
        root.add_widget(self.select_scroll)
        screen.add_widget(root)
        return screen

    def _do_select(self):
        self.select_status.text = "正在拉取全市场行情并筛选..."
        self._run_async(core.select_stocks, self._render_select)

    def _render_select(self, rows):
        self.select_box.clear_widgets()
        if not rows:
            self.select_status.text = "无符合条件的股票"
            return
        self.select_status.text = "共选出 %d 只" % len(rows)
        for r in rows:
            line = Label(
                text="%s %s  现价%s  涨%s%%  PE%s  评分%s" % (
                    r["代码"], r["名称"], r["现价"], r["涨跌幅%"],
                    r["市盈率PE"], r["score"]),
                size_hint_y=None, height=dp(36), font_size=dp(13),
                color=RED if r["涨跌幅%"] >= 0 else GREEN)
            self.select_box.add_widget(line)

    # ==================== 单股分析 ====================

    def _build_analyze(self):
        screen = Screen(name="analyze")
        root = BoxLayout(orientation="vertical")
        root.add_widget(self._header("🔍 单股分析"))
        root.add_widget(self._nav("analyze"))

        input_row = BoxLayout(size_hint_y=None, height=dp(48), padding=[dp(10), dp(6)], spacing=dp(8))
        self.code_input = TextInput(hint_text="输入股票代码，如 600519", multiline=False)
        input_row.add_widget(self.code_input)
        btn = Button(text="分析", size_hint_x=0.3, background_color=BLUE, color=(1, 1, 1, 1))
        btn.bind(on_release=lambda x: self._do_analyze())
        input_row.add_widget(btn)
        root.add_widget(input_row)

        self.analyze_status = Label(text="", size_hint_y=None, height=dp(36),
                                    color=GRAY, font_size=dp(13))
        root.add_widget(self.analyze_status)

        self.analyze_scroll = ScrollView()
        self.analyze_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(4), padding=[dp(10), dp(4)])
        self.analyze_box.bind(minimum_height=self.analyze_box.setter("height"))
        self.analyze_scroll.add_widget(self.analyze_box)
        root.add_widget(self.analyze_scroll)
        screen.add_widget(root)
        return screen

    def _do_analyze(self):
        code = self.code_input.text.strip()
        if not code:
            self._toast("请输入股票代码")
            return
        self.analyze_status.text = "正在分析 %s..." % code
        self._run_async(lambda: core.analyze_single(code), self._render_analyze)

    def _render_analyze(self, r):
        self.analyze_box.clear_widgets()
        if r is None:
            self.analyze_status.text = "未找到该股票"
            return
        self.analyze_status.text = "%s %s" % (r["代码"], r["名称"])

        def add(text, color=(0.2, 0.2, 0.2, 1), height=dp(32)):
            self.analyze_box.add_widget(Label(text=text, size_hint_y=None, height=height,
                                              font_size=dp(13), color=color, halign="left",
                                              text_size=(dp(340), None)))

        add("现价 %s 元  涨跌 %s%%" % (r["现价"], r["涨跌幅%"]),
            RED if r["涨跌幅%"] >= 0 else GREEN)
        add("换手 %s%%  PE %s  PB %s  市值 %s亿" % (
            r["换手率%"], r["市盈率PE"], r["市净率PB"], r["总市值(亿)"]))
        fin = r.get("finance", {})
        add("ROE %s%%  毛利率 %s%%" % (fin.get("roe", "-"), fin.get("gross_margin", "-")))
        cap = r.get("capital", {})
        main_net = cap.get("main_net", 0)
        add("主力净流入 %.2f亿  净占比 %s%%" % (main_net / 1e8, round(cap.get("main_pct", 0), 2)),
            RED if main_net >= 0 else GREEN)
        sig = r.get("signal")
        if sig:
            add("买卖点建议：%s（最新价 %s）" % (sig["建议"], sig["价格"]),
                RED if sig["建议"] == "买入" else (GREEN if sig["建议"] == "卖出" else GRAY),
                height=dp(40))
            for reason in sig["理由"]:
                add("  · " + reason, height=dp(28))
        news = r.get("news", {})
        add("新闻情绪：%s" % news.get("情绪", "-"))
        for n in news.get("列表", [])[:3]:
            add("  · " + n["title"][:30], height=dp(28))

    # ==================== K线页 ====================

    def _build_kline(self):
        screen = Screen(name="kline")
        root = BoxLayout(orientation="vertical")
        root.add_widget(self._header("📈 K线 + 买卖点"))
        root.add_widget(self._nav("kline"))

        input_row = BoxLayout(size_hint_y=None, height=dp(48), padding=[dp(10), dp(6)], spacing=dp(8))
        self.kline_code = TextInput(hint_text="股票代码", multiline=False)
        input_row.add_widget(self.kline_code)
        self.kline_scale = Spinner(text="日线", values=["日线", "周线", "1分钟", "5分钟", "15分钟", "30分钟", "60分钟"],
                                   size_hint_x=0.55)
        input_row.add_widget(self.kline_scale)
        btn = Button(text="查看", size_hint_x=0.25, background_color=BLUE, color=(1, 1, 1, 1))
        btn.bind(on_release=lambda x: self._do_kline())
        input_row.add_widget(btn)
        root.add_widget(input_row)

        self.kline_signal = Label(text="", size_hint_y=None, height=dp(70),
                                  font_size=dp(12), color=GRAY, text_size=(dp(360), None))
        root.add_widget(self.kline_signal)

        self.kline_widget = KlineWidget(size_hint_y=1)
        root.add_widget(self.kline_widget)
        screen.add_widget(root)
        return screen

    def _do_kline(self):
        code = self.kline_code.text.strip()
        if not code:
            self._toast("请输入股票代码")
            return
        scale_map = {"日线": "day", "周线": "week", "1分钟": "1", "5分钟": "5",
                     "15分钟": "15", "30分钟": "30", "60分钟": "60"}
        scale = scale_map.get(self.kline_scale.text, "day")

        def work():
            kline = core.fetch_kline(code, scale, 120)
            sig = core.latest_signal_summary(kline) if len(kline) >= 30 else None
            return kline, sig

        self._run_async(work, lambda res: self._render_kline(res))

    def _render_kline(self, res):
        kline, sig = res
        if not kline:
            self._toast("K线数据不足")
            return
        self.kline_widget.set_data(kline)
        if sig:
            color = RED if sig["建议"] == "买入" else (GREEN if sig["建议"] == "卖出" else GRAY)
            text = "建议：%s（价 %s）\n" % (sig["建议"], sig["价格"])
            text += " | ".join(sig["理由"][:4])
            self.kline_signal.text = text
            self.kline_signal.color = color

    # ==================== 下单页 ====================

    def _build_order(self):
        screen = Screen(name="order")
        root = BoxLayout(orientation="vertical")
        root.add_widget(self._header("📋 下单清单"))
        root.add_widget(self._nav("order"))

        input_row = BoxLayout(size_hint_y=None, height=dp(48), padding=[dp(10), dp(6)], spacing=dp(8))
        self.capital_input = TextInput(text="100000", hint_text="总资金", multiline=False)
        input_row.add_widget(self.capital_input)
        btn = Button(text="生成清单", size_hint_x=0.4, background_color=BLUE, color=(1, 1, 1, 1))
        btn.bind(on_release=lambda x: self._do_order())
        input_row.add_widget(btn)
        root.add_widget(input_row)

        self.order_status = Label(text="先到「选股」页选股，再回来生成清单", size_hint_y=None,
                                  height=dp(36), color=GRAY, font_size=dp(13))
        root.add_widget(self.order_status)

        self.order_scroll = ScrollView()
        self.order_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(2))
        self.order_box.bind(minimum_height=self.order_box.setter("height"))
        self.order_scroll.add_widget(self.order_box)
        root.add_widget(self.order_scroll)
        screen.add_widget(root)
        return screen

    def _do_order(self):
        # 用最近一次选股结果生成清单
        rows = getattr(self, "last_select", [])
        if not rows:
            self._toast("请先到「选股」页选股")
            return
        capital = float(self.capital_input.text or 100000)
        orders = core.build_orders(rows, capital=capital)
        self.order_box.clear_widgets()
        if not orders:
            self.order_status.text = "资金不足以买入一手"
            return
        total = sum(o["建议金额(元)"] for o in orders)
        self.order_status.text = "%d 只，合计 %.2f 元" % (len(orders), total)
        for o in orders:
            self.order_box.add_widget(Label(
                text="%s %s  买入%d股 @%s  金额%s" % (
                    o["代码"], o["名称"], o["建议数量(股)"], o["现价"], o["建议金额(元)"]),
                size_hint_y=None, height=dp(36), font_size=dp(13), color=RED))

    # ==================== 记录页 ====================

    def _build_trades(self):
        screen = Screen(name="trades")
        root = BoxLayout(orientation="vertical")
        root.add_widget(self._header("💾 下单记录 + 回测"))
        root.add_widget(self._nav("trades"))

        self.trades_status = Label(text="暂无下单记录", size_hint_y=None, height=dp(36),
                                   color=GRAY, font_size=dp(13))
        root.add_widget(self.trades_status)

        btn = Button(text="回测统计", size_hint_y=None, height=dp(44),
                     background_color=BLUE, color=(1, 1, 1, 1))
        btn.bind(on_release=lambda x: self._do_stats())
        root.add_widget(btn)

        self.trades_scroll = ScrollView()
        self.trades_box = GridLayout(cols=1, size_hint_y=None, spacing=dp(2))
        self.trades_box.bind(minimum_height=self.trades_box.setter("height"))
        self.trades_scroll.add_widget(self.trades_box)
        root.add_widget(self.trades_scroll)
        screen.add_widget(root)
        return screen

    def _do_stats(self):
        stats = core.backtest_stats(getattr(self, "trades", []))
        self.trades_box.clear_widgets()
        if not stats:
            self.trades_status.text = "暂无下单记录"
            return
        self.trades_status.text = "胜率 %s%%  总盈亏 %s 元" % (stats["胜率%"], stats["总盈亏(元)"])
        for k, v in stats.items():
            self.trades_box.add_widget(Label(text="%s：%s" % (k, v), size_hint_y=None,
                                             height=dp(32), font_size=dp(13)))


if __name__ == "__main__":
    StockApp().run()
