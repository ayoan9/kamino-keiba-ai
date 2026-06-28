from __future__ import annotations

import csv
import io
import os
from datetime import datetime

import pandas as pd
import streamlit as st

from horse_ai.core import (
    add_betting_journal_entries,
    add_betting_journal_entry,
    betting_journal_entries,
    extract_netkeiba_race_table_image_with_tesseract,
    extract_screenshot_with_macos_vision,
    load_prediction_profile,
    ocr_popular_odds_image_with_tesseract,
    parse_betting_history_text,
    parse_finish_order,
    parse_inputs,
)
from horse_ai.jra_fetcher import fetch_jra_result


if os.environ.get("KAMINO_EMBED_LAB") != "1":
    st.set_page_config(
        page_title="買い目実績ラボ｜競馬予想AI",
        page_icon="📝",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

st.markdown(
    """
    <style>
    :root {--ledger-green:#176a4a;--ledger-deep:#0f3d32;--ledger-gold:#d99a22;--ledger-red:#c84630;--ledger-ink:#26322f;--ledger-muted:#68736f;--ledger-paper:#fffaf0;--ledger-line:#e2d3b5;}
    .stApp {background:linear-gradient(180deg,#f5efe1 0%,#faf7ef 42%,#f3ead8 100%);color:var(--ledger-ink);}
    .block-container {max-width:1160px;padding-top:1.2rem;padding-bottom:4rem;}
    [data-testid="stSidebar"] {background:#f8f0df;}
    .lab-hero {
        position:relative;
        overflow:hidden;
        padding: 26px 28px;
        border-radius: 6px;
        background:
            linear-gradient(135deg, rgba(23,106,74,.98) 0%, rgba(15,61,50,.98) 64%, rgba(217,154,34,.95) 64%);
        color: white;
        margin-bottom: 14px;
        box-shadow: 0 12px 28px rgba(60,45,20,.16);
        border-top: 5px solid var(--ledger-gold);
    }
    .lab-hero:after {
        content:"";
        position:absolute;
        right:-42px;
        top:-38px;
        width:190px;
        height:190px;
        border:2px solid rgba(255,255,255,.3);
        border-radius:50%;
    }
    .lab-kicker {display:inline-flex;align-items:center;gap:.42rem;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.34);border-radius:999px;padding:.28rem .66rem;font-size:.78rem;font-weight:850;letter-spacing:.06em;margin-bottom:.55rem;}
    .lab-hero h1 { margin: 0 0 6px; font-size: 2.04rem; letter-spacing: .04em; line-height:1.25; }
    .lab-hero p { margin: 0; opacity: .92; max-width: 720px; line-height:1.65; }
    .lab-nav {
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:1rem;
        padding:12px 14px;
        margin:0 0 16px;
        background:#fffdf7;
        border:1px solid var(--ledger-line);
        border-left:6px solid var(--ledger-green);
        border-radius:6px;
        box-shadow:0 4px 12px rgba(60,45,20,.06);
    }
    .lab-nav strong {display:block;color:var(--ledger-deep);font-size:.96rem;}
    .lab-nav span {display:block;color:var(--ledger-muted);font-size:.78rem;line-height:1.5;margin-top:.1rem;}
    .lab-back [data-testid="stPageLink"] a {background:var(--ledger-green);color:white!important;border-radius:999px;padding:.48rem .78rem;font-weight:850;text-decoration:none;justify-content:center;}
    .metric-card {
        border:1px solid var(--ledger-line);
        border-radius:8px;
        background:#fffdf8;
        padding:13px 14px;
        box-shadow:0 4px 12px rgba(60,45,20,.055);
    }
    .hint-card {
        border: 1px dashed #d8bf89;
        background: #fff8e8;
        border-radius: 8px;
        padding: 13px 15px;
        color: #4a3d28;
        margin: 14px 0 12px;
        line-height:1.65;
    }
    .section-card {
        border:1px solid var(--ledger-line);
        background:#fffdf8;
        border-radius:10px;
        padding:18px 18px 12px;
        box-shadow:0 6px 16px rgba(60,45,20,.06);
    }
    .section-title {
        display:flex;
        align-items:center;
        gap:.5rem;
        color:var(--ledger-deep);
        font-weight:900;
        font-size:1.18rem;
        margin:0 0 .35rem;
    }
    .section-title:before {
        content:"";
        width:9px;
        height:28px;
        border-radius:999px;
        background:linear-gradient(180deg,var(--ledger-gold),var(--ledger-red));
    }
    div[data-testid="stTabs"] button p {font-weight:850;color:#4c4030;}
    div[data-testid="stTabs"] button[aria-selected="true"] {background:#fff7e3;border-radius:999px;border:1px solid #dfc285;}
    div[data-testid="stMetric"] {
        background:#fffdf8;
        border:1px solid var(--ledger-line);
        border-radius:8px;
        padding:10px 12px;
        box-shadow:0 3px 10px rgba(60,45,20,.045);
    }
    @media (max-width: 760px) {
        .lab-hero{padding:20px 18px;border-radius:8px}.lab-hero h1{font-size:1.55rem}
        .lab-nav{display:block}.lab-back{margin-top:.75rem}
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
        "出走馬": ["出走馬", "馬", "出馬表", "horses"],
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


def ocr_uploaded_images(files) -> tuple[str, list[str]]:
    texts: list[str] = []
    notes: list[str] = []
    for file in files or []:
        try:
            data = file.getvalue()
            text = ocr_popular_odds_image_with_tesseract(data)
            if text.strip():
                texts.append(f"【{file.name}】\n{text.strip()}")
        except Exception as exc:
            notes.append(f"{getattr(file, 'name', '画像')}: OCRに失敗しました（{exc}）")
    return "\n\n".join(texts), notes


def extract_race_screenshots(files) -> tuple[dict, list[dict], str, list[str]]:
    """Use the same race-table image parser as the main prediction flow when possible."""
    merged_info: dict = {}
    merged_horses: dict[int, dict] = {}
    texts: list[str] = []
    notes: list[str] = []
    for file in files or []:
        data = file.getvalue()
        name = getattr(file, "name", "画像")
        mime = getattr(file, "type", "") or "image/png"
        try:
            info, horses, text, warnings = extract_screenshot_with_macos_vision(data, name, mime)
            merged_info.update({k: v for k, v in info.items() if v not in ("", None)})
            for horse in horses:
                number = str(horse.get("馬番", "")).strip()
                if number.isdigit():
                    merged_horses[int(number)] = horse
            if text.strip():
                texts.append(f"【{name} / 出馬表専用解析】\n{text.strip()}")
            notes.extend(f"{name}: {warning}" for warning in warnings)
        except Exception as exc:
            notes.append(f"{name}: Mac出馬表解析は使えなかったため、Tesseract固定出馬表OCRへ切り替えます（{exc}）")
            try:
                info, horses, text, warnings = extract_netkeiba_race_table_image_with_tesseract(data, name)
                merged_info.update({k: v for k, v in info.items() if v not in ("", None)})
                for horse in horses:
                    number = str(horse.get("馬番", "")).strip()
                    if number.isdigit():
                        merged_horses[int(number)] = horse
                if text.strip():
                    texts.append(f"【{name} / Tesseract固定出馬表OCR】\n{text.strip()}")
                notes.extend(f"{name}: {warning}" for warning in warnings)
            except Exception as fixed_exc:
                notes.append(f"{name}: Tesseract固定出馬表OCRも使えなかったため、通常OCRで読み取ります（{fixed_exc}）")
                try:
                    fallback_text = ocr_popular_odds_image_with_tesseract(data)
                    if fallback_text.strip():
                        texts.append(f"【{name} / 通常OCR】\n{fallback_text.strip()}")
                        fallback_info, fallback_horses = parse_inputs({
                            "レース情報": fallback_text,
                            "出馬表": fallback_text,
                            "過去走情報": "",
                            "コメント": "",
                            "任意メモ": "",
                        })
                        merged_info.update({k: v for k, v in fallback_info.items() if v not in ("", None)})
                        for horse in fallback_horses:
                            number = str(horse.get("馬番", "")).strip()
                            if number.isdigit() and int(number) not in merged_horses:
                                merged_horses[int(number)] = horse
                except Exception as fallback_exc:
                    notes.append(f"{name}: 通常OCRにも失敗しました（{fallback_exc}）")
    return merged_info, [merged_horses[n] for n in sorted(merged_horses)], "\n\n".join(texts), list(dict.fromkeys(notes))


def race_label_from_info(info: dict) -> str:
    parts = [
        str(info.get("日付", "") or ""),
        str(info.get("競馬場", "") or ""),
        f'{info.get("レース番号")}R' if info.get("レース番号") else "",
        str(info.get("レース名", "") or ""),
    ]
    return " ".join(part for part in parts if part).strip()


def horses_text_from_rows(horses: list[dict]) -> str:
    lines = []
    for horse in horses:
        no = str(horse.get("馬番", "") or "").strip()
        name = str(horse.get("馬名", "") or "").strip()
        pop = str(horse.get("人気", "") or "").strip()
        odds = str(horse.get("単勝オッズ", "") or "").strip()
        extras = " ".join(part for part in [f"{pop}人気" if pop else "", f"単勝{odds}" if odds else ""] if part)
        if no or name:
            lines.append(" ".join(part for part in [no, name, extras] if part))
    return "\n".join(lines)


def result_text_from_ocr(text: str) -> str:
    order = parse_finish_order(text)
    if order:
        return "\n".join(f"{idx}着 {number}番" for idx, number in enumerate(order[:10], 1))
    return ""


st.markdown(
    """
    <div class="lab-hero">
      <div class="lab-kicker">📝 BETTING RESULT LEDGER</div>
      <h1>買い目実績ラボ</h1>
      <p>ここは予想作成画面ではなく、出走馬・買い目・結果・振り返りだけを残す実績台帳です。細かい評価やスコアは扱いません。</p>
    </div>
    """,
    unsafe_allow_html=True,
)

nav_col1, nav_col2 = st.columns([4, 1.25])
with nav_col1:
    st.markdown(
        '<div class="lab-nav"><div><strong>現在のページ：買い目実績ラボ</strong>'
        '<span>本サイトとは別ページです。レース予想に戻る場合は右のボタンを使ってください。</span></div></div>',
        unsafe_allow_html=True,
    )
with nav_col2:
    st.markdown('<div class="lab-back">', unsafe_allow_html=True)
    st.link_button("予想画面へ戻る", "/", icon="🏇", width="stretch")
    st.markdown("</div>", unsafe_allow_html=True)

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

st.markdown('<div class="hint-card">1レースごとに「何が走って、何を買って、結果がどうで、何を反省したか」だけを残します。蓄積した実績は、裏側で次回以降の買い目提案の参考にします。</div>', unsafe_allow_html=True)

tabs = st.tabs(["スクショ取込", "実績を登録", "履歴インポート", "蓄積一覧"])

with tabs[0]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">スクショから実績候補を作る</div>', unsafe_allow_html=True)
    st.caption("出走表と買い目のスクショを入れるだけで、レース情報・出走馬・買い目を候補化します。結果スクショがあれば結果も拾います。")
    race_images = st.file_uploader(
        "出走表・レース情報のスクショ",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="lab_race_screenshots",
    )
    bet_images = st.file_uploader(
        "買い目・投票履歴のスクショ",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="lab_bet_screenshots",
    )
    result_images = st.file_uploader(
        "結果スクショ（任意）",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="lab_result_screenshots",
    )
    auto_fetch_result = st.checkbox("レース情報が取れたらJRA公式から結果取得も試す", value=False)
    if st.button("スクショを解析して候補を作成", type="primary", disabled=not (race_images or bet_images or result_images)):
        race_info, horses, race_ocr, race_notes = extract_race_screenshots(race_images)
        bet_ocr, bet_notes = ocr_uploaded_images(bet_images)
        result_ocr, result_notes = ocr_uploaded_images(result_images)
        notes = race_notes + bet_notes + result_notes
        if not horses and race_ocr.strip():
            fallback_info, fallback_horses = parse_inputs({"レース情報": race_ocr, "出馬表": race_ocr, "過去走情報": "", "コメント": "", "任意メモ": ""})
            race_info.update({k: v for k, v in fallback_info.items() if v not in ("", None)})
            horses = fallback_horses
        parsed_bets, bet_parse_notes = parse_betting_history_text(bet_ocr, "スクショ取込") if bet_ocr.strip() else ([], [])
        notes.extend(bet_parse_notes)
        result_text = result_text_from_ocr(result_ocr)
        if auto_fetch_result and not result_text:
            try:
                jra_result = fetch_jra_result(race_info)
                result_text = jra_result.get("確定着順", "")
                notes.append("JRA公式から結果を取得しました。")
            except Exception as exc:
                notes.append(f"JRA結果取得はできませんでした: {exc}")
        st.session_state["lab_screenshot_candidate"] = {
            "race_label": race_label_from_info(race_info),
            "horses_text": horses_text_from_rows(horses),
            "bets_text": "\n".join(str(row.get("買い目", "")) for row in parsed_bets if str(row.get("買い目", "")).strip()),
            "stake": sum(int(row.get("購入額", 0) or 0) for row in parsed_bets),
            "return": sum(int(row.get("払戻額", 0) or 0) for row in parsed_bets),
            "result": result_text,
            "notes": notes,
            "ocr": "\n\n".join(part for part in [race_ocr, bet_ocr, result_ocr] if part.strip()),
        }
        st.rerun()
    candidate = st.session_state.get("lab_screenshot_candidate")
    if candidate:
        st.markdown("#### 取込候補")
        for note in candidate.get("notes", []):
            st.info(note)
        c1, c2 = st.columns(2)
        with c1:
            candidate_race = st.text_input("レース", value=candidate.get("race_label", ""), key="candidate_race_label")
            candidate_horses = st.text_area("出走馬", value=candidate.get("horses_text", ""), height=150, key="candidate_horses")
            candidate_bets = st.text_area("買い目", value=candidate.get("bets_text", ""), height=150, key="candidate_bets")
        with c2:
            candidate_stake = st.number_input("購入額", min_value=0, step=100, value=int(candidate.get("stake", 0) or 0), key="candidate_stake")
            candidate_return = st.number_input("払戻額", min_value=0, step=100, value=int(candidate.get("return", 0) or 0), key="candidate_return")
            candidate_result = st.text_area("結果", value=candidate.get("result", ""), height=120, key="candidate_result")
            candidate_review = st.text_area("振り返り", height=120, placeholder="例）軸は良かったが、相手候補の拾い方を見直したい。", key="candidate_review")
        with st.expander("OCR全文を確認"):
            st.text_area("OCR結果", candidate.get("ocr", ""), height=260)
        if st.button("この候補を実績として保存", type="primary"):
            try:
                updated = add_betting_journal_entry({
                    "レース": candidate_race,
                    "出走馬": candidate_horses,
                    "情報源": "スクショ取込",
                    "券種": "複数券種" if "\n" in candidate_bets.strip() else "",
                    "買い目": candidate_bets,
                    "購入額": int(candidate_stake),
                    "払戻額": int(candidate_return),
                    "結果": candidate_result,
                    "振り返り": candidate_review,
                    "次回への学び": candidate_review,
                    "登録日時": datetime.now().isoformat(timespec="seconds"),
                })
                st.success(f'保存しました。累計{updated.get("betting_journal", {}).get("count", 0)}件です。')
                del st.session_state["lab_screenshot_candidate"]
                st.rerun()
            except Exception as exc:
                st.error(f"保存できませんでした: {exc}")
    st.markdown("</div>", unsafe_allow_html=True)

with tabs[1]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">1レースの実績を登録</div>', unsafe_allow_html=True)
    st.caption("細かい採点は不要です。出走馬・買い目・結果・振り返りだけ残せば十分です。")
    race_label = st.text_input("レース", placeholder="例）2026-06-28 福島11R ラジオNIKKEI賞")
    horses_text = st.text_area("出走馬", height=120, placeholder="例）5 ファイアンクランツ\n8 センツブラッド\n14 トータルクラリティ")
    bets = st.text_area("買い目", height=120, placeholder="例）ワイド 5-8 1,000円\n馬連 5-8 500円")
    c1, c2, c3 = st.columns(3)
    with c1:
        source = st.selectbox("情報源", ["netkeiba", "IPAT", "JRA", "他ツール", "手入力"])
    with c2:
        stake_input = st.number_input("購入額", min_value=0, step=100, value=0)
    with c3:
        return_input = st.number_input("払戻額", min_value=0, step=100, value=0)
    result = st.text_area("結果", height=90, placeholder="例）5番1着、8番4着。馬連は不的中。")
    review = st.text_area("振り返り", height=120, placeholder="例）軸は良かったが、相手を人気寄りに寄せすぎた。道悪適性をもう少し重視したい。")
    if st.button("この実績を保存", type="primary"):
        try:
            updated = add_betting_journal_entry({
                "レース": race_label,
                "出走馬": horses_text,
                "情報源": source,
                "券種": "複数券種" if "\n" in bets.strip() else "",
                "買い目": bets,
                "購入額": int(stake_input),
                "払戻額": int(return_input),
                "結果": result,
                "振り返り": review,
                "次回への学び": review,
                "登録日時": datetime.now().isoformat(timespec="seconds"),
            })
            st.success(f'保存しました。累計{updated.get("betting_journal", {}).get("count", 0)}件です。')
            st.rerun()
        except Exception as exc:
            st.error(f"保存できませんでした: {exc}")
    st.markdown("</div>", unsafe_allow_html=True)

with tabs[2]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">JRA/IPAT・netkeiba履歴から半自動取込</div>', unsafe_allow_html=True)
    st.caption("ログイン情報は保存しません。各サイトで投票履歴やMy収支を開き、表をコピーするかHTML保存したファイルを読み込ませてください。")
    source_kind = st.selectbox("履歴の種類", ["JRA/IPAT", "netkeiba My収支", "他ツール", "自動判定"], key="history_import_source")
    uploaded_history = st.file_uploader("HTML / TXT / CSVファイルを選択", type=["html", "htm", "txt", "csv"], key="history_import_file")
    pasted_history = st.text_area(
        "または履歴ページの表を貼り付け",
        height=220,
        placeholder="例）投票履歴やMy収支の表を選択してコピー → ここに貼り付け",
        key="history_import_text",
    )
    history_text = pasted_history
    if uploaded_history:
        data = uploaded_history.getvalue()
        for enc in ("utf-8-sig", "cp932", "utf-8"):
            try:
                history_text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    source_label = {"自動判定": "履歴インポート"}.get(source_kind, source_kind)
    parsed_rows, parse_notes = parse_betting_history_text(history_text, source_label) if history_text.strip() else ([], [])
    for note in parse_notes:
        st.info(note)
    if parsed_rows:
        st.write("取込候補プレビュー")
        st.caption("レース名・購入額・払戻額がズレている場合は、この表で直してから取り込めます。振り返りは空欄のままでも後で追記できます。")
        candidate_df = pd.DataFrame(parsed_rows)
        editable_candidates = st.data_editor(
            candidate_df,
            hide_index=True,
            width="stretch",
            num_rows="dynamic",
            column_config={
                "券種": st.column_config.SelectboxColumn(options=["単勝", "複勝", "枠連", "ワイド", "馬連", "馬単", "3連複", "3連単", "その他"]),
                "購入額": st.column_config.NumberColumn(min_value=0, step=100, format="%d円"),
                "払戻額": st.column_config.NumberColumn(min_value=0, step=100, format="%d円"),
            },
            key="history_import_candidates",
        )
        valid_rows = [
            row for row in editable_candidates.to_dict("records")
            if str(row.get("買い目", "")).strip() and int(row.get("購入額", 0) or 0) >= 0
        ]
        if st.button("この候補を買い目実績に追加", type="primary", disabled=not valid_rows):
            profile_after, report = add_betting_journal_entries(valid_rows)
            if report["取込"]:
                st.success(f'{report["取込"]}件を追加しました。累計{report["累計"]}件です。')
                st.rerun()
            else:
                st.info("追加できる候補がありませんでした。")
            for message in report["エラー"]:
                st.warning(message)
    else:
        st.info("履歴を貼り付けるか、HTML/TXT/CSVファイルを選択すると候補を表示します。")

    with st.expander("CSVでまとめて取込"):
        example = "レース,出走馬,情報源,買い目,購入額,払戻額,結果,振り返り\n2026-06-28 福島11R,5 ファイアンクランツ / 8 センツブラッド,netkeiba,ワイド 5-8,1000,3200,的中,相手穴の選び方は良かった"
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
        if st.button("CSV内容をまとめて追加", type="primary", disabled=not rows):
            profile_after, report = add_betting_journal_entries(rows)
            if report["取込"]:
                st.success(f'{report["取込"]}件を追加しました。累計{report["累計"]}件です。')
                st.rerun()
            else:
                st.info("追加できる行がありませんでした。")
            for message in report["エラー"]:
                st.warning(message)
    st.markdown("</div>", unsafe_allow_html=True)

with tabs[3]:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">蓄積一覧</div>', unsafe_allow_html=True)
    entries = betting_journal_entries(limit=300)
    if entries:
        table = pd.DataFrame(entries)
        visible_cols = [col for col in ["登録日時", "レース", "出走馬", "情報源", "買い目", "購入額", "払戻額", "収支", "結果", "振り返り"] if col in table.columns]
        st.dataframe(table[visible_cols], hide_index=True, width="stretch")
        st.download_button(
            "蓄積データを書き出す",
            table.to_csv(index=False).encode("utf-8-sig"),
            "betting_journal_export.csv",
            "text/csv",
        )
    else:
        st.info("まだ買い目実績はありません。")
    st.markdown("</div>", unsafe_allow_html=True)
