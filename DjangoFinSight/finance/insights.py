"""Perhitungan insight dari master.csv untuk dashboard.

Semua logika angka ada di sini (bukan di view/template), jadi mudah dites
dan bisa dipakai ulang kalau nanti sumber data pindah dari CSV ke database.
"""
from functools import lru_cache
from pathlib import Path

import pandas as pd

DAY_NAMES = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def rp(x):
    """12345 -> 'Rp12.345'"""
    return "Rp" + f"{x:,.0f}".replace(",", ".")


def month_label(p):
    return f"{MONTH_NAMES[p.month - 1]} {p.year}"


@lru_cache(maxsize=4)
def _read(path_str, mtime):
    # mtime ikut jadi kunci cache: kalau master.csv berubah, file dibaca ulang otomatis
    df = pd.read_csv(path_str, parse_dates=["date"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    return df


def load_master(path):
    p = Path(path)
    return _read(str(p), p.stat().st_mtime).copy()


def _longest_zero_streak(daily):
    """Streak hari tanpa pengeluaran terpanjang. Tanggal yang tidak tercatat memutus streak."""
    full = daily.reindex(pd.date_range(daily.index.min(), daily.index.max()))
    is_zero = full.eq(0)
    groups = (~is_zero).cumsum()
    streaks = is_zero.groupby(groups).sum()
    longest = int(streaks.max()) if len(streaks) else 0
    if longest == 0:
        return 0, None, None
    g = streaks.idxmax()
    days = full.index[(groups == g) & is_zero]
    return longest, days.min(), days.max()


def build_dashboard(df, bulan=None):
    df = df.copy()
    df["ym"] = df["date"].dt.to_period("M")

    months_all = sorted(df["ym"].unique())
    month_options = [{"value": str(p), "label": month_label(p)} for p in months_all]
    valid = {str(p) for p in months_all}
    selected = bulan if bulan in valid else ""

    # ---- tren bulanan: selalu seluruh data, sebagai konteks ----
    exp_all = df.dropna(subset=["item"])
    monthly = exp_all.groupby("ym")["amount"].sum().reindex(months_all, fill_value=0)

    # ---- data yang dipilih (satu bulan atau semua) ----
    sel = df[df["ym"] == pd.Period(selected)] if selected else df
    exp = sel.dropna(subset=["item"]).copy()
    daily = sel.groupby("date")["amount"].sum()      # hari tanpa pengeluaran = 0

    total = float(exp["amount"].sum())
    n_days = int(len(daily))
    zero_days = int((daily == 0).sum()) if n_days else 0
    n_tx = int(len(exp))

    kpi = {
        "total": rp(total),
        "avg_day": rp(daily.mean()) if n_days else rp(0),
        "median_day": rp(daily.median()) if n_days else rp(0),
        "n_tx": f"{n_tx:,}".replace(",", "."),
        "avg_tx": rp(exp["amount"].mean()) if n_tx else rp(0),
        "zero_days": f"{zero_days} dari {n_days} hari",
        "zero_pct": f"{zero_days / n_days:.0%}" if n_days else "0%",
        "delta": None,
    }
    if selected:
        prev = pd.Period(selected) - 1
        if prev in monthly.index and monthly[prev] > 0:
            pct = (total - monthly[prev]) / monthly[prev] * 100
            kpi["delta"] = {"text": f"{pct:+.1f}% vs {month_label(prev)}", "up": bool(pct > 0)}

    # ---- kategori ----
    cat = (exp.groupby("category")
              .agg(total=("amount", "sum"), freq=("amount", "size"))
              .sort_values("total", ascending=False))

    # ---- hari dalam seminggu (rata-rata per hari, hari 0 ikut dihitung) ----
    wd = (daily.groupby(daily.index.dayofweek).mean()
               .reindex(range(7)).fillna(0)) if n_days else pd.Series([0] * 7)

    # ---- item teratas ----
    top_items = exp.groupby("item")["amount"].sum().nlargest(8)

    # ---- sorotan otomatis ----
    highlights = []
    if n_tx:
        top_cat = cat["total"].idxmax()
        highlights.append({
            "title": "Kategori terbesar", "value": top_cat,
            "note": f"{cat.loc[top_cat, 'total'] / total:.0%} dari total · {rp(cat.loc[top_cat, 'total'])}"})

        big = exp.loc[exp["amount"].idxmax()]
        highlights.append({
            "title": "Transaksi termahal", "value": rp(big["amount"]),
            "note": f"{big['item']} · {big['date']:%d %b %Y}"})

        top_day = daily.idxmax()
        items_that_day = exp.loc[exp["date"] == top_day, "item"].tolist()
        highlights.append({
            "title": "Hari termahal", "value": rp(daily.max()),
            "note": f"{top_day:%d %b %Y} · " + ", ".join(items_that_day[:4])})

        busiest = int(wd.idxmax())
        highlights.append({
            "title": "Hari paling boros", "value": DAY_NAMES[busiest],
            "note": f"rata-rata {rp(wd.max())} per hari"})

        longest, start, end = _longest_zero_streak(daily)
        highlights.append({
            "title": "Streak hari hemat", "value": f"{longest} hari",
            "note": f"{start:%d %b} – {end:%d %b %Y}" if longest else "belum ada hari hemat beruntun"})

    # ---- data untuk Chart.js & tabel (hanya kolom yang perlu, tanpa raw_line) ----
    chart_data = {
        "monthly": {"labels": [month_label(p) for p in months_all],
                    "keys": [str(p) for p in months_all],
                    "values": [int(v) for v in monthly.values]},
        "selected": selected,
        "categories": {"labels": list(cat.index),
                       "total": [int(v) for v in cat["total"]],
                       "freq": [int(v) for v in cat["freq"]]},
        "weekday": {"labels": DAY_NAMES, "values": [int(round(v)) for v in wd.values]},
        "top_items": {"labels": list(top_items.index), "values": [int(v) for v in top_items.values]},
        "daily": {"labels": [f"{d:%d %b}" for d in daily.index],
                  "values": [int(v) for v in daily.values]},
    }

    rows = [
        {"d": r.date.strftime("%Y-%m-%d"), "i": r.item, "a": int(r.amount),
         "c": r.category if isinstance(r.category, str) else "Tanpa kategori"}
        for r in exp.sort_values("date", kind="stable").itertuples()
    ]

    return {
        "month_options": month_options,
        "selected": selected,
        "selected_label": month_label(pd.Period(selected)) if selected else "Semua bulan",
        "period_text": (f"{sel['date'].min():%d %b %Y} – {sel['date'].max():%d %b %Y}" if len(sel) else "-"),
        "kpi": kpi,
        "highlights": highlights,
        "chart_data": chart_data,
        "rows": rows,
        "category_options": list(cat.index),
    }
