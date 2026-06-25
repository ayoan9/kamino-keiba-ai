from __future__ import annotations

from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def _font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc" if bold else "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if Path(path).exists(): return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_summary(state: dict) -> Image.Image:
    img = Image.new("RGB", (1800, 1250), "#f6f1e6"); d = ImageDraw.Draw(img)
    navy, gold, ink, white = "#17324d", "#c89b3c", "#20252b", "#ffffff"
    d.rectangle((0, 0, 1800, 145), fill=navy)
    info = state.get("race_info", {}); title = f"{info.get('レース名','レース未設定')}  |  {info.get('競馬場','')} {info.get('芝/ダート','')}{info.get('距離','')}m  {info.get('馬場','')}  発走 {info.get('発走時刻','')}"
    d.text((55, 38), title, font=_font(38, True), fill=white)
    d.text((55, 98), "競馬予想AI｜カミノ競馬クラブ制作 — 払戻・利益は目安であり、利益を保証しません", font=_font(18), fill="#dce7f0")
    panels = [(40,175,570,650), (600,175,1130,650), (1160,175,1760,650)]
    for box in panels: d.rounded_rectangle(box, radius=18, fill=white, outline="#d7cbb5", width=2)
    summary = state.get("summary", {})
    analysis_lines = [
        f"総評: {_ellipsize(str(summary.get('レース総評','')), 110)}",
        f"展開: {_ellipsize(str(summary.get('展開予想','')), 70)}",
        f"有利脚質: {_ellipsize(str(summary.get('有利脚質','')), 24)}",
        f"波乱度: {summary.get('波乱度','')}",
        f"買い判断: {_ellipsize(str(summary.get('買い判断','')), 48)}",
    ]
    _block(d, 70, 205, "レース分析", analysis_lines, max_y=620)
    marks = state.get("marks", {}); horses = {str(h.get("馬番")): h.get("馬名", "") for h in state.get("horses", [])}
    mark_lines = [f"{m}  {n}番  {horses.get(n,'')}" for n, m in sorted(marks.items(), key=lambda x: "◎○▲☆△消".find(x[1])) if m != "消"]
    _block(d, 630, 205, "印", mark_lines[:9], accent=gold, max_y=620)
    bet_lines = [
        f"{b['買い目']}  {b['推奨購入金額']:,}円  想定{float(b.get('現在オッズ', 0)):g}倍 / {int(b.get('想定払戻', 0)):,}円"
        for b in state.get("bets", [])
    ]
    latest = state.get("odds_history", [])[-1] if state.get("odds_history") else {}
    _block(d, 1190, 205, "買い目・オッズ", bet_lines[:8] + [f"取得: {latest.get('取得時刻','未更新')}"] + state.get("alerts", [])[:3], max_y=620, wrap_width=34)
    d.rounded_rectangle((40,680,1760,1190), radius=18, fill=white, outline="#d7cbb5", width=2)
    d.text((70, 710), "全馬評価表", font=_font(27, True), fill=navy)
    headers = ["印", "馬番", "馬名", "指数", "本命", "条件", "妙味", "総合"]
    xs = [75, 145, 230, 735, 865, 1040, 1215, 1390]
    for x, h in zip(xs, headers): d.text((x, 760), h, font=_font(18, True), fill=navy)
    rows = state.get("score_results", [])[:18]
    row_height = min(24, max(19, 350 // max(1, len(rows))))
    table_font = max(13, min(16, row_height - 5))
    y = 795
    for idx, row in enumerate(rows):
        vals = [marks.get(str(row["馬番"]), ""), str(row["馬番"]), str(row["馬名"])[:20], str(row.get("レース内指数", "-")), f"{row['本命スコア']:.2f}", f"{row['条件適性スコア']:.2f}", f"{row['妙味スコア']:.2f}", f"{row['総合スコア']:.2f}"]
        if idx % 2 == 0: d.rectangle((60, y-4, 1735, y+row_height-4), fill="#faf7f0")
        for x, v in zip(xs, vals): d.text((x, y), v, font=_font(table_font, v in "◎○▲☆"), fill=ink)
        y += row_height
        if y + row_height > 1160: break
    caution = str(summary.get("注意点", "オッズは変動します。最終購入判断はユーザー自身で行ってください。"))
    d.text((60, 1210), _ellipsize(caution, 92), font=_font(16), fill="#6e5432")
    return img


def _block(d, x, y, title, lines, accent="#17324d", max_y=640, wrap_width=29):
    d.text((x, y), title, font=_font(27, True), fill=accent); yy = y + 52
    for line in lines:
        parts = _wrap(str(line), wrap_width)
        for part in parts:
            if yy + 54 > max_y:
                d.text((x, yy), "…（続きはアプリ内で確認）", font=_font(15), fill="#7a6a58")
                return
            d.text((x, yy), part, font=_font(17), fill="#20252b"); yy += 28
        yy += 7


def _wrap(text: str, width: int):
    return [text[i:i+width] for i in range(0, len(text), width)] or [""]


def _ellipsize(text: str, limit: int):
    return text if len(text) <= limit else text[:max(0, limit-1)] + "…"


def image_bytes(image: Image.Image, fmt: str) -> bytes:
    bio = BytesIO(); image.save(bio, format=fmt, resolution=150.0); return bio.getvalue()
