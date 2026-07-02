from __future__ import annotations

import csv
import io
import json
import os
import re
import uuid
from datetime import datetime
from itertools import combinations, permutations

import pandas as pd
import streamlit as st

from horse_ai.core import (
    add_betting_journal_entries,
    add_betting_journal_entry,
    betting_journal_entries,
    cloud_storage_enabled,
    cloud_storage_status,
    data_path,
    extract_netkeiba_newspaper_pdf,
    extract_netkeiba_race_table_image_with_tesseract,
    extract_screenshot_with_macos_vision,
    load_cloud_json,
    load_prediction_profile,
    ocr_popular_odds_image_with_tesseract,
    parse_betting_history_text,
    parse_inputs,
    save_cloud_json,
)


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


def extract_race_screenshots(files) -> tuple[dict, list[dict], str, list[str]]:
    """Use the same race-data parsers as the main prediction flow when possible."""
    merged_info: dict = {}
    merged_horses: dict[int, dict] = {}
    texts: list[str] = []
    notes: list[str] = []

    def expected_count_from_info(info: dict) -> int:
        try:
            return int(str(info.get("頭数", "") or "0").replace("頭", ""))
        except ValueError:
            return 0

    def add_horses(horses: list[dict], prefer_sequential: bool = False) -> None:
        expected_count = expected_count_from_info(merged_info)
        for index, horse in enumerate(horses, 1):
            number = str(horse.get("馬番", "")).strip()
            fixed_number = 0
            if prefer_sequential and expected_count and index <= expected_count:
                fixed_number = index
            elif number.isdigit():
                fixed_number = int(number)
                # Generic OCR often joins frame+horse number: "11" for horse 1,
                # "22" for horse 2.  If the trailing digits match visual order,
                # keep the row-order number.
                if expected_count and fixed_number > expected_count and number.endswith(str(index)):
                    fixed_number = index
            if fixed_number:
                horse["馬番"] = fixed_number
                merged_horses[fixed_number] = horse

    for file in files or []:
        data = file.getvalue()
        name = getattr(file, "name", "画像")
        mime = getattr(file, "type", "") or "image/png"
        is_pdf = mime == "application/pdf" or str(name).lower().endswith(".pdf")
        if is_pdf:
            try:
                info, horses, summary, text, warnings = extract_netkeiba_newspaper_pdf(data)
                merged_info.update({k: v for k, v in info.items() if v not in ("", None)})
                add_horses(horses)
                if text.strip():
                    texts.append(f"【{name} / netkeiba競馬新聞PDF】\n{text.strip()}")
                pdf_notes = [f"{name}: {warning}" for warning in warnings]
                if summary.get("展開予想"):
                    pdf_notes.append(f"{name}: {summary.get('展開予想')}")
                notes.extend(pdf_notes)
                continue
            except Exception as exc:
                notes.append(f"{name}: netkeiba競馬新聞PDF解析に失敗したため画像/OCR解析へ切り替えます（{exc}）")
        try:
            info, horses, text, warnings = extract_screenshot_with_macos_vision(data, name, mime)
            merged_info.update({k: v for k, v in info.items() if v not in ("", None)})
            add_horses(horses)
            if text.strip():
                texts.append(f"【{name} / 出馬表専用解析】\n{text.strip()}")
            notes.extend(f"{name}: {warning}" for warning in warnings)
        except Exception as exc:
            notes.append(f"{name}: Mac出馬表解析は使えなかったため、Tesseract固定出馬表OCRへ切り替えます（{exc}）")
            try:
                info, horses, text, warnings = extract_netkeiba_race_table_image_with_tesseract(data, name)
                merged_info.update({k: v for k, v in info.items() if v not in ("", None)})
                add_horses(horses)
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
                        add_horses(fallback_horses)
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


def horse_choice_label(horse: dict) -> str:
    no = str(horse.get("馬番", "") or "").strip()
    name = str(horse.get("馬名", "") or "").strip()
    return " ".join(part for part in [f"{no}番" if no else "", name] if part).strip()


def horse_choices_from_rows(horses: list[dict]) -> list[str]:
    choices = [horse_choice_label(horse) for horse in horses if horse_choice_label(horse)]
    return [""] + choices


def horse_choices_from_text(text: str, fallback_horses: list[dict]) -> list[str]:
    choices: list[str] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"(\d{1,2})(?:番)?\s+(.+)", line)
        if match:
            no, rest = match.groups()
            name = re.sub(r"\s+\d+人気.*$", "", rest).strip()
            choices.append(f"{no}番 {name}")
    if not choices:
        choices = horse_choices_from_rows(fallback_horses)[1:]
    return [""] + list(dict.fromkeys(choices))


def compact_horse_number(label: str) -> str:
    match = re.search(r"(\d{1,2})\s*番", str(label or ""))
    if match:
        return match.group(1)
    match = re.search(r"^\s*(\d{1,2})\b", str(label or ""))
    return match.group(1) if match else ""


def unique_numbers(values: list[str]) -> list[str]:
    numbers = [compact_horse_number(value) for value in values]
    return list(dict.fromkeys(number for number in numbers if number))


def combo_text(ticket: str, numbers: tuple[str, ...] | list[str]) -> str:
    separator = "→" if ticket in {"馬単", "3連単"} else "-"
    return separator.join(numbers)


def expand_bet_combos(ticket: str, method: str, axis1: str, axis2: str, opponents: list[str]) -> list[tuple[str, ...]]:
    axis = unique_numbers([axis1, axis2])
    opponents = [number for number in unique_numbers(opponents) if number not in axis]
    selected = unique_numbers(axis + opponents)
    if not ticket or not method:
        return []
    if ticket in {"単勝", "複勝"}:
        return [(number,) for number in selected]
    if ticket in {"枠連", "ワイド", "馬連"}:
        if method == "ボックス":
            return list(combinations(selected, 2))
        if method in {"軸流し", "通常"} and axis:
            return [tuple(sorted((a, b), key=int)) for a in axis for b in opponents]
        return list(combinations(selected[:2], 2)) if len(selected) >= 2 else []
    if ticket == "馬単":
        if method == "ボックス":
            return list(permutations(selected, 2))
        if method in {"マルチ", "軸流しマルチ"} and axis:
            return [(a, b) for a in axis for b in opponents] + [(b, a) for a in axis for b in opponents]
        if method in {"軸流し", "通常"} and axis:
            return [(a, b) for a in axis for b in opponents]
        return [tuple(selected[:2])] if len(selected) >= 2 else []
    if ticket == "3連複":
        if method == "ボックス":
            return list(combinations(selected, 3))
        if method in {"軸流し", "通常"} and len(axis) >= 2:
            return [tuple(sorted((axis[0], axis[1], b), key=int)) for b in opponents]
        if method in {"軸流し", "通常"} and len(axis) == 1:
            return [tuple(sorted((axis[0], b, c), key=int)) for b, c in combinations(opponents, 2)]
        return list(combinations(selected[:3], 3)) if len(selected) >= 3 else []
    if ticket == "3連単":
        if method == "ボックス":
            return list(permutations(selected, 3))
        if method in {"マルチ", "軸流しマルチ"} and len(axis) >= 2:
            combos: list[tuple[str, ...]] = []
            for b in opponents:
                combos.extend(permutations([axis[0], axis[1], b], 3))
            return combos
        if method in {"マルチ", "軸流しマルチ"} and len(axis) == 1:
            combos: list[tuple[str, ...]] = []
            for b, c in combinations(opponents, 2):
                combos.extend(permutations([axis[0], b, c], 3))
            return combos
        if method in {"軸流し", "通常"} and len(axis) >= 2:
            return [(axis[0], axis[1], b) for b in opponents]
        if method in {"軸流し", "通常"} and len(axis) == 1:
            return [(axis[0], b, c) for b, c in permutations(opponents, 2)]
        return [tuple(selected[:3])] if len(selected) >= 3 else []
    return []


def build_bet_lines(rows: list[dict]) -> tuple[str, int, list[str]]:
    lines: list[str] = []
    ticket_types: list[str] = []
    total = 0
    for row in rows:
        ticket = str(row.get("券種", "") or "").strip()
        method = str(row.get("買い方", "") or "通常").strip() or "通常"
        stake = to_int(row.get("1点金額", row.get("金額", 0)))
        if not ticket or stake <= 0:
            continue
        opponents = [row.get(key, "") for key in ("相手1", "相手2", "相手3", "相手4", "相手5")]
        combos = expand_bet_combos(ticket, method, str(row.get("軸1", "") or ""), str(row.get("軸2", "") or ""), opponents)
        combos = list(dict.fromkeys(combos))
        if not combos:
            continue
        combo_lines = [f"{ticket} {combo_text(ticket, combo)} {stake:,}円" for combo in combos]
        header = f"【{ticket} {method}】{len(combos)}点 / 1点{stake:,}円"
        lines.append(header + "\n" + "\n".join(combo_lines))
        ticket_types.append(ticket)
        total += stake * len(combos)
    return "\n".join(lines), total, sorted(set(ticket_types))


def joined_selected(values: list[str]) -> str:
    return "、".join(str(v) for v in values if str(v).strip())


def safe_lab_draft_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", str(value or ""))[:64]


def current_lab_draft_id() -> str:
    draft_id = safe_lab_draft_id(st.query_params.get("lab_draft", ""))
    if not draft_id:
        draft_id = uuid.uuid4().hex[:12]
        st.query_params["view"] = "lab"
        st.query_params["lab_draft"] = draft_id
    return draft_id


def lab_draft_path(draft_id: str):
    return data_path("data/lab_drafts") / f"{safe_lab_draft_id(draft_id)}.json"


def load_lab_draft(draft_id: str) -> dict:
    cloud_payload = load_cloud_json("lab_drafts", safe_lab_draft_id(draft_id))
    if isinstance(cloud_payload, dict):
        return cloud_payload
    path = lab_draft_path(draft_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_lab_draft(draft_id: str, payload: dict) -> None:
    try:
        path = lab_draft_path(draft_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        payload = {**payload, "updated_at": datetime.now().isoformat(timespec="seconds")}
        save_cloud_json("lab_drafts", safe_lab_draft_id(draft_id), payload)
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        pass


def option_index(options: list, value) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


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

lab_draft_id = current_lab_draft_id()
loaded_lab_draft = load_lab_draft(lab_draft_id)
if "lab_screenshot_candidate" not in st.session_state and loaded_lab_draft.get("candidate"):
    st.session_state["lab_screenshot_candidate"] = loaded_lab_draft["candidate"]
if loaded_lab_draft.get("updated_at"):
    st.caption(f"下書き自動保存: {loaded_lab_draft['updated_at']} / draft {lab_draft_id}")
lab_cloud_status = cloud_storage_status()
st.caption(f"保存先: {'Supabase + ローカル' if cloud_storage_enabled() else 'ローカル'}")
if not lab_cloud_status["enabled"]:
    st.caption("Supabase設定: " + " / ".join(lab_cloud_status["missing"]) + " が未設定")

profile = load_prediction_profile()
journal = profile.get("betting_journal", {})
count = int(journal.get("count", 0) or 0)
st.markdown(
    f'<div class="hint-card">登録済み実績：<strong>{count}件</strong>。'
    'ここでは収支管理ではなく、「何を買い、どういうレース質で、何を学んだか」を蓄積します。'
    '保存した実績は次回以降の買い目提案の参考にします。</div>',
    unsafe_allow_html=True,
)

section = st.radio(
    "表示する機能",
    ["出馬表取込・選択入力", "手入力", "履歴インポート", "登録済み実績一覧"],
    horizontal=True,
    label_visibility="collapsed",
    key="lab_active_section",
)

if section == "出馬表取込・選択入力":
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">PDF・出馬表スクショから選択式で実績登録</div>', unsafe_allow_html=True)
    st.caption("基本はnetkeiba競馬新聞PDF推奨です。PDFなら文字座標から読むため、スクショOCRより安定します。買い目・結果・振り返りは、読み取った馬番候補から選ぶだけで登録できます。")
    race_images = st.file_uploader(
        "netkeiba競馬新聞PDF、または出走表・レース情報のスクショ",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="lab_race_screenshots",
    )
    if st.button("資料から出馬表を読み取る", type="primary", disabled=not race_images):
        progress = st.progress(0, text="資料を読み取る準備中（0%）")
        progress.progress(20, text="PDF・画像形式を確認しています（20%）")
        race_info, horses, race_ocr, race_notes = extract_race_screenshots(race_images)
        progress.progress(70, text="出走馬候補を整理しています（70%）")
        if not horses and race_ocr.strip():
            fallback_info, fallback_horses = parse_inputs({"レース情報": race_ocr, "出馬表": race_ocr, "過去走情報": "", "コメント": "", "任意メモ": ""})
            race_info.update({k: v for k, v in fallback_info.items() if v not in ("", None)})
            horses = fallback_horses
        st.session_state["lab_screenshot_candidate"] = {
            "race_label": race_label_from_info(race_info),
            "horses_text": horses_text_from_rows(horses),
            "horses": horses,
            "notes": race_notes,
            "ocr": race_ocr,
        }
        save_lab_draft(lab_draft_id, {"candidate": st.session_state["lab_screenshot_candidate"]})
        progress.progress(100, text="読み取り完了（100%）")
        st.rerun()
    candidate = st.session_state.get("lab_screenshot_candidate")
    if candidate:
        draft_form = loaded_lab_draft.get("form", {}) if isinstance(loaded_lab_draft.get("form", {}), dict) else {}
        st.markdown("#### 1. レースと出走馬を確認")
        for note in candidate.get("notes", []):
            st.info(note)
        horses = candidate.get("horses", []) or []
        c1, c2 = st.columns([1, 1.15])
        with c1:
            candidate_race = st.text_input("レース", value=candidate.get("race_label", ""), key="candidate_race_label")
            candidate_horses = st.text_area("出走馬", value=candidate.get("horses_text", ""), height=150, key="candidate_horses")
        with c2:
            source_options = ["netkeiba", "IPAT", "JRA", "他ツール", "手入力"]
            source = st.selectbox("購入・記録元", source_options, index=option_index(source_options, draft_form.get("source", "netkeiba")), key="candidate_source")
            candidate_return = st.number_input("払戻額", min_value=0, step=100, value=int(draft_form.get("return", 0) or 0), key="candidate_return")
            st.caption("出走馬の読み取りがズレた場合は、左の出走馬欄を直接直せます。買い目候補は下の選択肢から選びます。")
        horse_options = horse_choices_from_text(candidate_horses, horses)

        st.markdown("#### 2. 買い目を選択")
        st.caption("軸流し・マルチ・ボックスは自動で買い目に展開します。金額は1点あたりの購入額として入力してください。")
        saved_bet_rows = draft_form.get("bet_rows", []) if isinstance(draft_form.get("bet_rows", []), list) else []
        default_bet_count = min(5, max(1, len(saved_bet_rows) or 2))
        bet_count = st.number_input("買い方の行数", min_value=1, max_value=5, value=default_bet_count, step=1, key="candidate_bet_count")
        bet_rows: list[dict] = []
        ticket_options = ["", "単勝", "複勝", "枠連", "ワイド", "馬連", "馬単", "3連複", "3連単"]
        method_options = ["通常", "軸流し", "軸流しマルチ", "マルチ", "ボックス"]
        for idx in range(int(bet_count)):
            saved_row = saved_bet_rows[idx] if idx < len(saved_bet_rows) and isinstance(saved_bet_rows[idx], dict) else {}
            with st.container(border=True):
                st.caption(f"買い方 {idx + 1}")
                t1, t2, t3, t4 = st.columns([1, 1, 1, 1])
                with t1:
                    ticket = st.selectbox("券種", ticket_options, index=option_index(ticket_options, saved_row.get("券種", "")), key=f"candidate_ticket_{idx}")
                with t2:
                    method = st.selectbox("買い方", method_options, index=option_index(method_options, saved_row.get("買い方", "通常")), key=f"candidate_method_{idx}")
                with t3:
                    axis1 = st.selectbox("軸1", horse_options, index=option_index(horse_options, saved_row.get("軸1", "")), key=f"candidate_axis1_{idx}")
                with t4:
                    axis2 = st.selectbox("軸2", horse_options, index=option_index(horse_options, saved_row.get("軸2", "")), key=f"candidate_axis2_{idx}")
                o1, o2, o3, o4, o5, amount_col = st.columns([1, 1, 1, 1, 1, 1])
                with o1:
                    opponent1 = st.selectbox("相手1", horse_options, index=option_index(horse_options, saved_row.get("相手1", "")), key=f"candidate_opp1_{idx}")
                with o2:
                    opponent2 = st.selectbox("相手2", horse_options, index=option_index(horse_options, saved_row.get("相手2", "")), key=f"candidate_opp2_{idx}")
                with o3:
                    opponent3 = st.selectbox("相手3", horse_options, index=option_index(horse_options, saved_row.get("相手3", "")), key=f"candidate_opp3_{idx}")
                with o4:
                    opponent4 = st.selectbox("相手4", horse_options, index=option_index(horse_options, saved_row.get("相手4", "")), key=f"candidate_opp4_{idx}")
                with o5:
                    opponent5 = st.selectbox("相手5", horse_options, index=option_index(horse_options, saved_row.get("相手5", "")), key=f"candidate_opp5_{idx}")
                with amount_col:
                    amount = st.number_input("1点金額", min_value=0, step=100, value=to_int(saved_row.get("1点金額", 0)), key=f"candidate_amount_{idx}")
                bet_rows.append({
                    "券種": ticket,
                    "買い方": method,
                    "軸1": axis1,
                    "軸2": axis2,
                    "相手1": opponent1,
                    "相手2": opponent2,
                    "相手3": opponent3,
                    "相手4": opponent4,
                    "相手5": opponent5,
                    "1点金額": amount,
                })
        candidate_bets, candidate_stake, ticket_types = build_bet_lines(bet_rows)
        st.caption(f"購入額合計: {candidate_stake:,}円")
        if candidate_bets and st.toggle("展開された買い目を表示", value=False, key="show_expanded_bets"):
            st.code(candidate_bets, language=None)

        st.markdown("#### 3. 結果とレース質を選択")
        r1, r2, r3, r4 = st.columns(4)
        with r1:
            first = st.selectbox("1着", horse_options, index=option_index(horse_options, draft_form.get("first", "")), key="result_first")
        with r2:
            second = st.selectbox("2着", horse_options, index=option_index(horse_options, draft_form.get("second", "")), key="result_second")
        with r3:
            third = st.selectbox("3着", horse_options, index=option_index(horse_options, draft_form.get("third", "")), key="result_third")
        with r4:
            hit_options = ["不的中", "的中", "トリガミ", "見送り"]
            hit_status = st.selectbox("馬券結果", hit_options, index=option_index(hit_options, draft_form.get("hit_status", "不的中")), key="hit_status")
        p1, p2, p3, p4 = st.columns(4)
        with p1:
            pace_options = ["H", "M", "S"]
            pace_type = st.radio("ペース", pace_options, index=option_index(pace_options, draft_form.get("pace_type", "M")), horizontal=True, key="pace_type")
        with p2:
            pace_first3f = st.text_input("前半3F", value=str(draft_form.get("pace_first3f", "") or ""), placeholder="例）34.8", key="pace_first3f")
        with p3:
            pace_first5f = st.text_input("前半5F", value=str(draft_form.get("pace_first5f", "") or ""), placeholder="例）59.0", key="pace_first5f")
        with p4:
            pace_last3f = st.text_input("後半3F", value=str(draft_form.get("pace_last3f", "") or ""), placeholder="例）35.6", key="pace_last3f")
        b1, b2 = st.columns(2)
        with b1:
            track_options = ["良", "稍重", "重", "不良", "高速", "時計かかる", "内有利", "外有利", "フラット", "荒れ馬場"]
            track_condition = st.multiselect("馬場", track_options, default=[x for x in draft_form.get("track_condition", []) if x in track_options], key="track_condition")
        with b2:
            shape_options = ["逃げ残り", "先行有利", "差し有利", "追込有利", "内前有利", "外差し", "隊列縦長", "団子", "スロー瞬発戦", "持続力戦", "消耗戦"]
            race_shape = st.multiselect("展開", shape_options, default=[x for x in draft_form.get("race_shape", []) if x in shape_options], key="race_shape")

        st.markdown("#### 4. 振り返りを構造化")
        bought_reason = st.multiselect(
            "買った理由",
            ["軸信頼", "相手妙味", "オッズ妙味", "展開利", "馬場適性", "コース適性", "状態良さそう", "騎手評価", "人気過小評価", "実績重視"],
            default=[x for x in draft_form.get("bought_reason", []) if x in ["軸信頼", "相手妙味", "オッズ妙味", "展開利", "馬場適性", "コース適性", "状態良さそう", "騎手評価", "人気過小評価", "実績重視"]],
            key="bought_reason_tags",
        )
        review_options = ["軸は良かった", "軸選びミス", "相手抜け", "買い目を広げすぎ", "買い目を絞りすぎ", "オッズ判断ミス", "展開読み違い", "馬場読み違い", "ペース読み違い", "状態評価ミス", "穴馬評価成功", "人気馬軽視成功"]
        review_tags = st.multiselect(
            "振り返りタグ",
            review_options,
            default=[x for x in draft_form.get("review_tags", []) if x in review_options],
            key="review_tags",
        )
        lesson_options = ["軸の安定感を重視", "穴は相手まで", "展開利を強める", "馬場バイアスを強める", "オッズ妙味の下限を上げる", "点数を絞る", "三連系を控える", "ワイド中心にする", "人気馬の消しを慎重にする"]
        lesson_tags = st.multiselect(
            "次回に活かすこと",
            lesson_options,
            default=[x for x in draft_form.get("lesson_tags", []) if x in lesson_options],
            key="lesson_tags",
        )
        free_review = st.text_area("自由メモ", value=str(draft_form.get("free_review", "") or ""), height=100, placeholder="例）想定より流れて差し決着。軸は妥当だったが、相手を内前に寄せすぎた。", key="candidate_review")
        with st.expander("OCR全文を確認"):
            st.text_area("OCR結果", candidate.get("ocr", ""), height=260)
        lap_summary = " / ".join(part for part in [
            f"前半3F {pace_first3f}" if pace_first3f else "",
            f"前半5F {pace_first5f}" if pace_first5f else "",
            f"後半3F {pace_last3f}" if pace_last3f else "",
        ] if part) or "未入力"
        result_lines = [
            "着順: " + " / ".join(part for part in [
                f"1着 {first}" if first else "",
                f"2着 {second}" if second else "",
                f"3着 {third}" if third else "",
            ] if part),
            f"馬券結果: {hit_status}",
            f"ペース: {pace_type}",
            "ラップ: " + lap_summary,
            "馬場: " + (joined_selected(track_condition) if track_condition else "未入力"),
            "展開: " + (joined_selected(race_shape) if race_shape else "未入力"),
        ]
        structured_review = "\n".join(part for part in [
            "買った理由: " + joined_selected(bought_reason) if bought_reason else "",
            "振り返りタグ: " + joined_selected(review_tags) if review_tags else "",
            "自由メモ: " + free_review if free_review.strip() else "",
        ] if part)
        next_lesson = "次回への学び: " + joined_selected(lesson_tags) if lesson_tags else free_review
        autosave_payload = {
            "candidate": {
                **candidate,
                "race_label": candidate_race,
                "horses_text": candidate_horses,
            },
            "form": {
                "source": source,
                "return": int(candidate_return),
                "bet_rows": bet_rows,
                "bets_text": candidate_bets,
                "stake": int(candidate_stake),
                "ticket_types": ticket_types,
                "first": first,
                "second": second,
                "third": third,
                "hit_status": hit_status,
                "pace_type": pace_type,
                "pace_first3f": pace_first3f,
                "pace_first5f": pace_first5f,
                "pace_last3f": pace_last3f,
                "track_condition": track_condition,
                "race_shape": race_shape,
                "bought_reason": bought_reason,
                "review_tags": review_tags,
                "lesson_tags": lesson_tags,
                "free_review": free_review,
            },
        }
        save_lab_draft(lab_draft_id, autosave_payload)
        st.caption("この入力内容は下書きとして自動保存されています。ブラウザを閉じても同じURLから再開できます。")
        can_save = bool(candidate_bets.strip() or structured_review.strip() or any([first, second, third]))
        if st.button("この内容で実績を保存", type="primary", disabled=not can_save):
            try:
                updated = add_betting_journal_entry({
                    "レース": candidate_race,
                    "出走馬": candidate_horses,
                    "情報源": source,
                    "券種": "複数券種" if len(ticket_types) > 1 else (ticket_types[0] if ticket_types else ""),
                    "買い目": candidate_bets,
                    "購入額": int(candidate_stake),
                    "払戻額": int(candidate_return),
                    "買った理由": joined_selected(bought_reason),
                    "結果": "\n".join(result_lines),
                    "振り返り": structured_review,
                    "次回への学び": next_lesson,
                    "登録日時": datetime.now().isoformat(timespec="seconds"),
                })
                st.success(f'保存しました。累計{updated.get("betting_journal", {}).get("count", 0)}件です。')
                save_lab_draft(lab_draft_id, {})
                del st.session_state["lab_screenshot_candidate"]
                st.rerun()
            except Exception as exc:
                st.error(f"保存できませんでした: {exc}")
    st.markdown("</div>", unsafe_allow_html=True)

if section == "手入力":
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">1レースの実績を登録</div>', unsafe_allow_html=True)
    st.caption("細かい採点は不要です。出走馬・買い目・結果・振り返りだけ残せば十分です。")
    manual_form = loaded_lab_draft.get("manual_form", {}) if isinstance(loaded_lab_draft.get("manual_form", {}), dict) else {}
    race_label = st.text_input("レース", value=str(manual_form.get("race_label", "") or ""), placeholder="例）2026-06-28 福島11R ラジオNIKKEI賞")
    horses_text = st.text_area("出走馬", value=str(manual_form.get("horses_text", "") or ""), height=120, placeholder="例）5 ファイアンクランツ\n8 センツブラッド\n14 トータルクラリティ")
    bets = st.text_area("買い目", value=str(manual_form.get("bets", "") or ""), height=120, placeholder="例）ワイド 5-8 1,000円\n馬連 5-8 500円")
    c1, c2, c3 = st.columns(3)
    with c1:
        manual_source_options = ["netkeiba", "IPAT", "JRA", "他ツール", "手入力"]
        source = st.selectbox("情報源", manual_source_options, index=option_index(manual_source_options, manual_form.get("source", "netkeiba")))
    with c2:
        stake_input = st.number_input("購入額", min_value=0, step=100, value=to_int(manual_form.get("stake_input", 0)))
    with c3:
        return_input = st.number_input("払戻額", min_value=0, step=100, value=to_int(manual_form.get("return_input", 0)))
    result = st.text_area("結果", value=str(manual_form.get("result", "") or ""), height=90, placeholder="例）5番1着、8番4着。馬連は不的中。")
    review = st.text_area("振り返り", value=str(manual_form.get("review", "") or ""), height=120, placeholder="例）軸は良かったが、相手を人気寄りに寄せすぎた。道悪適性をもう少し重視したい。")
    save_lab_draft(lab_draft_id, {
        **loaded_lab_draft,
        "manual_form": {
            "race_label": race_label,
            "horses_text": horses_text,
            "bets": bets,
            "source": source,
            "stake_input": int(stake_input),
            "return_input": int(return_input),
            "result": result,
            "review": review,
        },
    })
    st.caption("手入力の途中内容も自動保存されています。同じURLから再開できます。")
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
            save_lab_draft(lab_draft_id, {})
            st.rerun()
        except Exception as exc:
            st.error(f"保存できませんでした: {exc}")
    st.markdown("</div>", unsafe_allow_html=True)

if section == "履歴インポート":
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

if section == "登録済み実績一覧":
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">登録済み実績一覧</div>', unsafe_allow_html=True)
    st.caption("保存した振り返りを確認できます。収支管理ではなく、予想ロジックの蓄積用メモとして使います。")
    list_limit = st.selectbox("表示件数", [50, 100, 200, 300], index=0, key="journal_list_limit")
    entries = betting_journal_entries(limit=int(list_limit))
    if entries:
        table = pd.DataFrame(entries)
        visible_cols = [col for col in ["登録日時", "レース", "出走馬", "情報源", "券種", "買い目", "結果", "買った理由", "振り返り", "次回への学び"] if col in table.columns]
        st.dataframe(table[visible_cols], hide_index=True, width="stretch")
        if st.toggle("CSV書き出しを表示", value=False, key="show_journal_export"):
            st.download_button(
                "蓄積データを書き出す",
                table.to_csv(index=False).encode("utf-8-sig"),
                "betting_journal_export.csv",
                "text/csv",
            )
    else:
        st.info("まだ買い目実績はありません。")
    st.markdown("</div>", unsafe_allow_html=True)
