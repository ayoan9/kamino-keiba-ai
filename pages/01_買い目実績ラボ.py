from __future__ import annotations

import csv
import io
import json
from datetime import datetime

import pandas as pd
import streamlit as st

from horse_ai.core import (
    add_betting_journal_entries,
    add_betting_journal_entry,
    betting_journal_entries,
    load_prediction_profile,
    prediction_policy_prompt,
    save_prediction_profile,
)


st.set_page_config(
    page_title="買い目実績ラボ｜競馬予想AI",
    page_icon="📝",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .lab-hero {
        padding: 22px 24px;
        border-radius: 20px;
        background: linear-gradient(135deg, #12375f 0%, #0f6fb2 58%, #f5f7fb 58%);
        color: white;
        margin-bottom: 18px;
        box-shadow: 0 14px 38px rgba(18,55,95,.16);
    }
    .lab-hero h1 { margin: 0 0 6px; font-size: 2rem; letter-spacing: .03em; }
    .lab-hero p { margin: 0; opacity: .9; max-width: 720px; }
    .hint-card {
        border: 1px solid #d9e2ef;
        background: #f8fbff;
        border-radius: 16px;
        padding: 14px 16px;
        color: #27415f;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def to_int(value) -> int:
    text = str(value or "").replace(",", "").replace("円", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return 0


def normalize_row(row: dict) -> dict:
    aliases = {
        "レース": ["レース", "レース名", "race"],
        "情報源": ["情報源", "購入元", "source"],
        "券種": ["券種", "馬券種", "ticket"],
        "買い目": ["買い目", "bet", "bets"],
        "購入額": ["購入額", "投資額", "金額", "stake"],
        "払戻額": ["払戻額", "回収額", "払戻", "return", "payout"],
        "買った理由": ["買った理由", "理由", "狙い", "reason"],
        "結果": ["結果", "着順", "result"],
        "振り返り": ["振り返り", "反省", "review"],
        "次回への学び": ["次回への学び", "学び", "lesson"],
        "登録日時": ["登録日時", "日付", "date"],
    }
    normalized = {}
    for canonical, keys in aliases.items():
        normalized[canonical] = next((row.get(key, "") for key in keys if key in row and str(row.get(key, "")).strip()), "")
    normalized["購入額"] = to_int(normalized.get("購入額"))
    normalized["払戻額"] = to_int(normalized.get("払戻額"))
    normalized.setdefault("情報源", "手入力")
    return normalized


def parse_csv_text(text: str) -> list[dict]:
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    return [normalize_row(row) for row in reader]


st.markdown(
    """
    <div class="lab-hero">
      <h1>買い目実績ラボ</h1>
      <p>netkeiba・IPAT・他ツールで買った馬券や振り返りを、予想AIの学習ノートとして蓄積します。3年分の実績も少しずつ投入できます。</p>
    </div>
    """,
    unsafe_allow_html=True,
)

profile = load_prediction_profile()
journal = profile.get("betting_journal", {})
count = int(journal.get("count", 0) or 0)
stake = int(journal.get("stake_total", 0) or 0)
returns = int(journal.get("return_total", 0) or 0)
profit = int(journal.get("profit_total", 0) or 0)
hit_count = int(journal.get("hit_count", 0) or 0)
roi = returns / stake * 100 if stake else 0
hit_rate = hit_count / count * 100 if count else 0

m1, m2, m3, m4 = st.columns(4)
m1.metric("記録数", f"{count}件")
m2.metric("累計収支", f"{profit:+,}円")
m3.metric("回収率", f"{roi:.0f}%" if stake else "-")
m4.metric("的中率", f"{hit_rate:.0f}%" if count else "-")

st.markdown('<div class="hint-card">ここに蓄積した予想ロジック・買い目実績・振り返りは、次回以降のAI仮評価と買い目提案の参考情報になります。まずは予想方針だけでも、CSVで3年分を少しずつ入れてもOKです。</div>', unsafe_allow_html=True)

tabs = st.tabs(["予想ロジック", "1件ずつ登録", "CSVでまとめて取込", "蓄積一覧", "AIに渡す学習内容"])

with tabs[0]:
    st.subheader("自分の予想方針")
    st.caption("日頃の予想軸をここに集約します。レースごとの入力欄ではなく、このラボに保存した内容を共通の判断軸として使います。")
    policy_text = st.text_area(
        "予想AIに常に共有したい方針",
        value=str(profile.get("policy", "") or ""),
        height=220,
        placeholder="例）近走の着順より内容を重視。小回りは位置取り、道悪は馬場適性とパワー型を重視。過剰人気は妙味を下げ、軸は崩れにくさを優先する。",
    )
    if st.button("予想ロジックを保存", type="primary"):
        save_prediction_profile(policy_text)
        st.success("保存しました。次回以降のAI仮評価と買い目提案の参考にします。")
        st.rerun()
    learned = profile.get("result_learning", {})
    st.markdown("#### 現在AIに渡される学習素材")
    c1, c2, c3 = st.columns(3)
    c1.metric("手修正履歴", f'{int(profile.get("learning_samples", 0) or 0)}R')
    c2.metric("結果振り返り", f'{int(learned.get("reviews", 0) or 0)}R')
    c3.metric("買い目実績", f"{count}件")
    st.info("過去実績が増えるほど、券種の選び方・点数の広げ方・妙味判断の傾向を買い目提案へ反映しやすくなります。")

with tabs[1]:
    st.subheader("1件ずつ登録")
    c1, c2 = st.columns(2)
    with c1:
        race_label = st.text_input("レース", placeholder="例）2026-06-28 福島11R ラジオNIKKEI賞")
        source = st.selectbox("情報源", ["netkeiba", "IPAT", "JRA", "他ツール", "手入力"])
        ticket = st.selectbox("券種", ["単勝", "複勝", "枠連", "ワイド", "馬連", "馬単", "3連複", "3連単", "複数券種", "その他"])
        stake_input = st.number_input("購入額", min_value=0, step=100, value=0)
        return_input = st.number_input("払戻額", min_value=0, step=100, value=0)
    with c2:
        bets = st.text_area("買い目", height=110, placeholder="例）ワイド 5-8 1,000円\n馬連 5-8 500円")
        reason = st.text_area("買った理由", height=100)
    result = st.text_area("結果", height=80)
    review = st.text_area("振り返り", height=90)
    lesson = st.text_area("次回への学び", height=90)
    if st.button("この買い目を学習ノートに追加", type="primary"):
        try:
            updated = add_betting_journal_entry({
                "レース": race_label,
                "情報源": source,
                "券種": ticket,
                "買い目": bets,
                "購入額": int(stake_input),
                "払戻額": int(return_input),
                "買った理由": reason,
                "結果": result,
                "振り返り": review,
                "次回への学び": lesson,
                "登録日時": datetime.now().isoformat(timespec="seconds"),
            })
            st.success(f'追加しました。累計{updated.get("betting_journal", {}).get("count", 0)}件です。')
            st.rerun()
        except Exception as exc:
            st.error(f"追加できませんでした: {exc}")

with tabs[2]:
    st.subheader("CSVでまとめて取込")
    example = "レース,情報源,券種,買い目,購入額,払戻額,買った理由,結果,振り返り,次回への学び\n2026-06-28 福島11R,netkeiba,ワイド,5-8,1000,3200,本命信頼も単勝妙味薄,的中,相手穴の選び方は良かった,小回り重馬場は位置取り重視"
    st.download_button("CSVテンプレートをダウンロード", example.encode("utf-8-sig"), "betting_journal_template.csv", "text/csv")
    uploaded = st.file_uploader("CSVファイルを選択", type=["csv"])
    pasted = st.text_area("またはCSVを貼り付け", height=180, placeholder=example)
    rows: list[dict] = []
    if uploaded:
        text = uploaded.getvalue().decode("utf-8-sig")
        rows.extend(parse_csv_text(text))
    if pasted.strip():
        rows.extend(parse_csv_text(pasted))
    if rows:
        st.write("取込プレビュー")
        st.dataframe(pd.DataFrame(rows).head(50), hide_index=True, width="stretch")
    if st.button("プレビュー内容をまとめて学習に追加", type="primary", disabled=not rows):
        profile_after, report = add_betting_journal_entries(rows)
        if report["取込"]:
            st.success(f'{report["取込"]}件を追加しました。累計{report["累計"]}件です。')
            st.rerun()
        else:
            st.info("追加できる行がありませんでした。")
        for message in report["エラー"]:
            st.warning(message)

with tabs[3]:
    st.subheader("蓄積一覧")
    entries = betting_journal_entries(limit=300)
    if entries:
        table = pd.DataFrame(entries)
        visible_cols = [col for col in ["登録日時", "レース", "情報源", "券種", "買い目", "購入額", "払戻額", "収支", "買った理由", "振り返り", "次回への学び"] if col in table.columns]
        st.dataframe(table[visible_cols], hide_index=True, width="stretch")
        st.download_button(
            "蓄積データを書き出す",
            table.to_csv(index=False).encode("utf-8-sig"),
            "betting_journal_export.csv",
            "text/csv",
        )
    else:
        st.info("まだ買い目実績はありません。")

with tabs[4]:
    st.subheader("AIに渡す学習内容")
    prompt_text = prediction_policy_prompt(load_prediction_profile())
    if prompt_text.strip():
        st.text_area("次回以降のAI仮評価に共有される要約", prompt_text, height=360)
    else:
        st.info("まだAIへ共有する実績メモはありません。")
