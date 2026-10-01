# -*- coding: utf-8 -*-
"""
安卓精简版 · 选股核心逻辑（纯 Python，无重依赖）
================================================
仅依赖 requests + 标准库，供 Kivy 打包 APK 使用。

复用 desktop 版 stock_selector_enhanced.py 的核心算法，
但去掉了 akshare / pandas / matplotlib / numpy 等重依赖。

功能：
  - 全市场行情快照（新浪）
  - 单股分析（行情/技术/财务/资金/新闻/龙虎榜/评分/概率）
  - 日线/周线/分时 K线数据 + 买卖点信号
  - 下单清单生成 + 回测统计

数据源：新浪财经 + 东方财富（公开接口）
"""

import json
import math
import datetime
import requests

_UA_SINA = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}
_UA_EM = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
          "Referer": "https://quote.eastmoney.com/"}


def log(msg):
    print("[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg))


def to_float(v, default=0.0):
    try:
        f = float(v)
        return f if not math.isnan(f) else default
    except (TypeError, ValueError):
        return default


def to_sina_symbol(code):
    code = str(code).strip().lower()
    for p in ("sh", "sz", "bj"):
        if code.startswith(p):
            code = code[len(p):]
            break
    if code.startswith(("6", "9")):
        return "sh" + code
    return "sz" + code


# ==================== 行情快照 ====================

def fetch_market_snapshot():
    """新浪：全市场 A 股行情快照（含 PE/PB/市值/换手/涨跌幅）。"""
    all_rows = []
    page = 1
    while True:
        params = {"page": page, "num": 80, "sort": "changepercent", "asc": 0,
                  "node": "hs_a", "symbol": "", "_s_r_a": "page"}
        try:
            r = requests.get(
                "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
                params=params, headers=_UA_SINA, timeout=20)
        except Exception:
            break
        if r.status_code != 200:
            break
        text = r.text.strip()
        if not text or text in ("null", "[]", ""):
            break
        try:
            rows = json.loads(text)
        except Exception:
            break
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < 80:
            break
        page += 1
    return all_rows


# ==================== K线数据 ====================

def fetch_kline(code, scale="day", count=120):
    """拉取 K线。scale: 'day'/'week'/'1'/'5'/'15'/'30'/'60'。"""
    symbol = to_sina_symbol(code)
    sina_scale = {"day": "240", "week": "1200", "1": "1", "5": "5",
                  "15": "15", "30": "30", "60": "60"}.get(str(scale), str(scale))
    try:
        r = requests.get(
            "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/CN_MarketDataService.getKLineData",
            params={"symbol": symbol, "scale": sina_scale, "ma": "no", "datalen": str(count)},
            headers=_UA_SINA, timeout=20)
    except Exception:
        return []
    text = r.text
    start = text.find("([")
    end = text.rfind("])")
    if start < 0 or end < 0:
        return []
    try:
        arr = json.loads(text[start + 1:end + 1])
    except Exception:
        return []
    return [{"day": k["day"], "open": float(k["open"]), "high": float(k["high"]),
             "low": float(k["low"]), "close": float(k["close"]),
             "volume": float(k["volume"]), "amount": float(k.get("amount", 0))}
            for k in arr]


# ==================== 技术指标 ====================

def calc_ema(values, period):
    if not values:
        return []
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def calc_macd(closes):
    if len(closes) < 26:
        return [0], [0], [0]
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = calc_ema(dif, 9)
    hist = [(a - b) * 2 for a, b in zip(dif, dea)]
    return dif, dea, hist


def calc_rsi(closes, period=14):
    n = len(closes)
    if n < period + 1:
        return [50.0] * n
    rsi = [50.0] * (period + 1)
    gains, losses = [], []
    for i in range(1, n):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, 0))
        losses.append(max(-chg, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi.append(100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss))
    while len(rsi) < n:
        rsi.append(rsi[-1])
    return rsi[:n]


def calc_kdj(kline, n=9):
    k_vals, d_vals, j_vals = [], [], []
    k, d = 50.0, 50.0
    for i in range(len(kline)):
        if i < n - 1:
            k_vals.append(50.0); d_vals.append(50.0); j_vals.append(50.0)
            continue
        window = kline[i - n + 1:i + 1]
        hn = max(x["high"] for x in window)
        ln = min(x["low"] for x in window)
        rsv = (kline[i]["close"] - ln) / (hn - ln) * 100 if hn != ln else 50.0
        k = 2 / 3 * k + 1 / 3 * rsv
        d = 2 / 3 * d + 1 / 3 * k
        j = 3 * k - 2 * d
        k_vals.append(k); d_vals.append(d); j_vals.append(j)
    return k_vals, d_vals, j_vals


def calc_ma(closes, period):
    return [None] * (period - 1) + [
        sum(closes[i - period + 1:i + 1]) / period for i in range(period - 1, len(closes))
    ]


def gen_signals(kline):
    """生成买卖点信号（MACD + 均线 + RSI + KDJ）。"""
    closes = [k["close"] for k in kline]
    n = len(kline)
    dif, dea, _ = calc_macd(closes)
    macd_buy, macd_sell = [], []
    for i in range(1, n):
        if dif[i - 1] <= dea[i - 1] and dif[i] > dea[i]:
            macd_buy.append(i)
        elif dif[i - 1] >= dea[i - 1] and dif[i] < dea[i]:
            macd_sell.append(i)

    ma5 = calc_ma(closes, 5)
    ma20 = calc_ma(closes, 20)
    ma_buy, ma_sell = [], []
    for i in range(20, n):
        if ma5[i - 1] is not None and ma20[i - 1] is not None:
            if ma5[i - 1] <= ma20[i - 1] and ma5[i] > ma20[i]:
                ma_buy.append(i)
            elif ma5[i - 1] >= ma20[i - 1] and ma5[i] < ma20[i]:
                ma_sell.append(i)

    rsi = calc_rsi(closes)
    rsi_buy, rsi_sell = [], []
    for i in range(1, n):
        if rsi[i - 1] >= 30 and rsi[i] < 30:
            rsi_buy.append(i)
        elif rsi[i - 1] <= 70 and rsi[i] > 70:
            rsi_sell.append(i)

    k_vals, d_vals, _ = calc_kdj(kline)
    kdj_buy, kdj_sell = [], []
    for i in range(1, n):
        if k_vals[i - 1] <= d_vals[i - 1] and k_vals[i] > d_vals[i]:
            kdj_buy.append(i)
        elif k_vals[i - 1] >= d_vals[i - 1] and k_vals[i] < d_vals[i]:
            kdj_sell.append(i)

    return {"macd_buy": macd_buy, "macd_sell": macd_sell,
            "ma_buy": ma_buy, "ma_sell": ma_sell,
            "rsi_buy": rsi_buy, "rsi_sell": rsi_sell,
            "kdj_buy": kdj_buy, "kdj_sell": kdj_sell}


def latest_signal_summary(kline):
    """最近买卖点文字化总结。"""
    if len(kline) < 30:
        return {"建议": "观望", "理由": ["数据不足"], "价格": kline[-1]["close"] if kline else 0}
    sig = gen_signals(kline)
    n = len(kline)
    last = n - 1
    reasons = []
    buy_score = sell_score = 0

    def recent(lst, lookback=3):
        return [i for i in lst if last - lookback < i <= last]

    if recent(sig["macd_buy"]): reasons.append("MACD 金叉（买入）"); buy_score += 2
    if recent(sig["macd_sell"]): reasons.append("MACD 死叉（卖出）"); sell_score += 2
    if recent(sig["ma_buy"]): reasons.append("均线 MA5 上穿 MA20（买入）"); buy_score += 2
    if recent(sig["ma_sell"]): reasons.append("均线 MA5 下穿 MA20（卖出）"); sell_score += 2
    if recent(sig["kdj_buy"]): reasons.append("KDJ 金叉（买入）"); buy_score += 1
    if recent(sig["kdj_sell"]): reasons.append("KDJ 死叉（卖出）"); sell_score += 1
    if recent(sig["rsi_buy"]): reasons.append("RSI 超卖（买入）"); buy_score += 1
    if recent(sig["rsi_sell"]): reasons.append("RSI 超买（卖出）"); sell_score += 1

    closes = [k["close"] for k in kline]
    dif, dea, hist = calc_macd(closes)
    ma5 = calc_ma(closes, 5)
    ma20 = calc_ma(closes, 20)
    if hist[-1] > 0: reasons.append("MACD 红柱（多头）"); buy_score += 1
    else: reasons.append("MACD 绿柱（空头）"); sell_score += 1
    if ma5[-1] is not None and ma20[-1] is not None:
        if ma5[-1] > ma20[-1]: reasons.append("MA5 在 MA20 上方（多头）"); buy_score += 1
        else: reasons.append("MA5 在 MA20 下方（空头）"); sell_score += 1
    rsi = calc_rsi(closes)[-1]
    if rsi < 30: reasons.append("RSI %.1f 超卖" % rsi); buy_score += 1
    elif rsi > 70: reasons.append("RSI %.1f 超买" % rsi); sell_score += 1

    advice = "买入" if buy_score > sell_score else ("卖出" if sell_score > buy_score else "观望")
    return {"建议": advice, "理由": reasons[:6], "价格": closes[-1],
            "买入信号数": buy_score, "卖出信号数": sell_score}


# ==================== 财务 / 资金 / 新闻 ====================

def fetch_finance(code):
    """东财：主要财务指标（ROE/毛利率/营收增速/净利增速）。"""
    secucode = code + (".SH" if code.startswith(("6", "9")) else ".SZ")
    params = {"reportName": "RPT_F10_FINANCE_MAINFINADATA", "columns": "ALL",
              "filter": '(SECUCODE="%s")' % secucode,
              "pageNumber": 1, "pageSize": 1, "sortTypes": "-1", "sortColumns": "REPORT_DATE",
              "source": "HSF10", "client": "PC"}
    try:
        r = requests.get("https://datacenter.eastmoney.com/securities/api/data/v1/get",
                         params=params, headers=_UA_EM, timeout=15)
        rows = r.json().get("result", {}).get("data", [])
    except Exception:
        return {}
    if not rows:
        return {}
    row = rows[0]
    return {"roe": to_float(row.get("ROEJQ")), "gross_margin": to_float(row.get("XSMLL")),
            "rev_yoy": to_float(row.get("TOTALOPERATEREVETZ")),
            "profit_yoy": to_float(row.get("PARENTNETPROFITTZ"))}


def fetch_capital_flow(code):
    """新浪：主力资金流。"""
    symbol = to_sina_symbol(code)
    try:
        r = requests.get(
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_zjlrqs",
            params={"page": 1, "num": 1, "sort": "opendate", "asc": 0, "daima": symbol},
            headers=_UA_SINA, timeout=15)
        rows = json.loads(r.text.strip())
    except Exception:
        return {}
    if not rows:
        return {}
    row = rows[0]
    return {"main_net": to_float(row.get("netamount")),
            "main_pct": to_float(row.get("r0_ratio")) * 100,
            "super_net": to_float(row.get("r0_net"))}


_POS = ["增长", "涨停", "中标", "回购", "增持", "涨价", "利好", "突破", "新高", "超预期",
        "扭亏", "盈利", "预增", "签约", "订单", "获批", "大涨", "分红", "扩产", "合作"]
_NEG = ["亏损", "减持", "诉讼", "处罚", "下滑", "下跌", "跌停", "利空", "违规", "退市",
        "警示", "问询", "调查", "爆雷", "裁员", "破产", "造假", "预亏", "暴跌", "风险"]


def fetch_news(code, num=5):
    """东财：个股新闻标题。"""
    secid = ("1." if str(code).startswith("6") else "0.") + str(code)
    try:
        r = requests.get("https://np-listapi.eastmoney.com/comm/web/getListInfo",
                         params={"client": "web", "mType": "1", "type": "1",
                                 "mTypeAndCode": secid, "pageSize": num, "pageIndex": 1},
                         headers=_UA_EM, timeout=12)
        items = r.json().get("data", {}).get("list", [])
        return [{"title": it.get("Art_Title", ""), "url": it.get("Art_Url", "")}
                for it in items if it.get("Art_Title")]
    except Exception:
        return []


def news_sentiment(titles):
    pos = sum(1 for t in titles for w in _POS if w in t)
    neg = sum(1 for t in titles for w in _NEG if w in t)
    score = pos - neg
    label = "利好" if score > 0 else ("利空" if score < 0 else "中性")
    return label, score


# ==================== 选股 ====================

CONFIG = {
    "min_change_pct": 0.0, "max_change_pct": 3.0,
    "min_turnover": 0.5, "max_turnover": 20.0,
    "min_pe": 0.0, "max_pe": 50.0,
    "min_pb": 0.0, "max_pb": 10.0,
    "min_mktcap": 30.0, "max_mktcap": 2000.0,
    "top_n": 20,
}


def is_excluded(code, name):
    if "ST" in name.upper():
        return True
    if code.startswith(("300", "301", "688", "689", "920", "83", "87", "43")):
        return True
    return False


def score_stock(c):
    s = 0.0
    s += c["chg"] * 0.5
    s += min(c["turnover"], 15) * 0.15
    if c["pe"] > 0:
        s += max(0, 40 - c["pe"]) * 0.15
    fin = c.get("finance", {})
    s += fin.get("roe", 0) * 0.3
    s += fin.get("gross_margin", 0) * 0.05
    return round(s, 2)


def select_stocks(top_n=None):
    """快速选股（技术面+基本面，不逐股查K线，速度优先）。"""
    if top_n is None:
        top_n = CONFIG["top_n"]
    rows = fetch_market_snapshot()
    picked = []
    for row in rows:
        code = str(row.get("code", ""))
        name = str(row.get("name", ""))
        if is_excluded(code, name):
            continue
        chg = to_float(row.get("changepercent"))
        turn = to_float(row.get("turnoverratio"))
        pe = to_float(row.get("per"))
        pb = to_float(row.get("pb"))
        mktcap = to_float(row.get("mktcap")) / 10000.0
        if not (CONFIG["min_change_pct"] <= chg <= CONFIG["max_change_pct"]):
            continue
        if not (CONFIG["min_turnover"] <= turn <= CONFIG["max_turnover"]):
            continue
        if pe <= CONFIG["min_pe"] or pe > CONFIG["max_pe"]:
            continue
        if pb < CONFIG["min_pb"] or pb > CONFIG["max_pb"]:
            continue
        if not (CONFIG["min_mktcap"] <= mktcap <= CONFIG["max_mktcap"]):
            continue
        picked.append({"代码": code, "名称": name, "现价": to_float(row.get("trade")),
                       "涨跌幅%": chg, "换手率%": turn, "市盈率PE": pe, "市净率PB": pb,
                       "总市值(亿)": round(mktcap, 2),
                       "score": score_stock({"chg": chg, "turnover": turn, "pe": pe,
                                             "finance": {}})})
    picked.sort(key=lambda x: x["score"], reverse=True)
    return picked[:top_n]


def analyze_single(code):
    """单股分析。"""
    code = str(code).strip()
    if code.startswith(("sh", "sz")):
        code = code[2:]
    snapshot = fetch_market_snapshot()
    raw = None
    for row in snapshot:
        if str(row.get("code", "")) == code:
            raw = row
            break
    if raw is None:
        return None
    name = str(raw.get("name", ""))
    result = {
        "代码": code, "名称": name,
        "现价": to_float(raw.get("trade")),
        "涨跌幅%": to_float(raw.get("changepercent")),
        "换手率%": to_float(raw.get("turnoverratio")),
        "市盈率PE": to_float(raw.get("per")),
        "市净率PB": to_float(raw.get("pb")),
        "总市值(亿)": round(to_float(raw.get("mktcap")) / 10000.0, 2),
    }
    kline = fetch_kline(code, "day", 60)
    if len(kline) >= 30:
        result["signal"] = latest_signal_summary(kline)
    result["finance"] = fetch_finance(code)
    result["capital"] = fetch_capital_flow(code)
    news = fetch_news(code)
    label, score = news_sentiment([n["title"] for n in news])
    result["news"] = {"情绪": label, "列表": news}
    return result


# ==================== 下单 + 回测 ====================

def build_orders(rows, capital=100000.0, max_positions=10, lot_size=100):
    if not rows:
        return []
    picked = rows[:max_positions]
    scores = [max(float(r.get("score", r.get("综合评分", 0))), 0.01) for r in picked]
    total = sum(scores)
    orders = []
    for r, s in zip(picked, scores):
        price = to_float(r.get("现价", r.get("price", 0)))
        if price <= 0:
            continue
        alloc = capital * (s / total)
        shares = int(alloc / price / lot_size) * lot_size
        if shares <= 0:
            continue
        orders.append({"代码": r.get("代码", r.get("code", "")),
                       "名称": r.get("名称", r.get("name", "")),
                       "现价": round(price, 2), "建议数量(股)": shares,
                       "建议金额(元)": round(shares * price, 2),
                       "方向": "买入", "综合评分": round(s, 2)})
    return orders


def backtest_stats(trades):
    """回测统计：买卖配对计算盈亏/胜率。"""
    if not trades:
        return None
    from collections import defaultdict
    groups = defaultdict(list)
    for t in trades:
        groups[t["代码"]].append(t)
    closed_pnl, closed_win, closed_total = [], 0, 0
    open_positions = []
    for code, ts in groups.items():
        ts.sort(key=lambda x: x.get("时间", ""))
        pending = []
        for t in ts:
            if t.get("方向") == "买入":
                pending.append(t)
            elif t.get("方向") == "卖出" and pending:
                b = pending.pop(0)
                pnl = (to_float(t.get("价格")) - to_float(b.get("价格"))) * to_float(t.get("数量(股)"))
                closed_pnl.append(pnl)
                closed_total += 1
                if pnl > 0:
                    closed_win += 1
        open_positions.extend(pending)
    total_pnl = sum(closed_pnl)
    return {"总记录数": len(trades), "已平仓": closed_total,
            "胜率%": round(closed_win / closed_total * 100, 2) if closed_total else 0,
            "总盈亏(元)": round(total_pnl, 2),
            "持仓中": len(open_positions)}
