from __future__ import annotations

import json
import os
import html
import hmac
import hashlib
import importlib.util
import platform
import re
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from itertools import combinations, permutations
from pathlib import Path

import pandas as pd
import altair as alt
import streamlit as st

from horse_ai.core import (
    HORSE_COLUMNS, PRESETS, SCORE_KEYS, analyze_race_trends, archive_prediction, available_ollama_models, calculate_scores,
    compare_odds, evaluate_with_ollama,
    extract_screenshot_with_macos_vision, extract_netkeiba_race_table_image_with_tesseract,
    extract_netkeiba_newspaper_pdf, generate_marks, align_marks_to_bets,
    heuristic_evaluations, learn_from_race_result, learn_from_result_history, learn_prediction_adjustments, list_predictions,
    cloud_storage_enabled, cloud_storage_status, data_path, load_cloud_json, load_json, load_prediction_profile, new_state, ocr_popular_odds_image_with_tesseract, ocr_text_with_macos_vision, parse_inputs,
    fetch_netkeiba_popular_odds, merge_web_history, parse_finish_order, parse_odds, parse_popular_odds_snapshot, prediction_policy_prompt, save_json,
    save_cloud_json, propose_bet_plans, parse_netkeiba_popular_odds_image_layout,
)
from horse_ai.exporter import image_bytes, render_summary
from horse_ai.jra_fetcher import fetch_jra_odds, fetch_jra_result
from horse_ai.historical import history_job_status, load_cached_history, start_history_job

IS_MAC = platform.system() == "Darwin"

st.set_page_config(
    page_title="競馬予想AI｜カミノ競馬クラブ",
    page_icon="🏇",
    layout="wide",
    initial_sidebar_state="collapsed",
)

if st.query_params.get("view") == "lab":
    os.environ["KAMINO_EMBED_LAB"] = "1"
    lab_path = Path(__file__).parent / "pages" / "betting_results_lab.py"
    spec = importlib.util.spec_from_file_location("kamino_betting_results_lab", lab_path)
    if spec is None or spec.loader is None:
        st.error("買い目実績ラボを読み込めませんでした。")
        st.stop()
    lab_module = importlib.util.module_from_spec(spec)
    sys.modules["kamino_betting_results_lab"] = lab_module
    spec.loader.exec_module(lab_module)
    st.stop()

st.markdown("""
<style>
  :root {--green:#0878bd;--green-dark:#073d70;--lime:#45a966;--ink:#202a33;--muted:#586774;--line:#cfd6dc;--bg:#edf0f3;--red:#df2735;--blue:#0878bd;--blue-dark:#064f82;--warm:#f4f2ed;--input:#f7fbfe;--input-line:#91aabd;}
  .stApp {background:var(--bg);color:var(--ink);font-size:1rem;line-height:1.6;-webkit-font-smoothing:antialiased;}
  .block-container {max-width:1280px;padding-top:1.15rem;padding-bottom:4rem;}
  [data-testid="stSidebar"] {--text-color:#f5f9fc;background:linear-gradient(180deg,#073d70 0%,#082e53 100%);border-right:3px solid #0d69ad;}
  [data-testid="stSidebar"],[data-testid="stSidebar"] * {color:#f5f9fc!important;opacity:1;}
  [data-testid="stSidebar"] svg {color:#f5f9fc!important;fill:currentColor!important;stroke:currentColor!important;opacity:1!important;visibility:visible!important;}
  [data-testid="stSidebar"] details {background:#f3f7fa!important;border:1px solid #9fb6c8!important;border-left:4px solid #1b82bd!important;border-radius:4px!important;box-shadow:0 2px 7px rgba(0,0,0,.13);}
  [data-testid="stSidebar"] details summary,[data-testid="stSidebar"] details summary * {color:#103d5d!important;font-weight:900!important;opacity:1!important;}
  [data-testid="stSidebar"] details summary::marker,[data-testid="stSidebar"] details summary::-webkit-details-marker {color:#103d5d!important;}
  [data-testid="stSidebar"] details summary svg,[data-testid="stSidebar"] details [data-testid="stExpanderToggleIcon"],[data-testid="stSidebar"] details [data-testid="stExpanderToggleIcon"] * {color:#103d5d!important;fill:#103d5d!important;stroke:#103d5d!important;}
  [data-testid="stSidebar"] details p,[data-testid="stSidebar"] details label,[data-testid="stSidebar"] details span {color:#253946!important;}
  [data-testid="stSidebar"] input,[data-testid="stSidebar"] textarea,[data-testid="stSidebar"] [data-baseweb="select"]>div,[data-testid="stSidebar"] [data-baseweb="select"]>div * {color:#1f2d38!important;background:#fff!important;}
  [data-testid="stSidebar"] [data-baseweb="select"] svg,[data-testid="stSidebar"] [data-baseweb="select"] svg * ,[data-testid="stSidebar"] [data-baseweb="input"] svg,[data-testid="stSidebar"] [data-baseweb="input"] svg * {color:#334653!important;fill:#334653!important;stroke:#334653!important;}
  [data-testid="stSidebar"] .stButton button,
  [data-testid="stSidebar"] .stButton button *,
  [data-testid="stSidebar"] .stDownloadButton button,
  [data-testid="stSidebar"] .stDownloadButton button * {background:#fff!important;color:#073d70!important;border:0;font-weight:800;}
  [data-testid="stSidebarCollapseButton"],[data-testid="stSidebarCollapseButton"] button,[data-testid="stSidebarCollapsedControl"],[data-testid="stSidebarCollapsedControl"] button {background:#fff!important;border:2px solid #0b6ea8!important;border-radius:999px!important;box-shadow:0 2px 8px rgba(0,0,0,.22)!important;opacity:1!important;visibility:visible!important;}
  [data-testid="stSidebarCollapseButton"] *,[data-testid="stSidebarCollapsedControl"] * {color:#064f82!important;fill:#064f82!important;stroke:#064f82!important;opacity:1!important;visibility:visible!important;}
  h1,h2,h3 {color:var(--ink);letter-spacing:-.015em;line-height:1.35;}
  p {line-height:1.65;}
  .brandbar {position:relative;isolation:isolate;overflow:hidden;display:flex;justify-content:space-between;align-items:center;min-height:94px;padding:1.2rem 1.4rem 1.25rem;border-radius:5px 5px 0 0;background:linear-gradient(105deg,#064b80 0%,#0878bd 68%,#0b8acb 100%);color:white;box-shadow:0 4px 14px rgba(7,61,112,.22);border-top:5px solid var(--red);}
  .brandbar:after {content:"";position:absolute;z-index:-1;inset:-30% -2% -40% 56%;opacity:.16;background:repeating-linear-gradient(125deg,transparent 0 22px,#fff 22px 25px);transform:skewX(-8deg);}
  .brandbar:before {content:"";position:absolute;left:0;right:0;bottom:0;height:4px;background:linear-gradient(90deg,#fff 0 12%,transparent 12% 14%,rgba(255,255,255,.55) 14% 36%,transparent 36%);opacity:.72;}
  .brandbar h1 {color:white;margin:0;font-size:1.62rem;line-height:1.35}.brandbar p{margin:.28rem 0 0;color:#eff8fd;font-size:.84rem;font-weight:650;line-height:1.45}
  .brand-badge {border:1px solid rgba(255,255,255,.7);background:var(--red);border-radius:3px;padding:.36rem .65rem;font-size:.7rem;font-weight:900;letter-spacing:.05em;box-shadow:0 1px 3px rgba(0,0,0,.15);}
  .racebar {display:flex;gap:1rem;align-items:center;padding:.78rem 1.15rem;background:white;border:1px solid #bdc8d1;border-top:0;border-radius:0 0 5px 5px;margin-bottom:.85rem;box-shadow:0 2px 7px rgba(25,45,65,.08);}
  .racebar strong{font-size:1.08rem;color:#1e2932}.racebar span{color:#6b7780;font-size:.77rem;font-weight:450}.racebar .race-no{color:white;background:var(--blue);border-radius:3px;padding:.34rem .54rem;font-weight:900;border-bottom:3px solid #04518b;}
  .lab-link {display:flex;align-items:center;justify-content:space-between;gap:.85rem;margin:-.25rem 0 .95rem;padding:.84rem 1rem;border:1px solid #c8d7e6;border-radius:10px;background:linear-gradient(135deg,#f7fbff 0%,#fff 62%);box-shadow:0 3px 10px rgba(25,45,65,.06);}
  .lab-link strong{display:block;color:#12375f;font-size:.98rem}.lab-link span{display:block;color:#65727d;font-size:.78rem;line-height:1.45;margin-top:.12rem}
  .lab-link-button [data-testid="stPageLink"] a{white-space:nowrap;text-decoration:none;background:#0b78bd;color:white!important;border-radius:999px;padding:.48rem .82rem;font-weight:850;font-size:.82rem;box-shadow:0 3px 8px rgba(11,120,189,.22);display:inline-flex;justify-content:center;}
  .page-head {display:flex;gap:1rem;align-items:center;margin:1.35rem 0 .9rem;}
  .step-kicker {display:grid;place-items:center;min-width:44px;height:44px;border-radius:4px;background:var(--blue);color:white;font-weight:900;font-size:1.1rem;box-shadow:inset 0 -3px 0 #04518b}
  .page-head h2 {margin:0;font-size:1.55rem;color:#182630}.page-head p{margin:.16rem 0 0;color:#6b7780;font-size:.81rem;font-weight:450;line-height:1.5}
  .guide {padding:.58rem .78rem;background:#f5f7f8;border:1px solid #d2d8dc;border-left:3px solid #9aa8b2;border-radius:3px;color:#68747d;margin:.22rem 0 .82rem;font-size:.79rem;font-weight:450;line-height:1.55;}
  .section-label {margin:1.2rem 0 .58rem;padding:.55rem .72rem;font-weight:900;font-size:1rem;color:#28343d;display:flex;align-items:center;gap:.5rem;background:linear-gradient(90deg,#e7e9eb 0%,#f8f9fa 72%);border-top:1px solid #cdd2d6;border-bottom:1px solid #cdd2d6;border-left:6px solid var(--red);}
  .section-label:before {display:none;}
  div[data-testid="stMetric"] {background:white;border:1px solid #d8dce0;border-top:3px solid var(--blue);padding:.72rem .85rem;border-radius:3px;box-shadow:0 1px 4px rgba(25,45,65,.06);}
  div[data-testid="stMetric"] label {color:#4e5e6b!important;font-weight:800!important;}
  div[data-testid="stMetric"] [data-testid="stMetricValue"] {color:#102f48;font-weight:900;}
  [data-testid="stDataFrame"], [data-testid="stDataEditor"] {border:1px solid #d3d7db;border-radius:3px;overflow:hidden;background:white;box-shadow:0 1px 3px rgba(0,0,0,.04);}
  div[role="radiogroup"] {gap:.25rem;background:white;border:1px solid var(--line);padding:.3rem;border-radius:4px;box-shadow:0 1px 4px rgba(25,45,65,.05);}
  div[role="radiogroup"] label {padding:.48rem .72rem;border-radius:8px;}
  div[role="radiogroup"] label:has(input:checked) {background:#e6f2f9;color:var(--blue-dark);font-weight:900;}
  .stButton>button[kind="primary"] {background:linear-gradient(#0b83c7,#0668aa);border-color:#075c99;font-weight:900;border-radius:3px;box-shadow:inset 0 1px 0 rgba(255,255,255,.25);}
  .stButton>button[kind="primary"]:hover {background:linear-gradient(#0877b7,#04578f);border-color:#044b7d;}
  .stTabs [data-baseweb="tab-list"] {gap:1px;background:#dcdfe2;padding:1px;border-radius:3px 3px 0 0;border-bottom:3px solid var(--blue);}
  .stTabs [data-baseweb="tab"] {border-radius:0;padding:.48rem .85rem;background:#f0f1f2;}
  .stTabs [aria-selected="true"] {background:white;color:var(--blue-dark);font-weight:900;box-shadow:none;}
  [data-testid="stVerticalBlockBorderWrapper"]{background:#fff;border-color:#c7cfd6!important;border-radius:4px!important;box-shadow:0 2px 7px rgba(25,45,65,.07);}
  [data-testid="stExpander"]{background:#fff;border-color:#d7dadd!important;border-radius:3px!important;}
  .stButton>button:not([kind="primary"]),.stDownloadButton>button{border-radius:3px;border-color:#bfc6cc;background:linear-gradient(#fff,#f2f3f4);color:#34414c;font-weight:750;}
  /* 入力可能な領域を、閲覧情報とは異なる淡い青と濃い輪郭で統一する。 */
  [data-testid="stTextInput"] label p,[data-testid="stTextArea"] label p,[data-testid="stNumberInput"] label p,[data-testid="stSelectbox"] label p,[data-testid="stTimeInput"] label p,[data-testid="stFileUploader"] label p,[data-testid="stSlider"] label p {color:#263746!important;font-size:.9rem!important;font-weight:850!important;letter-spacing:.01em;}
  [data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea,[data-testid="stNumberInput"] input,[data-testid="stTimeInput"] input,[data-baseweb="select"]>div {background:var(--input)!important;color:#172832!important;border-color:var(--input-line)!important;box-shadow:inset 3px 0 0 rgba(8,120,189,.22);}
  [data-testid="stTextInput"] input:focus,[data-testid="stTextArea"] textarea:focus,[data-testid="stNumberInput"] input:focus,[data-testid="stTimeInput"] input:focus {background:#fff!important;box-shadow:inset 4px 0 0 var(--blue),0 0 0 1px var(--blue)!important;}
  [data-baseweb="select"]>div:focus-within {background:#fff!important;box-shadow:inset 4px 0 0 var(--blue),0 0 0 1px var(--blue)!important;}
  input::placeholder,textarea::placeholder {color:#778894!important;opacity:1!important;}
  input:disabled,textarea:disabled {background:#e9edf0!important;color:#65727c!important;box-shadow:none!important;}
  [data-testid="stFileUploader"] section {background:#f5fafc;border:2px dashed #79a9c5;border-radius:5px;}
  [data-testid="stFileUploader"] section:hover {background:#edf7fc;border-color:var(--blue);}
  [data-testid="stFileUploaderDropzoneInstructions"] span {color:#304b5e!important;font-weight:800;}
  [data-testid="stCheckbox"] p,[data-testid="stToggle"] p,[data-testid="stRadio"]>label p {color:#2b3944;font-weight:750;}
  [data-testid="stCaptionContainer"] {color:#52636f!important;font-size:.82rem;}
  [data-testid="stAlert"] {border-width:1px 1px 1px 5px;border-radius:3px;}
  .st-key-workflow_nav div[role="radiogroup"]{background:linear-gradient(#0878bd,#075596);border:0;border-radius:3px;padding:2px;gap:1px;box-shadow:0 2px 5px rgba(7,61,112,.2);}
  .st-key-workflow_nav div[role="radiogroup"] label{color:#fff!important;padding:.46rem .68rem;border-radius:2px;}
  .st-key-workflow_nav div[role="radiogroup"] label p,.st-key-workflow_nav div[role="radiogroup"] label span{color:#fff!important;font-weight:850!important;text-shadow:0 1px 1px rgba(0,0,0,.2);}
  .st-key-workflow_nav div[role="radiogroup"] label:has(input:checked){background:white;color:#064f82!important;box-shadow:inset 0 4px 0 var(--red);}
  .st-key-workflow_nav div[role="radiogroup"] label:has(input:checked) p,.st-key-workflow_nav div[role="radiogroup"] label:has(input:checked) span{color:#064f82!important;text-shadow:none;}
  .maker {margin-top:2.5rem;padding-top:1rem;border-top:1px solid var(--line);text-align:center;color:var(--muted);font-size:.78rem;letter-spacing:.04em;}
  .rank-grid {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.75rem;margin:.35rem 0 1rem;}
  .rank-card {position:relative;overflow:hidden;background:white;border:1px solid #d2d7dc;border-radius:4px;padding:.85rem .9rem .75rem;box-shadow:0 2px 7px rgba(25,45,65,.08);}
  .rank-card:after {content:"";position:absolute;inset:0 auto 0 0;width:5px;background:var(--frame-color,#0878bd);}
  .rank-card .rank-meta {display:flex;align-items:center;gap:.5rem;color:var(--muted);font-size:.75rem;font-weight:800;}
  .rank-card .rank-mark {font-size:1.45rem;color:var(--red);line-height:1;}
  .rank-card .horse-name {font-size:1.05rem;font-weight:900;margin:.55rem 0 .2rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .rank-card .race-index {font-size:1.7rem;font-weight:900;color:var(--blue-dark);letter-spacing:-.04em;}
  .rank-card .race-index small {font-size:.68rem;color:var(--muted);letter-spacing:0;margin-left:.25rem;}
  .chart-shell {background:white;border:1px solid var(--line);border-radius:4px;padding:.65rem .8rem .35rem;box-shadow:0 2px 7px rgba(25,45,65,.05);}
  .ability-card {--ability-blue:#087bb6;--ability-cyan:#dff7ff;overflow:hidden;border:3px solid #b7d9e9;border-radius:18px;background:linear-gradient(145deg,#f9fdff 0%,#e8f8ff 55%,#d8f2fb 100%);box-shadow:0 12px 30px rgba(30,105,140,.14),inset 0 1px 0 white;margin:.4rem 0 1rem;}
  .ability-head {display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:.75rem;padding:.8rem 1rem;background:linear-gradient(180deg,#fff5a6,#ffd42d 65%,#efad00);border-bottom:3px solid #dda000;color:#14384b;}
  .ability-head .gate {width:38px;height:38px;display:grid;place-items:center;border-radius:9px;background:var(--gate,#fff);color:var(--gate-text,#17211d);border:2px solid rgba(0,0,0,.16);font-weight:900;font-size:1.05rem;}
  .ability-head .ability-name {font-size:1.35rem;font-weight:950;letter-spacing:.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
  .ability-head .ability-index {font-size:1.65rem;font-weight:950;color:#00679d;text-align:right;line-height:1;}.ability-head .ability-index small{display:block;font-size:.62rem;color:#547586;margin-top:.2rem;letter-spacing:.04em;}
  .ability-body {display:grid;grid-template-columns:minmax(270px,.85fr) minmax(360px,1.4fr);gap:.75rem;padding:.8rem;}
  .ability-panel {border:2px solid #b9deec;border-radius:12px;background:rgba(255,255,255,.72);padding:.55rem;box-shadow:inset 0 1px 8px rgba(26,132,177,.05);}
  .ability-row {display:grid;grid-template-columns:1fr 42px 52px;align-items:center;gap:.4rem;min-height:37px;padding:.24rem .45rem;border-bottom:1px solid #cce7f1;color:#076a9c;font-weight:850;}.ability-row:last-child{border-bottom:0}
  .ability-grade {width:34px;height:30px;display:grid;place-items:center;border-radius:8px;color:white;font-size:1.15rem;font-weight:950;text-shadow:0 1px 2px rgba(0,0,0,.2);box-shadow:inset 0 -2px 0 rgba(0,0,0,.12)}
  .grade-S{background:#e74f91}.grade-A{background:#26a9e0}.grade-B{background:#46ac65}.grade-C{background:#e4af18}.grade-D{background:#d28735}.grade-E{background:#8796a3}.grade-F{background:#68757f}
  .ability-value {text-align:right;font-size:1.15rem;color:#075f91;font-weight:950;font-variant-numeric:tabular-nums;}
  .ability-subhead {display:flex;justify-content:space-between;align-items:center;color:#0a6f9f;font-weight:900;padding:.25rem .35rem .55rem;border-bottom:2px solid #a8ddea;margin-bottom:.55rem;}
  .trait-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.45rem;}
  .trait {min-height:36px;display:flex;align-items:center;justify-content:center;text-align:center;border:2px solid #59c6e8;border-radius:9px;background:linear-gradient(180deg,#e8fbff,#c7f1fb);color:#08729e;font-weight:850;padding:.3rem .45rem;}
  .trait.good {border-color:#25b8d9;background:linear-gradient(180deg,#d9fbff,#a7ecf7);color:#006c8f}.trait.caution{border-color:#ef8c8c;background:linear-gradient(180deg,#fff1f1,#ffd5d5);color:#b92727}.trait.neutral{color:#7192a1;border-color:#bedbe5;background:#edf7fa}
  .ability-note {margin-top:.55rem;padding:.6rem .7rem;border-radius:9px;background:#fff;color:#416675;font-size:.8rem;line-height:1.55;border:1px solid #c9e2ea;}
  @media(max-width:980px){
    .block-container{padding-left:1rem;padding-right:1rem;}
    .rank-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
    .ability-body{grid-template-columns:1fr;}
  }
  @media(max-width:760px){
    html,body,.stApp{max-width:100vw;overflow-x:hidden;}
    .block-container{padding:.55rem .65rem 5rem;max-width:100%;}
    [data-testid="stSidebar"][aria-expanded="false"]{width:0!important;min-width:0!important;max-width:0!important;transform:translateX(-100%)!important;border-right:0!important;overflow:hidden!important;}
    [data-testid="stSidebar"][aria-expanded="false"]>div{width:0!important;min-width:0!important;max-width:0!important;padding:0!important;overflow:hidden!important;}
    [data-testid="stSidebar"][aria-expanded="true"]{width:min(88vw,360px)!important;min-width:min(88vw,360px)!important;max-width:min(88vw,360px)!important;box-shadow:8px 0 24px rgba(0,0,0,.22)!important;}
    [data-testid="stSidebar"]:not([aria-expanded="false"]){width:min(88vw,360px)!important;min-width:min(88vw,360px)!important;max-width:min(88vw,360px)!important;}
    [data-testid="stSidebar"]>div{width:100%!important;}
    [data-testid="stAppViewContainer"],[data-testid="stMain"],section.main{margin-left:0!important;max-width:100vw!important;}
    [data-testid="stSidebar"] details summary{min-height:48px;display:flex;align-items:center;}
    [data-testid="collapsedControl"],[data-testid="stSidebarCollapsedControl"]{left:.55rem!important;top:.55rem!important;z-index:999999!important;}
    [data-testid="stSidebarCollapseButton"],[data-testid="stSidebarCollapseButton"] button,[data-testid="stSidebarCollapsedControl"],[data-testid="stSidebarCollapsedControl"] button{min-width:42px!important;min-height:42px!important;}
    .brandbar{align-items:center;min-height:86px;padding:1.05rem 1rem 1.1rem;border-radius:7px 7px 0 0;}
    .brandbar h1{font-size:1.34rem;line-height:1.35}.brandbar p{font-size:.75rem;line-height:1.45}.brand-badge{display:none}
    .racebar{flex-wrap:wrap;gap:.45rem .7rem;padding:.72rem .9rem;border-radius:0 0 11px 11px;margin-bottom:.7rem;}
    .racebar strong{font-size:.98rem;max-width:calc(100% - 52px);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.racebar span{width:100%;font-size:.73rem}
    .racebar .race-no{padding:.3rem .48rem;font-size:.88rem}
    .lab-link{align-items:flex-start;flex-direction:column;margin:-.15rem 0 .8rem;padding:.78rem .86rem}.lab-link-button [data-testid="stPageLink"] a{width:100%;text-align:center}
    .page-head{gap:.65rem;margin:1rem 0 .7rem;align-items:flex-start}.step-kicker{min-width:38px;height:38px;border-radius:10px;font-size:1rem}
    .page-head h2{font-size:1.22rem;line-height:1.35}.page-head p{font-size:.75rem;line-height:1.5}
    .guide{padding:.56rem .72rem;font-size:.74rem;line-height:1.55;margin-bottom:.72rem}.section-label{margin:1rem 0 .5rem;font-size:.94rem}
    div[role="radiogroup"]{display:flex;flex-wrap:nowrap!important;overflow-x:auto;overflow-y:hidden;scroll-snap-type:x proximity;-webkit-overflow-scrolling:touch;gap:.2rem;padding:.28rem;}
    div[role="radiogroup"]::-webkit-scrollbar{display:none}div[role="radiogroup"] label{flex:0 0 auto;min-width:max-content;padding:.43rem .58rem!important;scroll-snap-align:start;font-size:.78rem;}
    .st-key-workflow_nav div[role="radiogroup"]{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));overflow:visible;gap:2px;padding:3px;}
    .st-key-workflow_nav div[role="radiogroup"] label{min-width:0!important;width:100%;min-height:42px;justify-content:center;padding:.42rem .25rem!important;text-align:center;}
    .st-key-workflow_nav div[role="radiogroup"] label p,.st-key-workflow_nav div[role="radiogroup"] label span{font-size:.74rem!important;white-space:nowrap;}
    [data-testid="stHorizontalBlock"]{flex-wrap:wrap!important;gap:.55rem!important;}
    [data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{flex:1 1 260px!important;width:100%!important;min-width:0!important;}
    div[data-testid="stMetric"]{padding:.68rem .78rem;border-radius:5px}div[data-testid="stMetric"] [data-testid="stMetricValue"]{font-size:1.25rem}
    .rank-grid{grid-template-columns:1fr}.rank-card{padding:.78rem .9rem}.rank-card .race-index{font-size:1.45rem}
    .ability-body{grid-template-columns:1fr;padding:.55rem}.trait-grid{grid-template-columns:1fr}.ability-head{grid-template-columns:auto minmax(0,1fr) auto;padding:.65rem .7rem}.ability-head .ability-name{font-size:1rem}.ability-head .ability-index{font-size:1.3rem}
    [data-testid="stDataFrame"],[data-testid="stDataEditor"]{max-width:100%;overflow-x:auto;border-radius:9px;}
    .stTabs [data-baseweb="tab-list"]{overflow-x:auto;flex-wrap:nowrap}.stTabs [data-baseweb="tab"]{white-space:nowrap;padding:.48rem .7rem;font-size:.82rem}
    .stButton>button,.stDownloadButton>button{min-height:44px;width:100%;font-size:.9rem}
    input,textarea,select{font-size:16px!important}input,[data-baseweb="select"]>div{min-height:44px}textarea{min-height:110px}
    [data-testid="stFileUploader"]{padding:.1rem}[data-testid="stFileUploader"] section{padding:.75rem!important}[data-testid="stImage"] img{max-width:100%;height:auto}
    [data-testid="stPlotlyChart"],[data-testid="stVegaLiteChart"]{max-width:100%;overflow-x:auto;}
    details{border-radius:9px!important}.maker{margin-top:1.5rem;padding-bottom:1rem;font-size:.7rem}
  }
</style>
""", unsafe_allow_html=True)


def init():
    if "draft_id" not in st.session_state:
        draft_from_url = _safe_draft_id(st.query_params.get("draft", ""))
        st.session_state.draft_id = draft_from_url or uuid.uuid4().hex[:12]
        if st.query_params.get("draft") != st.session_state.draft_id:
            st.query_params["draft"] = st.session_state.draft_id
    if "race" not in st.session_state:
        restored = load_draft(st.session_state.draft_id)
        st.session_state.race = restored or new_state()
        st.session_state.draft_restored = bool(restored)
    st.session_state.race.setdefault("bet_plans", {})
    st.session_state.race.setdefault("selected_bet_plan", "AIおすすめ")
    st.session_state.race.setdefault("trend_analysis", {})
    st.session_state.race.setdefault("web_history", {})
    # 旧9項目データを読み込んでも、血統評価を画面へ復活させず8項目へ移行する。
    for score_group in ("ai_scores", "final_scores"):
        for scores in st.session_state.race.setdefault(score_group, {}).values():
            scores.pop("血統評価", None)
            for key in SCORE_KEYS: scores.setdefault(key, 3)
    weights = st.session_state.race.setdefault("weights", {})
    weights.pop("血統評価", None)
    for key in SCORE_KEYS: weights.setdefault(key, 1.0)
    if "step" not in st.session_state: st.session_state.step = 1
    if "budget" not in st.session_state: st.session_state.budget = 5000
    if "unit" not in st.session_state: st.session_state.unit = 100
    if "min_odds" not in st.session_state: st.session_state.min_odds = 1.5
    if "prediction_policy" not in st.session_state:
        st.session_state.prediction_policy = load_prediction_profile().get("policy", "")


DRAFT_ROOT = data_path("data/drafts")


def _safe_draft_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", str(value or ""))[:64]


def draft_path(draft_id: str) -> Path:
    return DRAFT_ROOT / f"{_safe_draft_id(draft_id)}.json"


def load_draft(draft_id: str) -> dict | None:
    if not draft_id:
        return None
    cloud_payload = load_cloud_json("drafts", _safe_draft_id(draft_id))
    if isinstance(cloud_payload, dict) and isinstance(cloud_payload.get("race"), dict):
        st.session_state.draft_saved_at = cloud_payload.get("saved_at", cloud_payload.get("updated_at", ""))
        st.session_state.draft_storage = "Supabase"
        return cloud_payload["race"]
    path = draft_path(draft_id)
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("race"), dict):
                st.session_state.draft_saved_at = payload.get("saved_at", "")
                st.session_state.draft_storage = "ローカル"
                return payload["race"]
    except (OSError, json.JSONDecodeError):
        return None
    return None


def save_draft(state: dict) -> Path | None:
    draft_id = _safe_draft_id(st.session_state.get("draft_id", ""))
    if not draft_id:
        return None
    try:
        DRAFT_ROOT.mkdir(parents=True, exist_ok=True)
        now = datetime.now().isoformat(timespec="seconds")
        payload = {"draft_id": draft_id, "saved_at": now, "race": state}
        cloud_saved = save_cloud_json("drafts", draft_id, payload)
        path = draft_path(draft_id)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.replace(temp, path)
        st.session_state.draft_saved_at = now
        st.session_state.draft_storage = "Supabase + ローカル" if cloud_saved else "ローカル"
        return path
    except Exception as exc:
        st.session_state.draft_save_error = str(exc)
        return None


def require_shared_access():
    """Optional lightweight gate for a club-only shared deployment."""
    configured = os.getenv("APP_ACCESS_PASSWORD", "")
    try:
        configured = configured or st.secrets.get("APP_ACCESS_PASSWORD", "")
    except Exception:
        pass
    if not configured or st.session_state.get("shared_access_granted"):
        return
    st.markdown("## 🏇 競馬予想AI")
    st.caption("カミノ競馬クラブ制作")
    entered = st.text_input("共有用パスワード", type="password")
    if st.button("ツールを開く", type="primary"):
        if hmac.compare_digest(entered, configured):
            st.session_state.shared_access_granted = True
            st.rerun()
        else:
            st.error("パスワードが違います。")
    st.stop()


def persist(message="保存しました"):
    try:
        path = save_json(st.session_state.race)
        st.toast(f"{message}: {path.name}")
    except Exception as exc:
        st.warning(f"自動保存に失敗しました。セッション内データは保持されています: {exc}")


def horse_df():
    return pd.DataFrame(st.session_state.race["horses"], columns=HORSE_COLUMNS)


def page_head(number: int, title: str, description: str):
    st.markdown(
        f'<div class="page-head"><div class="step-kicker">{number}</div>'
        f'<div><h2>{title}</h2><p>{description}</p></div></div>',
        unsafe_allow_html=True,
    )


def section_label(label: str):
    st.markdown(f'<div class="section-label">{label}</div>', unsafe_allow_html=True)


def progress_step(progress, percent: int, message: str):
    progress.progress(max(0, min(100, percent)), text=f"{message}（{percent}%）")


def _lap_format(value) -> str:
    return f"{value}秒" if value not in ("", None) else "－"


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(str(value or "").replace(",", "").replace("円", "").strip()))
    except (TypeError, ValueError):
        return default


def option_index(options: list, value) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


def horse_option_label(horse: dict) -> str:
    no = str(horse.get("馬番", "")).strip()
    name = str(horse.get("馬名", "")).strip()
    return f"{no} {name}".strip() if no or name else ""


def horse_no_from_option(value: str) -> str:
    match = re.match(r"\s*(\d{1,2})", str(value or ""))
    return match.group(1) if match else ""


def _bet_lookup_key(ticket: str, combo: tuple[str, ...]) -> str:
    unordered = {"枠連", "馬連", "ワイド", "3連複"}
    values = [str(int(float(x))) if re.fullmatch(r"\d+(?:\.0+)?", str(x)) else str(x) for x in combo]
    if ticket in unordered:
        values = sorted(values, key=lambda x: int(x) if x.isdigit() else x)
    return f"{ticket} {'-'.join(values)}"


def expand_manual_formation_combos(ticket: str, group1: list[str], group2: list[str], group3: list[str]) -> list[tuple[str, ...]]:
    first = list(dict.fromkeys(x for x in group1 if x))
    second = list(dict.fromkeys(x for x in group2 if x))
    third = list(dict.fromkeys(x for x in group3 if x))
    if ticket in {"単勝", "複勝"}:
        return [(number,) for number in first]
    if ticket in {"枠連", "ワイド", "馬連"}:
        combos = [tuple(sorted((a, b), key=int)) for a in first for b in second if a != b]
        return list(dict.fromkeys(combos))
    if ticket == "馬単":
        combos = [(a, b) for a in first for b in second if a != b]
        return list(dict.fromkeys(combos))
    if ticket == "3連複":
        combos = [
            tuple(sorted((a, b, c), key=int))
            for a in first for b in second for c in third
            if len({a, b, c}) == 3
        ]
        return list(dict.fromkeys(combos))
    if ticket == "3連単":
        combos = [
            (a, b, c)
            for a in first for b in second for c in third
            if len({a, b, c}) == 3
        ]
        return list(dict.fromkeys(combos))
    return []


def _manual_row_list(row: dict, key: str) -> list:
    value = row.get(key, [])
    return value if isinstance(value, list) else []


def expand_manual_bet_combos(ticket: str, method: str, axis1: str, axis2: str, opponents: list[str]) -> list[tuple[str, ...]]:
    axis = [x for x in [axis1, axis2] if x]
    opponents = [x for x in opponents if x and x not in axis]
    selected = list(dict.fromkeys(axis + opponents))
    if ticket in {"単勝", "複勝"}:
        return [(n,) for n in selected]
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


def _manual_estimated_odds(ticket: str, combo: tuple[str, ...], score_rows: list[dict], frame_to_no: dict[str, str]) -> float:
    by_no = {str(row.get("馬番", "")): row for row in score_rows}
    numbers = [frame_to_no.get(n, n) for n in combo] if ticket == "枠連" else list(combo)
    singles = []
    for no in numbers:
        row = by_no.get(str(no), {})
        try:
            single_odd = float(str(row.get("単勝オッズ") or 8.0).replace(",", ""))
        except (TypeError, ValueError):
            single_odd = 8.0
        singles.append(max(1.1, single_odd))
    powers = {"単勝": 1.0, "複勝": .42, "枠連": .48, "馬連": .58, "ワイド": .40, "馬単": .72, "3連複": .72, "3連単": .96}
    discounts = {"単勝": 1.0, "複勝": .72, "枠連": .82, "馬連": .90, "ワイド": .70, "馬単": 1.05, "3連複": 1.15, "3連単": 1.35}
    product = 1.0
    for odd in singles:
        product *= odd
    return max(1.1, product ** powers.get(ticket, .5) * discounts.get(ticket, 1.0))


def manual_bets_from_rows(rows: list[dict], race_state: dict, odds_map: dict[str, float], min_odds: float, allow_torigami: bool = True) -> tuple[list[dict], list[dict], int]:
    output: list[dict] = []
    skipped: list[dict] = []
    total = 0
    frame_by_no = {str(h.get("馬番", "")): str(h.get("枠番") or h.get("馬番", "")) for h in race_state.get("horses", [])}
    frame_to_no = {}
    for no, frame in frame_by_no.items():
        frame_to_no.setdefault(frame, no)
    for row in rows:
        ticket = str(row.get("券種", "") or "").strip()
        stake = _to_int(row.get("1点金額", 0))
        method = str(row.get("買い方", "通常") or "通常")
        if not ticket or stake <= 0:
            continue
        axis1 = horse_no_from_option(row.get("軸1", ""))
        axis2 = horse_no_from_option(row.get("軸2", ""))
        opponent_values = _manual_row_list(row, "相手候補") or _manual_row_list(row, "相手")
        opponent_values += [row.get(key, "") for key in [f"相手{i}" for i in range(1, 11)]]
        opponents = [horse_no_from_option(value) for value in opponent_values]
        if method == "フォーメーション":
            combos = expand_manual_formation_combos(
                ticket,
                [horse_no_from_option(v) for v in _manual_row_list(row, "1列目") if v],
                [horse_no_from_option(v) for v in _manual_row_list(row, "2列目") if v],
                [horse_no_from_option(v) for v in _manual_row_list(row, "3列目") if v],
            )
        else:
            combos = expand_manual_bet_combos(ticket, method, axis1, axis2, opponents)
        if ticket == "枠連":
            combos = [tuple(frame_by_no.get(n, n) for n in combo) for combo in combos]
        combos = list(dict.fromkeys(combos))
        for combo in combos:
            key = _bet_lookup_key(ticket, combo)
            has_live = key in odds_map
            odds = float(odds_map.get(key, _manual_estimated_odds(ticket, combo, race_state.get("score_results", []), frame_to_no)))
            item = {
                "買い目": key, "券種": ticket, "買い目スコア": 0,
                "現在オッズ": round(odds, 2), "オッズ区分": "取得値" if has_live else "推定値",
                "的中期待度": 0, "回収期待指数": 0,
                "推奨購入金額": stake, "想定払戻": int(stake * odds), "想定利益": int(stake * odds) - stake,
                "狙い": f"手動調整: {ticket} {method}", "見送り理由": "",
            }
            if odds < min_odds:
                skipped.append({**item, "見送り理由": f"最低買いオッズ{min_odds:.1f}未満"})
            else:
                output.append(item)
                total += stake
    if not allow_torigami and output:
        portfolio_total = sum(int(item.get("推奨購入金額", 0)) for item in output)
        kept = []
        for item in output:
            if int(item.get("想定払戻", 0)) < portfolio_total:
                skipped.append({**item, "見送り理由": f"トリガミ回避: 的中時の想定払戻{int(item.get('想定払戻', 0)):,}円が購入総額{portfolio_total:,}円を下回る"})
            else:
                kept.append(item)
        output = kept
        total = sum(int(item.get("推奨購入金額", 0)) for item in output)
    return output, skipped, total


def bet_to_manual_row(bet: dict, horses: list[dict]) -> dict:
    labels = {str(h.get("馬番", "")): horse_option_label(h) for h in horses}
    ticket = str(bet.get("券種", "") or "")
    raw = str(bet.get("買い目", "") or "").replace(ticket, "").strip()
    nums = re.findall(r"\d{1,2}", raw)
    values = [labels.get(n, n) for n in nums]
    return {
        "券種": ticket,
        "買い方": "通常",
        "軸1": values[0] if len(values) > 0 else "",
        "軸2": values[1] if len(values) > 2 else "",
        "相手候補": values[1:] if len(values) > 1 else [],
        "相手1": values[1] if len(values) == 2 else values[2] if len(values) > 2 else "",
        "相手2": "",
        "相手3": "",
        "相手4": "",
        "相手5": "",
        "1点金額": _to_int(bet.get("推奨購入金額", 0)),
    }


def _race_datetime(offset_minutes: int = 0) -> datetime:
    info = st.session_state.race.get("race_info", {})
    raw_date = str(info.get("日付", "")).replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")
    raw_time = str(info.get("発走時刻", ""))
    try:
        return datetime.strptime(f"{raw_date} {raw_time}", "%Y-%m-%d %H:%M") + timedelta(minutes=offset_minutes)
    except ValueError:
        return datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=offset_minutes)


def run_jra_fetch_job(current_race: dict, job: dict) -> None:
    """Run a single JRA odds/result fetch and mutate race state with logs."""
    job["status"] = "fetching"
    try:
        if job["kind"] == "odds":
            snapshot = fetch_jra_odds(current_race["race_info"])
            previous = current_race["odds_history"][-1].get("odds", {}) if current_race.get("odds_history") else {}
            comparisons, alerts = compare_odds(previous, snapshot["odds"], float(st.session_state.min_odds))
            current_race.setdefault("odds_history", []).append({**snapshot, "comparisons": comparisons})
            current_race["alerts"] = alerts
            for horse in current_race.get("horses", []):
                key = f'単勝 {horse.get("馬番")}'
                if key in snapshot["odds"]:
                    horse["単勝オッズ"] = snapshot["odds"][key]
            if current_race.get("final_scores"):
                current_race["score_results"] = calculate_scores(current_race["horses"], current_race["final_scores"], current_race["weights"])
            if current_race.get("score_results"):
                current_race["bet_plans"] = propose_bet_plans(
                    current_race["score_results"],
                    current_race.get("marks", {}),
                    int(st.session_state.budget),
                    int(st.session_state.unit),
                    float(st.session_state.min_odds),
                    snapshot["odds"],
                    load_prediction_profile(),
                    allow_torigami=bool(current_race.get("allow_torigami", True)),
                )
                selected_name = current_race.get("selected_bet_plan")
                if selected_name not in current_race["bet_plans"]:
                    selected_name = next((name for name, plan in current_race["bet_plans"].items() if plan.get("recommended")), next(iter(current_race["bet_plans"]), ""))
                selected_plan = current_race["bet_plans"].get(selected_name, {})
                current_race["selected_bet_plan"] = selected_name
                current_race["bets"], current_race["skipped_bets"] = selected_plan.get("bets", []), selected_plan.get("skipped", [])
                current_race["marks"] = align_marks_to_bets(current_race["score_results"], current_race["bets"], current_race.get("marks", {}))
            job["message"] = f'{len(snapshot["取得券種"])}券種を取得 / 単複オッズ{len(snapshot["odds"])}件を反映'
        else:
            result = fetch_jra_result(current_race["race_info"])
            feedback = {
                **current_race.get("result_feedback", {}),
                "確定着順": result["確定着順"],
                "登録日時": result["取得時刻"],
                "取得元": result["取得元"],
            }
            current_race["result_feedback"] = feedback
            if current_race.get("score_results"):
                learn_from_race_result(current_race, feedback)
            job["message"] = f'{len(result["着順馬番"])}頭の結果を取得'
        job["status"] = "completed"
        job["completed_at"] = datetime.now().isoformat(timespec="seconds")
    except Exception as exc:
        job["status"] = "error"
        job["message"] = str(exc)[:240]
    current_race.setdefault("jra_auto_fetch_log", []).append({**job})


@st.fragment(run_every=15)
def jra_schedule_runner():
    current_race = st.session_state.race
    schedules = current_race.get("jra_fetch_schedule", [])
    now = datetime.now()
    due = [item for item in schedules if item.get("status") == "pending" and datetime.fromisoformat(item["scheduled_at"]) <= now]
    if due:
        job = sorted(due, key=lambda item: item["scheduled_at"])[0]
        save_json(current_race)
        run_jra_fetch_job(current_race, job)
        save_json(current_race)
    pending = [item for item in schedules if item.get("status") == "pending"]
    if pending:
        next_job = min(pending, key=lambda item: item["scheduled_at"])
        st.info(f'次回のJRA自動取得: {next_job["scheduled_at"].replace("T"," ")}（{"オッズ" if next_job["kind"]=="odds" else "結果"}）')


@st.fragment(run_every=5)
def history_job_monitor():
    current_race = st.session_state.race
    status = history_job_status(current_race.get("race_info", {}))
    if not status: return
    if status.get("状態") == "取得中":
        st.info(f'Web傾向をバックグラウンド取得中です。画面はそのまま利用できます。開始：{status.get("開始日時", "-")}')
    elif status.get("状態") == "完了":
        completion = status.get("完了日時", "")
        if st.session_state.get("history_completion_seen") != completion:
            cached = load_cached_history(current_race.get("race_info", {}))
            if cached:
                current_race["web_history"] = cached; save_json(current_race)
            st.session_state.history_completion_seen = completion
            st.rerun()
        st.success(f'Web傾向の取得が完了しました。{status.get("メッセージ", "")}')
    else:
        st.warning(f'Web傾向の取得を完了できませんでした：{status.get("メッセージ", "原因不明")}')


def ability_card(row: dict, horse: dict, scores: dict, mark: str) -> str:
    frame_colors = {1:("#f4f4f4","#17211d"),2:("#242424","#fff"),3:("#e33b3b","#fff"),4:("#356bd8","#fff"),5:("#f1cb35","#17211d"),6:("#3ca45c","#fff"),7:("#ef8b2c","#17211d"),8:("#e987ad","#17211d")}
    frame = int(horse.get("枠番") or 1); gate, gate_text = frame_colors.get(frame, frame_colors[1])
    short_labels = {"近走評価":"近走力","距離・コース適性":"コース","馬場適性":"馬場適性","展開利":"展開力","本命適性":"軸信頼","妙味":"妙味","騎手評価":"騎手力","厩舎・ローテ評価":"仕上がり"}
    grade_map = {5:("S",90),4:("A",80),3:("C",60),2:("E",40),1:("F",25)}
    rows_html, good, caution = [], [], []
    for key in SCORE_KEYS:
        score = max(1,min(5,int(scores.get(key,3)))); grade, value = grade_map[score]
        rows_html.append(f'<div class="ability-row"><span>{short_labels[key]}</span><span class="ability-grade grade-{grade}">{grade}</span><span class="ability-value">{value}</span></div>')
        if score >= 4: good.append(short_labels[key] + "◎")
        elif score <= 2: caution.append(short_labels[key] + "注意")
    traits = [f'<div class="trait good">{html.escape(v)}</div>' for v in good[:4]] + [f'<div class="trait caution">{html.escape(v)}</div>' for v in caution[:3]]
    while len(traits) < 6: traits.append('<div class="trait neutral">分析中</div>')
    note = f'{horse.get("脚質","脚質未定")} / {horse.get("父","")} 産駒。血統はコース・馬場適性へ反映した8項目の参考表示です。'
    return (
        f'<div class="ability-card"><div class="ability-head">'
        f'<div class="gate" style="--gate:{gate};--gate-text:{gate_text}">{frame}</div>'
        f'<div class="ability-name">{html.escape(mark)} {horse.get("馬番","")} {html.escape(str(horse.get("馬名","")))}</div>'
        f'<div class="ability-index">{row.get("レース内指数",50)}<small>レース指数</small></div></div>'
        f'<div class="ability-body"><div class="ability-panel">{"".join(rows_html)}</div>'
        f'<div class="ability-panel"><div class="ability-subhead"><span>特徴</span><span>{html.escape(str(horse.get("性齢","")))} / {html.escape(str(horse.get("騎手","")))}</span></div>'
        f'<div class="trait-grid">{"".join(traits[:6])}</div><div class="ability-note">{html.escape(note)}</div></div></div></div>'
    )


require_shared_access(); init(); race = st.session_state.race

with st.sidebar:
    st.markdown("## 🏇 競馬予想AI")
    st.caption("カミノ競馬クラブ制作")
    st.divider()
    st.markdown("**レース操作**")
    if st.button("＋ 新しいレース", width="stretch"):
        st.session_state.draft_id = uuid.uuid4().hex[:12]
        st.query_params["draft"] = st.session_state.draft_id
        st.session_state.race = new_state()
        st.session_state.draft_restored = False
        st.rerun()
    st.link_button("買い目実績ラボを開く", "/?view=lab", icon="📝", width="stretch")
    with st.expander("データの保存・復元", expanded=False):
        if st.session_state.get("draft_restored"):
            st.success("前回の一時保存データを復元しました。", icon=":material/restore:")
        saved_at = st.session_state.get("draft_saved_at", "")
        if saved_at:
            st.caption(f"自動一時保存: {saved_at}")
        else:
            st.caption("自動一時保存: 有効")
        storage_label = st.session_state.get("draft_storage") or ("Supabase待機" if cloud_storage_enabled() else "ローカル")
        st.caption(f"保存先: {storage_label}")
        cloud_status = cloud_storage_status()
        if not cloud_status["enabled"]:
            st.caption("Supabase設定: " + " / ".join(cloud_status["missing"]) + " が未設定")
        else:
            st.caption(f"Supabase設定: 有効（table: {cloud_status['table']}）")
        st.caption("ブラウザを閉じても、同じURLを開くと作業途中から再開できます。")
        if st.session_state.get("draft_save_error"):
            st.warning(f'一時保存エラー: {st.session_state["draft_save_error"]}')
        uploaded = st.file_uploader("レースJSONを復元", type="json")
        if uploaded and st.button("読み込む", width="stretch"):
            try:
                st.session_state.race = json.load(uploaded); st.success("復元しました"); st.rerun()
            except Exception as exc: st.error(f"読み込み失敗: {exc}")
        if st.button("端末に保存", width="stretch"): persist()
        st.download_button("JSONを書き出す", json.dumps(race, ensure_ascii=False, indent=2, default=str), "race.json", "application/json", width="stretch")
    saved_predictions = list_predictions(limit=50)
    with st.expander(f"保存した予想（{len(saved_predictions)}）", expanded=False):
        if saved_predictions:
            selected_prediction = st.selectbox(
                "予想を選択",
                [item["path"] for item in saved_predictions],
                format_func=lambda p: next(f"{x['title']}  {x['saved_at']}" for x in saved_predictions if x["path"] == p),
            )
            if st.button("この予想を開く", width="stretch"):
                st.session_state.race = load_json(selected_prediction); st.rerun()
        else:
            st.caption("保存された予想はまだありません。手順6で選択して保存できます。")
        st.caption("共有版では表示を軽くするため、一覧は最新50件までです。")
    ollama_models = available_ollama_models()
    ollama_model = ""
    with st.expander("ローカルAI・詳細設定", expanded=False):
        if ollama_models:
            ollama_model = st.selectbox("ローカルAIモデル", ollama_models)
            st.success("キー不要のローカルAIを利用できます。", icon=":material/computer:")
        else:
            st.caption("ローカルAIは未導入です。キー不要モードはルール評価で動作します。")
        st.caption("外部APIは使わず、ローカルAIまたはルール仮評価だけで動作します。")
    st.markdown("<br>", unsafe_allow_html=True)
    st.caption("※ 予想整理の支援ツールです。利益を保証するものではありません。")

info = race.get("race_info", {})
race_name = info.get("レース名") or "レース未設定"
race_no = f"{info.get('レース番号')}R" if info.get("レース番号") else "新規"
race_meta = " / ".join(str(v) for v in [info.get("競馬場"), f"{info.get('芝/ダート','')}{info.get('距離','')}m" if info.get("距離") else "", info.get("馬場"), info.get("発走時刻")] if v)
st.markdown(
    f'<div class="brandbar"><div><h1>競馬予想AI</h1><p>カミノ競馬クラブ｜予想の整理・可視化ワークスペース</p></div><div class="brand-badge">ローカルAI予想支援</div></div>'
    f'<div class="racebar"><div class="race-no">{race_no}</div><strong>{race_name}</strong><span>{race_meta or "レース情報を入力してください"}</span></div>',
    unsafe_allow_html=True,
)
lab_col1, lab_col2 = st.columns([4, 1.25])
with lab_col1:
    st.markdown(
        '<div class="lab-link"><div><strong>3年分の買い目実績を少しずつ蓄積する</strong>'
        '<span>netkeiba・IPATなど外部で買った馬券、買った理由、振り返りをAIの学習ノートへ追加できます。</span></div></div>',
        unsafe_allow_html=True,
    )
with lab_col2:
    st.markdown('<div class="lab-link-button">', unsafe_allow_html=True)
    st.link_button("買い目実績ラボへ", "/?view=lab", icon="📝", width="stretch")
    st.markdown("</div>", unsafe_allow_html=True)

steps = ["1 取込", "2 傾向・評価", "3 スコア・印", "4 オッズ・状態", "5 買い目", "6 出力"]
with st.container(key="workflow_nav"):
    choice = st.radio("ワークフロー", steps, index=st.session_state.step-1, horizontal=True, label_visibility="collapsed")
st.session_state.step = steps.index(choice) + 1
if any(item.get("status") == "pending" for item in race.get("jra_fetch_schedule", [])):
    jra_schedule_runner()


def step1():
    page_head(1, "レースデータを取り込む", "出馬表などのテキストを貼り付け、編集できるデータへ変換します。")
    st.markdown('<div class="guide">まず「レース・出馬表」だけでも開始できます。過去走やコメントは、情報がある場合に追加してください。</div>', unsafe_allow_html=True)
    basic, form, notes = st.tabs(["レース・出馬表", "過去走・コメント", "メモ"])
    with basic:
        c1, c2 = st.columns([.8, 1.2])
        with c1:
            race["raw_inputs"]["レース情報"] = st.text_area("レース情報", race["raw_inputs"].get("レース情報", ""), height=190, key="raw_レース情報", placeholder="例）東京11R ○○ステークス 芝1600m 良 15:45")
        with c2:
            race["raw_inputs"]["出馬表"] = st.text_area("出馬表", race["raw_inputs"].get("出馬表", ""), height=190, key="raw_出馬表", placeholder="出馬表をそのまま貼り付け")
        section_label("PDF・画面キャプチャから取り込む")
        uploaded_race_files = st.file_uploader(
            "PDFまたは画像を選択",
            type=["pdf", "png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            help="netkeiba競馬新聞PDFを推奨します。画像はMacローカルOCRまたは公開環境の無料OCRで解析します。",
        )
        if uploaded_race_files:
            has_newspaper_pdf = any((f.type == "application/pdf" or f.name.lower().endswith(".pdf")) for f in uploaded_race_files)
            analysis_options = (["netkeiba競馬新聞PDF（推奨）"] if has_newspaper_pdf else []) + (["MacローカルOCR（無料・推奨）"] if IS_MAC else ["Tesseract無料OCR"])
            analysis_method = st.radio(
                "解析方式",
                analysis_options,
                horizontal=True,
                help="netkeiba競馬新聞PDFは文字座標から直接解析します。外部APIは不要です。",
            )
            if analysis_method.startswith("Macローカル"):
                st.success("添付例の出馬表レイアウトを自動認識します。赤枠・緑枠の設定や外部APIキーは不要です。", icon=":material/computer:")
            elif analysis_method.startswith("Tesseract"):
                st.success("公開環境の無料OCRで解析します。PDFがある場合はPDF取込の方が安定します。", icon=":material/text_fields:")
            else:
                st.success("このPDF仕様専用の座標パーサーを使用します。レース情報・全馬・血統・過去5走・脚質をAPIなしで抽出します。", icon=":material/picture_as_pdf:")
            active_profile = None
            st.caption(" / ".join(f.name for f in uploaded_race_files[:6]))
            preview_images = [f for f in uploaded_race_files if (f.type or "").startswith("image/")]
            if preview_images:
                st.image([f.getvalue() for f in preview_images[:3]], width=230)
            if st.button("資料からレース・出馬表を解析", type="primary", icon=":material/document_scanner:"):
                media_files = [(f.name, f.type or "application/octet-stream", f.getvalue()) for f in uploaded_race_files[:6]]
                try:
                    progress = st.progress(0, text="解析準備中（0%）")
                    progress_step(progress, 12, "ファイルを確認しています")
                    with st.spinner("PDF・画像を読み取っています…"):
                        extracted_summary = None
                        if analysis_method.startswith("netkeiba競馬新聞PDF"):
                            progress_step(progress, 28, "PDF文字座標を解析しています")
                            first_name, first_mime, first_data = media_files[0]
                            extracted_info, extracted_horses, extracted_summary, extracted_text, extraction_warnings = extract_netkeiba_newspaper_pdf(first_data)
                        elif analysis_method.startswith("Macローカル"):
                            progress_step(progress, 28, "画像OCRを実行しています")
                            first_name, first_mime, first_data = media_files[0]
                            extracted_info, extracted_horses, extracted_text, extraction_warnings = extract_screenshot_with_macos_vision(first_data, first_name, first_mime)
                        elif analysis_method.startswith("Tesseract"):
                            progress_step(progress, 28, "無料OCRを実行しています")
                            first_name, first_mime, first_data = media_files[0]
                            extracted_info, extracted_horses, extracted_text, extraction_warnings = extract_netkeiba_race_table_image_with_tesseract(first_data, first_name)
                        else:
                            raise ValueError("画像を解析できませんでした。netkeiba競馬新聞PDFを使うか、出馬表テキストを貼り付けてください。")
                    progress_step(progress, 78, "読み取り結果を画面へ反映しています")
                    race["race_info"].update({k: v for k, v in extracted_info.items() if v not in ("", None)})
                    if extracted_horses: race["horses"] = extracted_horses
                    if extracted_summary: race["summary"].update(extracted_summary)
                    st.session_state.media_extracted_text = extracted_text
                    st.session_state.media_extraction_warnings = extraction_warnings
                    persist("資料の解析結果を保存しました")
                    progress_step(progress, 100, "解析完了")
                    st.success(f"{len(extracted_horses)}頭を読み取りました。下の表で内容を確認してください。")
                    for warning in extraction_warnings:
                        st.warning(warning)
                except Exception as exc:
                    st.error(f"資料を解析できませんでした: {exc}")
        if st.session_state.get("media_extracted_text"):
            with st.expander("資料から読み取ったテキスト", expanded=False):
                st.text(st.session_state.media_extracted_text[:12000])
        if st.session_state.get("media_extraction_warnings"):
            with st.expander("読み取り精度のチェック", expanded=True):
                for warning in st.session_state.media_extraction_warnings:
                    st.warning(warning)
    with form:
        c1, c2 = st.columns(2)
        with c1: race["raw_inputs"]["過去走情報"] = st.text_area("過去走情報", race["raw_inputs"].get("過去走情報", ""), height=190, key="raw_過去走情報")
        with c2: race["raw_inputs"]["コメント"] = st.text_area("コメント", race["raw_inputs"].get("コメント", ""), height=190, key="raw_コメント")
    with notes:
        race["raw_inputs"]["任意メモ"] = st.text_area("任意メモ", race["raw_inputs"].get("任意メモ", ""), height=150, key="raw_任意メモ", placeholder="気になる馬、展開の仮説、当日の傾向など")
    if st.button("貼り付け内容を解析", type="primary", icon=":material/search:"):
        try:
            info, horses = parse_inputs(race["raw_inputs"])
            race["race_info"].update({k:v for k,v in info.items() if v != ""})
            if horses: race["horses"] = horses
            persist("抽出結果を保存しました")
        except Exception as exc: st.error(f"抽出中にエラーが発生しました。入力テキストは保持されています: {exc}")
    section_label("解析結果を確認")
    st.caption("誤って読み取られた項目は、セルをクリックして直接修正できます。")
    with st.expander("レース基本情報", expanded=True):
        edited_info = st.data_editor(pd.DataFrame([race["race_info"]]), hide_index=True, width="stretch", num_rows="fixed", key="race_info_editor")
    section_label("出走馬")
    edited_horses = st.data_editor(horse_df(), hide_index=True, width="stretch", num_rows="dynamic", key="horse_editor",
        column_config={"馬番": st.column_config.NumberColumn(min_value=1, max_value=18, step=1), "枠番": st.column_config.NumberColumn(min_value=1, max_value=8, step=1), "単勝オッズ": st.column_config.NumberColumn(min_value=0.0), "人気": st.column_config.NumberColumn(min_value=1, max_value=18, step=1)})
    if st.button("この内容で評価へ進む", type="primary", icon=":material/arrow_forward:"):
        race["race_info"] = {k: ("" if pd.isna(v) else v) for k,v in edited_info.iloc[0].to_dict().items()}
        race["horses"] = [{k: ("" if pd.isna(v) else v) for k,v in row.items()} for row in edited_horses.to_dict("records") if str(row.get("馬名", "")).strip()]
        persist(); st.session_state.step = 2; st.rerun()


def step2():
    page_head(2, "各馬を仮評価する", "AIのたたき台を確認し、自分の見立てに合わせて1〜5点で調整します。")
    if not race["horses"]: st.warning("先に手順1で出走馬を登録してください。"); return
    cached_web = load_cached_history(race["race_info"])
    if cached_web and not race.get("web_history"): race["web_history"] = cached_web
    with st.container(border=True):
        web_c1, web_c2 = st.columns([3, 1])
        with web_c1:
            st.markdown("**同名レース10年・同コース距離3年**")
            if race.get("web_history"):
                source = race["web_history"]
                cache_label = "保存データ" if source.get("キャッシュ利用", True) else "新規取得"
                st.caption(f'{source.get("取得元","JRA公式")} / 更新 {source.get("更新日時","-")} / {cache_label}')
            else:
                st.caption("未取得です。初回のみ数分かかる場合があります。以後は保存データを再利用します。")
        with web_c2:
            web_button_label = "Web傾向を更新" if race.get("web_history") else "Web傾向を取得"
            if st.button(web_button_label, type="primary", width="stretch", icon=":material/travel_explore:"):
                start_history_job(race["race_info"], force=bool(race.get("web_history")))
                st.toast("バックグラウンド取得を開始しました"); st.rerun()
        history_job_monitor()
        if race.get("web_history"):
            web = race["web_history"]; named = web.get("同名レース", {}); course = web.get("同条件レース", {})
            w1, w2 = st.columns(2)
            with w1:
                st.metric("同名レース", f'{named.get("サンプル数",0)}件')
                st.caption(f'平均 前半{_lap_format(named.get("平均前半3F"))} / 上がり{_lap_format(named.get("平均上がり3F"))}　ペース S{named.get("ペース内訳",{}).get("S",0)} M{named.get("ペース内訳",{}).get("M",0)} H{named.get("ペース内訳",{}).get("H",0)}')
            with w2:
                st.metric("同コース・距離", f'{course.get("サンプル数",0)}件')
                st.caption(f'平均 前半{_lap_format(course.get("平均前半3F"))} / 上がり{_lap_format(course.get("平均上がり3F"))}　ペース S{course.get("ペース内訳",{}).get("S",0)} M{course.get("ペース内訳",{}).get("M",0)} H{course.get("ペース内訳",{}).get("H",0)}')
            st.caption(web.get("注意", ""))
    race["trend_analysis"] = merge_web_history(analyze_race_trends(race["horses"], race["race_info"]), race.get("web_history"))
    trend = race["trend_analysis"]
    section_label("過去走ラップ・レース傾向")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("想定ペース", trend["想定ペース"])
    t2.metric("有利脚質", trend["有利脚質"])
    t3.metric("解析した過去走", f'{trend["過去走サンプル数"]}走')
    lap_text = f'{trend["平均前半3F"]}秒 → {trend["平均上がり3F"]}秒' if trend["平均前半3F"] != "" and trend["平均上がり3F"] != "" else "材料不足"
    t4.metric("平均ラップ", lap_text)
    pace_counts = trend["ペース内訳"]
    st.caption(f'過去走ペース内訳：スロー {pace_counts["S"]}走 / 平均 {pace_counts["M"]}走 / ハイ {pace_counts["H"]}走。逃げ候補{trend["逃げ候補数"]}頭、先行を含む前方候補{trend["先行候補を含む前方馬数"]}頭から今回の流れを推定しています。')
    if trend.get("Web傾向") and trend["Web傾向"].get("サンプル数"):
        web_trend = trend["Web傾向"]
        st.info(f'Web過去傾向：{web_trend["想定ペース"]}優勢・{web_trend["有利脚質"]}向き（同名{web_trend["同名サンプル数"]}件、同条件{web_trend["同条件サンプル数"]}件）。出走馬の適合指数へ反映済みです。')
    trend_table = pd.DataFrame(trend["適合馬"])
    if not trend_table.empty:
        section_label("データ推奨馬")
        st.dataframe(trend_table.head(5)[["馬番", "馬名", "脚質", "適合指数", "判定", "根拠"]], hide_index=True, width="stretch",
            column_config={"適合指数": st.column_config.ProgressColumn(min_value=20, max_value=90, format="%d")})
        with st.expander("全馬の傾向分析を確認", expanded=False):
            st.dataframe(trend_table[["馬番", "馬名", "脚質", "適合指数", "判定", "近似走数", "平均上がり3F", "根拠"]], hide_index=True, width="stretch",
                column_config={"適合指数": st.column_config.ProgressColumn(min_value=20, max_value=90, format="%d")})
    st.caption("適合指数はPDFの直近走、前半・上がり3F、ペース記号、通過順位を集計した比較用の目安です。データが少ない馬は『条件付き』として扱います。")
    if not race["summary"].get("有利脚質"): race["summary"]["有利脚質"] = trend["有利脚質"]
    if not race["summary"].get("展開予想"): race["summary"]["展開予想"] = f'過去走集計では{trend["想定ペース"]}想定。{trend["有利脚質"]}を中心に確認。'
    c1, c2 = st.columns([1,2.4])
    active_prediction_profile = load_prediction_profile()
    policy_for_ai = prediction_policy_prompt(active_prediction_profile)
    with c1:
        st.caption("仮評価は外部APIを使わず、ローカルAIまたはルール評価で生成します。")
        if st.button("仮評価を生成", type="primary", width="stretch", icon=":material/auto_awesome:"):
            fallback_reason = ""
            progress = st.progress(0, text="仮評価を準備しています（0%）")
            progress_step(progress, 18, "出走馬データを整理しています")
            with st.spinner("各馬を仮評価しています…"):
                if ollama_models:
                    try:
                        progress_step(progress, 38, "ローカルAIで評価しています")
                        scores, comments, risks = evaluate_with_ollama(race["horses"], race["race_info"], ollama_model, policy_for_ai, trend_analysis=trend)
                        source = f"ローカルAI（{ollama_model}）"
                    except Exception:
                        progress_step(progress, 58, "ルール評価へ切り替えています")
                        scores, comments, risks = heuristic_evaluations(race["horses"], active_prediction_profile, trend)
                        source = "ローカル仮評価（AI自動切替）"
                        fallback_reason = "ローカルAIを実行できなかったため"
                else:
                    progress_step(progress, 45, "ローカル仮評価を計算しています")
                    scores, comments, risks = heuristic_evaluations(race["horses"], active_prediction_profile, trend)
                    source = "キー不要のローカル仮評価"
            progress_step(progress, 84, "評価結果を保存しています")
            race["ai_scores"], race["ai_comments"], race["risk_comments"] = scores, comments, risks
            race["final_scores"] = deepcopy(scores)
            race["evaluation_source"] = source
            persist("仮評価を保存しました")
            progress_step(progress, 100, "仮評価完了")
            if fallback_reason:
                st.warning(f"{fallback_reason}、ローカル仮評価で続行しました。入力データと評価は保存済みです。")
            else:
                st.success(f"{source}で仮評価を生成しました。")
    with c2: st.markdown('<div class="guide">評価はあくまで下書きです。材料不足は3点になり、元のAI評価は修正後も履歴として残ります。</div>', unsafe_allow_html=True)
    if race.get("evaluation_source"):
        st.caption(f"現在の仮評価: {race['evaluation_source']}")
    if not race["ai_scores"]: return
    rows = []
    by_no = {str(h.get("馬番")): h for h in race["horses"]}
    for no, scores in race["final_scores"].items():
        rows.append({"馬番": int(no) if str(no).isdigit() else no, "馬名": by_no.get(no,{}).get("馬名", ""), **{key: scores.get(key, 3) for key in SCORE_KEYS}})
    section_label("8項目評価")
    edited = st.data_editor(pd.DataFrame(rows, columns=["馬番", "馬名", *SCORE_KEYS]), hide_index=True, width="stretch", disabled=["馬番", "馬名"], key="score_editor_8items_v1",
        column_config={k: st.column_config.NumberColumn(k, min_value=1, max_value=5, step=1) for k in SCORE_KEYS})
    section_label("評価根拠")
    selected_no = st.selectbox("馬を選択", list(race["final_scores"].keys()), format_func=lambda n: f"{n}番 {by_no.get(n,{}).get('馬名','')}")
    comment_col, risk_col = st.columns(2)
    with comment_col: st.info(f"**評価コメント**\n\n{race['ai_comments'].get(selected_no, '')}")
    with risk_col: st.warning(f"**チェックしたい点**\n\n{race['risk_comments'].get(selected_no, '')}")
    with st.expander("AI仮評価の原本を確認"):
        original_scores = race["ai_scores"].get(selected_no, {})
        st.json({key: original_scores.get(key, 3) for key in SCORE_KEYS})
    if st.button("評価を確定してスコアへ", type="primary", icon=":material/arrow_forward:"):
        race["final_scores"] = {str(int(r["馬番"])) if isinstance(r["馬番"], float) else str(r["馬番"]): {k: int(r[k]) for k in SCORE_KEYS} for r in edited.to_dict("records")}
        learn_prediction_adjustments(race["ai_scores"], race["final_scores"])
        persist(); st.session_state.step = 3; st.rerun()


def step3():
    page_head(3, "スコアと印を組み立てる", "重視する観点を選び、評価をランキングと印へ変換します。")
    if not race["final_scores"]: st.warning("先に手順2で評価を確定してください。"); return
    c1, c2 = st.columns([2,1])
    with c1: preset = st.selectbox("予想スタイル", list(PRESETS), key="preset", help="選んだスタイルに合わせて8項目の重みを調整します")
    with c2:
        st.write("")
        if st.button("スタイルを適用", width="stretch"):
            race["weights"] = {k: PRESETS[preset].get(k, 1.0) for k in SCORE_KEYS}; st.rerun()
    with st.expander("詳細な重みを調整", expanded=False):
        st.caption("通常はプリセットのままで構いません。0.5〜2.0倍で微調整できます。")
        cols = st.columns(3)
        for i, key in enumerate(SCORE_KEYS):
            with cols[i%3]: race["weights"][key] = st.slider(key, .5, 2.0, float(race["weights"].get(key,1)), .05, key=f"weight_{key}")
    if st.button("スコアと印を生成", type="primary", icon=":material/flag:"):
        race["score_results"] = calculate_scores(race["horses"], race["final_scores"], race["weights"])
        race["marks"] = generate_marks(race["score_results"]); persist("スコアと印を保存しました")
    if race["score_results"]:
        display = pd.DataFrame([{**r, "印": race["marks"].get(str(r["馬番"]), "")} for r in race["score_results"]])
        section_label("ランキング")
        frame_colors = {1:"#f4f4f4", 2:"#242424", 3:"#e33b3b", 4:"#356bd8", 5:"#f1cb35", 6:"#3ca45c", 7:"#ef8b2c", 8:"#e987ad"}
        cards = []
        for rank, row in enumerate(race["score_results"][:3], 1):
            frame = int(row.get("枠番") or 1)
            mark = race["marks"].get(str(row["馬番"]), "")
            cards.append(
                f'<div class="rank-card" style="--frame-color:{frame_colors.get(frame,"#0878bd")}">'
                f'<div class="rank-meta"><span>{rank}位</span><span>{frame}枠 {row["馬番"]}番</span></div>'
                f'<div class="horse-name"><span class="rank-mark">{html.escape(mark)}</span> {html.escape(str(row["馬名"]))}</div>'
                f'<div class="race-index">{row.get("レース内指数",50)}<small>レース内指数</small></div></div>'
            )
        st.markdown('<div class="rank-grid">' + ''.join(cards) + '</div>', unsafe_allow_html=True)

        chart_data = display.copy()
        chart_data["ラベル"] = chart_data.apply(lambda r: f'{int(r["馬番"])}  {r["馬名"]}', axis=1)
        chart_data["枠"] = chart_data["枠番"].fillna(1).astype(int).astype(str)
        order = chart_data["ラベル"].tolist()
        bars = alt.Chart(chart_data).mark_bar(cornerRadiusEnd=6, height=18, stroke="#d7dfdb", strokeWidth=.5).encode(
            x=alt.X("レース内指数:Q", scale=alt.Scale(domain=[20,100]), title=None, axis=alt.Axis(grid=True, ticks=False, domain=False)),
            y=alt.Y("ラベル:N", sort=order, title=None, axis=alt.Axis(labelFontSize=12, labelLimit=190, ticks=False, domain=False)),
            color=alt.Color("枠:N", scale=alt.Scale(domain=[str(i) for i in range(1,9)], range=[frame_colors[i] for i in range(1,9)]), legend=None),
            tooltip=[alt.Tooltip("印:N"), alt.Tooltip("馬番:Q"), alt.Tooltip("馬名:N"), alt.Tooltip("レース内指数:Q"), alt.Tooltip("総合スコア:Q", format=".3f")],
        )
        labels = alt.Chart(chart_data).mark_text(align="left", baseline="middle", dx=5, fontWeight="bold", color="#075596").encode(
            x=alt.X("レース内指数:Q"), y=alt.Y("ラベル:N", sort=order), text=alt.Text("レース内指数:Q")
        )
        st.altair_chart((bars + labels).properties(height=max(320, len(chart_data)*29)), use_container_width=True)

        display.insert(1, "枠", display["枠番"].apply(lambda v: f"{int(v)}枠" if pd.notna(v) and str(v) != "" else ""))
        st.dataframe(display[["印","枠","馬番","馬名","レース内指数","本命スコア","条件適性スコア","妙味スコア","総合スコア"]], hide_index=True, width="stretch",
            column_config={"レース内指数": st.column_config.ProgressColumn(min_value=20, max_value=100, format="%d"), "総合スコア": st.column_config.NumberColumn(format="%.3f"), "印": st.column_config.TextColumn(width="small"), "枠": st.column_config.TextColumn(width="small")})
        st.caption("☆は総合4〜7位のうち妙味上位を優先。印は初期提案であり、最終判断ではありません。")
        with st.expander("🎮 有力馬ステータスカード（オプション）", expanded=False):
            st.caption("新しい評価入力ではなく、現在の8項目スコアをゲーム風に見やすくした参考表示です。")
            top_numbers = [str(r["馬番"]) for r in race["score_results"][:min(6, len(race["score_results"]))]]
            selected_card_no = st.selectbox(
                "表示する馬",
                top_numbers,
                format_func=lambda n: f'{race["marks"].get(n,"")} {n}番 {next((h.get("馬名","") for h in race["horses"] if str(h.get("馬番"))==n),"")}',
                key="ability_card_horse",
            )
            card_row = next(r for r in race["score_results"] if str(r["馬番"]) == selected_card_no)
            card_horse = next(h for h in race["horses"] if str(h.get("馬番")) == selected_card_no)
            st.markdown(ability_card(card_row, card_horse, race["final_scores"].get(selected_card_no, {}), race["marks"].get(selected_card_no, "")), unsafe_allow_html=True)
        mark_rows = [{"馬番": int(n) if n.isdigit() else n, "馬名": next((h["馬名"] for h in race["horses"] if str(h["馬番"])==n), ""), "印": m} for n,m in race["marks"].items()]
        edited = st.data_editor(pd.DataFrame(mark_rows), hide_index=True, disabled=["馬番","馬名"], column_config={"印": st.column_config.SelectboxColumn(options=["◎","○","▲","☆","△","消"])}, key="mark_editor")
        if st.button("印を確定してオッズ確認へ", type="primary", icon=":material/arrow_forward:"):
            race["marks"] = {str(r["馬番"]): r["印"] for r in edited.to_dict("records")}; persist(); st.session_state.step=4; st.rerun()


def step5():
    page_head(5, "AIが買い方を組み立てる", "全8券種を横断し、的中・回収・蓄積実績の視点から買い方を比較します。")
    if not race["score_results"]: st.warning("先に手順3でスコアを生成してください。"); return
    st.markdown('<div class="guide">券種や点数の指定は不要です。単勝から三連単までを機械的に比較し、予算と最低購入単位から点数を自動で絞ります。</div>', unsafe_allow_html=True)
    with st.container(border=True):
        section_label("AIに渡す購入条件")
        cols = st.columns(3)
        with cols[0]: budget = st.number_input("購入予算", min_value=100, step=100, key="budget")
        with cols[1]: unit = st.number_input("最小購入単位", min_value=100, step=100, key="unit")
        with cols[2]: min_odds = st.number_input("最低買いオッズ", min_value=1.0, step=.1, key="min_odds")
        allow_torigami = st.checkbox(
            "トリガミを許容する",
            value=bool(race.get("allow_torigami", True)),
            help="オンにすると的中率寄りの保険買いを残します。オフにすると、的中しても購入総額を下回る可能性が高い買い目を削り、回収率優先で組み立てます。",
        )
        race["allow_torigami"] = allow_torigami
        st.caption("点数は入力しません。100円単位・予算上限・候補の質から自動決定します。")
    if st.button("全券種を分析して買い方を提案", type="primary", icon=":material/psychology:"):
        latest_odds = race["odds_history"][-1].get("odds", {}) if race.get("odds_history") else {}
        race["bet_plans"] = propose_bet_plans(race["score_results"], race["marks"], int(budget), int(unit), float(min_odds), latest_odds, load_prediction_profile(), allow_torigami=allow_torigami)
        recommended = next((name for name, plan in race["bet_plans"].items() if plan.get("recommended")), "バランス")
        race["selected_bet_plan"] = recommended
        selected = race["bet_plans"].get(recommended, {})
        race["bets"], race["skipped_bets"] = selected.get("bets", []), selected.get("skipped", [])
        race["marks"] = align_marks_to_bets(race["score_results"], race["bets"], race.get("marks", {}))
        persist("買い方の候補を保存しました")
    if race.get("bet_plans"):
        section_label("AIが比較した買い方")
        plan_names = list(race["bet_plans"])
        plan_cols = st.columns(len(plan_names))
        descriptions = {
            "軸セット": "軸1頭から単勝・馬連・ワイドをセット買い",
            "的中30%型": "点数を絞り、軸の2着以内を主戦にする",
            "回収重視": "馬連と3連複の上積みで回収率を狙う",
            "実績反映": "買い目実績ラボで成績が出ている券種を参考",
            "高回収狙い": "ワイドを抑え、三連系の上振れを狙う",
        }
        for col, name in zip(plan_cols, plan_names):
            plan = race["bet_plans"][name]; summary = plan["summary"]
            badge = "AIおすすめ" if plan.get("recommended") else name
            with col:
                st.markdown(f"**{badge}**")
                st.caption(descriptions.get(name, ""))
                a,b,c = st.columns(3)
                a.metric("点数", summary["点数"]); b.metric("的中", summary["的中期待指数"]); c.metric("回収", summary["回収期待指数"])
                st.caption(f'トリガミ: {summary.get("トリガミ", "許容" if race.get("allow_torigami", True) else "回避")}')
                if summary.get("実績券種"):
                    st.caption(f'参考実績: {summary["実績券種"]}')
        default_plan = race.get("selected_bet_plan") if race.get("selected_bet_plan") in plan_names else plan_names[0]
        selected_name = st.radio("採用する買い方", plan_names, index=plan_names.index(default_plan), horizontal=True)
        selected_plan = race["bet_plans"][selected_name]
        if st.button("この買い方を採用", icon=":material/check_circle:"):
            race["selected_bet_plan"] = selected_name
            race["bets"], race["skipped_bets"] = selected_plan["bets"], selected_plan["skipped"]
            race["marks"] = align_marks_to_bets(race["score_results"], race["bets"], race.get("marks", {}))
            persist(f"{selected_name}を採用しました"); st.rerun()
    with st.expander("買い目を選択式で手動調整する", expanded=bool(race.get("manual_bet_rows"))):
        st.caption("AI案をベースに、軸流し・マルチ・ボックス・フォーメーションなどを選ぶだけで最終買い目を調整できます。金額は1点あたりです。")
        horse_options = [""] + [horse_option_label(h) for h in race.get("horses", []) if horse_option_label(h)]
        horse_multi_options = horse_options[1:]
        ticket_options = ["", "単勝", "複勝", "枠連", "ワイド", "馬連", "馬単", "3連複", "3連単"]
        method_options = ["通常", "軸流し", "軸流しマルチ", "マルチ", "ボックス", "フォーメーション"]
        if st.button("AI案を手動調整欄にコピー", disabled=not bool(race.get("bets")), icon=":material/content_copy:"):
            race["manual_bet_rows"] = [bet_to_manual_row(bet, race.get("horses", [])) for bet in race.get("bets", [])[:5]]
            persist("AI案を手動調整欄へコピーしました")
            st.rerun()
        saved_manual_rows = race.get("manual_bet_rows", []) if isinstance(race.get("manual_bet_rows", []), list) else []
        manual_count = st.number_input("買い方の行数", min_value=1, max_value=5, value=min(5, max(1, len(saved_manual_rows) or 2)), step=1, key="manual_bet_count")
        manual_rows: list[dict] = []
        for idx in range(int(manual_count)):
            saved = saved_manual_rows[idx] if idx < len(saved_manual_rows) and isinstance(saved_manual_rows[idx], dict) else {}
            with st.container(border=True):
                st.caption(f"手動買い方 {idx + 1}")
                t1, t2, t3, t4 = st.columns([1, 1, 1, 1])
                with t1:
                    ticket = st.selectbox("券種", ticket_options, index=option_index(ticket_options, saved.get("券種", "")), key=f"manual_ticket_{idx}")
                with t2:
                    method = st.selectbox("買い方", method_options, index=option_index(method_options, saved.get("買い方", "通常")), key=f"manual_method_{idx}")
                with t3:
                    axis1 = st.selectbox("軸1", horse_options, index=option_index(horse_options, saved.get("軸1", "")), key=f"manual_axis1_{idx}")
                with t4:
                    axis2 = st.selectbox("軸2", horse_options, index=option_index(horse_options, saved.get("軸2", "")), key=f"manual_axis2_{idx}")
                saved_opponents = saved.get("相手候補", saved.get("相手", []))
                if not isinstance(saved_opponents, list):
                    saved_opponents = []
                saved_opponents = list(dict.fromkeys(
                    [v for v in saved_opponents if v in horse_multi_options]
                    + [saved.get(f"相手{i}", "") for i in range(1, 11) if saved.get(f"相手{i}", "") in horse_multi_options]
                ))
                formation1 = saved.get("1列目", []) if isinstance(saved.get("1列目", []), list) else []
                formation2 = saved.get("2列目", []) if isinstance(saved.get("2列目", []), list) else []
                formation3 = saved.get("3列目", []) if isinstance(saved.get("3列目", []), list) else []
                if method == "フォーメーション":
                    st.caption("例：3連複 1頭-3頭-5頭なら、1列目に軸1頭、2列目に3頭、3列目に5頭を選びます。重複する組み合わせは自動で除外します。")
                    f1, f2, f3, amount_col = st.columns([1.2, 1.4, 1.6, .8])
                    with f1:
                        formation1 = st.multiselect("1列目", horse_multi_options, default=[v for v in formation1 if v in horse_multi_options], key=f"manual_form1_{idx}")
                    with f2:
                        formation2 = st.multiselect("2列目", horse_multi_options, default=[v for v in formation2 if v in horse_multi_options], key=f"manual_form2_{idx}")
                    with f3:
                        formation3 = st.multiselect("3列目", horse_multi_options, default=[v for v in formation3 if v in horse_multi_options], key=f"manual_form3_{idx}")
                    with amount_col:
                        amount = st.number_input("1点金額", min_value=0, step=100, value=_to_int(saved.get("1点金額", 0)), key=f"manual_amount_{idx}")
                else:
                    opp_col, amount_col = st.columns([3.6, .8])
                    with opp_col:
                        opponent_candidates = st.multiselect(
                            "相手候補",
                            horse_multi_options,
                            default=saved_opponents,
                            key=f"manual_opponents_{idx}",
                            help="軸流し・ボックスなどの相手をまとめて選べます。必要なら10頭以上でも選択できます。",
                        )
                    with amount_col:
                        amount = st.number_input("1点金額", min_value=0, step=100, value=_to_int(saved.get("1点金額", 0)), key=f"manual_amount_{idx}")
                if method != "フォーメーション":
                    formation1 = formation2 = formation3 = []
                manual_rows.append({
                    "券種": ticket, "買い方": method, "軸1": axis1, "軸2": axis2,
                    "相手候補": opponent_candidates if method != "フォーメーション" else [],
                    "1列目": formation1, "2列目": formation2, "3列目": formation3,
                    "1点金額": amount,
                })
        latest_odds = race["odds_history"][-1].get("odds", {}) if race.get("odds_history") else {}
        manual_bets, manual_skipped, manual_total = manual_bets_from_rows(manual_rows, race, latest_odds, float(min_odds), allow_torigami=bool(race.get("allow_torigami", True)))
        race["manual_bet_rows"] = manual_rows
        c1, c2, c3 = st.columns(3)
        c1.metric("手動買い目数", len(manual_bets))
        c2.metric("手動配分合計", f"{manual_total:,}円")
        c3.metric("予算差分", f"{int(budget) - manual_total:+,}円")
        if manual_total > int(budget):
            st.warning("購入予算を超えています。1点金額か買い方を調整してください。")
        if manual_bets:
            preview = pd.DataFrame([{
                "券種": item["券種"],
                "買い目": item["買い目"],
                "金額": f'{int(item["推奨購入金額"]):,}円',
                "想定配当": f'{float(item["現在オッズ"]):g}倍',
                "想定払戻": f'{int(item["想定払戻"]):,}円',
                "オッズ": item["オッズ区分"],
            } for item in manual_bets])
            st.dataframe(preview, hide_index=True, width="stretch")
        if manual_skipped:
            with st.expander("手動調整で見送りになる候補"):
                st.dataframe(pd.DataFrame([{"買い目": item["買い目"], "理由": item["見送り理由"]} for item in manual_skipped]), hide_index=True)
        if st.button("この手動調整を採用", type="primary", disabled=not manual_bets or manual_total > int(budget), icon=":material/tune:"):
            race["selected_bet_plan"] = "手動調整"
            race["bets"], race["skipped_bets"] = manual_bets, manual_skipped
            race["marks"] = align_marks_to_bets(race["score_results"], race["bets"], race.get("marks", {}))
            persist("手動調整した買い目を保存しました")
            st.rerun()
    if race["bets"]:
        total = sum(b["推奨購入金額"] for b in race["bets"])
        a,b,c = st.columns(3); a.metric("採用プラン", race.get("selected_bet_plan", "AIおすすめ")); b.metric("配分合計", f"{total:,}円"); c.metric("買い目数", len(race["bets"]))
        section_label("採用中の買い目")
        bet_display = pd.DataFrame([{
            "券種": item["券種"], "買い目": item["買い目"],
            "推奨金額": f'{int(item["推奨購入金額"]):,}円',
            "想定配当": f'{float(item["現在オッズ"]):g}倍',
            "想定払戻": f'{int(item["想定払戻"]):,}円',
            "オッズ": item["オッズ区分"], "的中期待": f'{float(item["的中期待度"]):.0f}',
            "回収期待": f'{float(item["回収期待指数"]):.0f}', "狙い": item["狙い"],
        } for item in race["bets"]])
        st.dataframe(bet_display, hide_index=True, width="stretch")
        st.caption("取得値がない券種は単勝オッズからの推定値です。的中・回収の数値は比較用指数であり、確率や利益を保証しません。")
    if race["skipped_bets"]:
        skipped_display = pd.DataFrame([{"買い目": item["買い目"], "想定配当": f'{float(item["現在オッズ"]):g}倍', "見送り理由": item["見送り理由"]} for item in race["skipped_bets"]])
        with st.expander("見送り候補と理由"): st.dataframe(skipped_display, hide_index=True)
    if race["bets"] and st.button("最終サマリーへ", type="primary", icon=":material/arrow_forward:"): st.session_state.step=6; st.rerun()


def step4():
    page_head(4, "オッズと直前状態を確認する", "能力評価を固定したまま、最新オッズと状態変化から妙味を確認します。")
    st.markdown('<div class="guide">評価の軸は固定したまま、オッズ由来の「妙味」だけを見直します。全オッズ入力が難しい場合は、netkeiba等の人気上位表だけでも買い目推定に使えます。</div>', unsafe_allow_html=True)
    with st.expander("JRA公式から指定時刻に自動取得", expanded=True):
        st.caption("JRAへ常時アクセスせず、予約した時刻に1セットだけ取得します。Render無料枠ではスリープや画面離脱で予約取得が止まることがあるため、直前は「今すぐ取得」も使ってください。")
        identity = race.get("race_info", {})
        required_identity = all(identity.get(key) not in ("", None) for key in ("日付", "競馬場", "開催回", "開催日", "レース番号"))
        if not required_identity:
            st.warning("競馬場・開催回・開催日・レース番号を手順1のレース基本情報で確認してください。PDFを再解析すると自動入力されます。")
        start_dt = _race_datetime()
        schedule_c1, schedule_c2 = st.columns(2)
        with schedule_c1:
            odds_fetch_time = st.time_input("オッズ取得時刻", value=(start_dt - timedelta(minutes=5)).time(), step=60, key="jra_odds_fetch_time")
        with schedule_c2:
            result_fetch_time = st.time_input("結果取得時刻", value=(start_dt + timedelta(minutes=20)).time(), step=60, key="jra_result_fetch_time")
        add_backup = st.checkbox("オッズの予備取得を1回追加", value=False, help="本取得の3分前にも一度だけ取得します。")
        if st.button("この時刻でJRA自動取得を予約", disabled=not required_identity, icon=":material/schedule:"):
            race_day = start_dt.date()
            odds_at = datetime.combine(race_day, odds_fetch_time)
            result_at = datetime.combine(race_day, result_fetch_time)
            completed = [item for item in race.get("jra_fetch_schedule", []) if item.get("status") in {"completed", "error"}]
            jobs = [{"kind": "odds", "scheduled_at": odds_at.isoformat(timespec="minutes"), "status": "pending"}]
            if add_backup:
                jobs.insert(0, {"kind": "odds", "scheduled_at": (odds_at - timedelta(minutes=3)).isoformat(timespec="minutes"), "status": "pending"})
            jobs.append({"kind": "result", "scheduled_at": result_at.isoformat(timespec="minutes"), "status": "pending"})
            race["jra_fetch_schedule"] = completed + jobs
            persist("JRA自動取得を予約しました"); st.rerun()
        now_c1, now_c2 = st.columns(2)
        with now_c1:
            if st.button("今すぐJRAオッズ取得", disabled=not required_identity, icon=":material/refresh:"):
                with st.spinner("JRA公式からオッズを取得しています…"):
                    job = {"kind": "odds", "scheduled_at": datetime.now().isoformat(timespec="minutes"), "status": "pending", "manual": True}
                    run_jra_fetch_job(race, job)
                    persist("JRAオッズ取得を実行しました")
                st.rerun()
        with now_c2:
            if st.button("今すぐJRA結果取得", disabled=not required_identity, icon=":material/flag:"):
                with st.spinner("JRA公式から結果を取得しています…"):
                    job = {"kind": "result", "scheduled_at": datetime.now().isoformat(timespec="minutes"), "status": "pending", "manual": True}
                    run_jra_fetch_job(race, job)
                    persist("JRA結果取得を実行しました")
                st.rerun()
        if race.get("jra_fetch_schedule"):
            status_labels = {"pending": "待機中", "fetching": "取得中", "completed": "完了", "error": "要確認"}
            schedule_rows = [{"種類": "オッズ" if item["kind"] == "odds" else "結果", "予定時刻": item["scheduled_at"].replace("T", " "), "状態": status_labels.get(item.get("status"), item.get("status")), "内容": item.get("message", "")} for item in race["jra_fetch_schedule"]]
            st.dataframe(pd.DataFrame(schedule_rows), hide_index=True, width="stretch")
        if race.get("jra_auto_fetch_log"):
            with st.expander("JRA取得ログ", expanded=False):
                status_labels = {"pending": "待機中", "fetching": "取得中", "completed": "完了", "error": "要確認"}
                log_rows = [{
                    "種類": "オッズ" if item.get("kind") == "odds" else "結果",
                    "実行時刻": item.get("completed_at", item.get("scheduled_at", "")).replace("T", " "),
                    "状態": status_labels.get(item.get("status"), item.get("status", "")),
                    "内容": item.get("message", ""),
                } for item in race["jra_auto_fetch_log"][-8:]]
                st.dataframe(pd.DataFrame(log_rows), hide_index=True, width="stretch")
    section_label("手動入力（自動取得できない場合）")
    with st.expander("人気上位オッズ表から推定する", expanded=True):
        st.caption("おすすめはURL取得です。netkeibaの人気上位オッズ表を直接読み取り、表示されていない買い目は単勝支持率から推定します。画像・テキスト入力は予備手段として使えます。")
        odds_url = st.text_input(
            "netkeibaオッズページURL",
            value=race.get("popular_odds_url", ""),
            placeholder="https://race.netkeiba.com/odds/index.html?race_id=...",
            help="頻繁に自動巡回せず、このボタンを押した時だけ取得します。ページ形式やアクセス制限により取得できない場合があります。",
        )
        race["popular_odds_url"] = odds_url
        if st.button("URLから人気上位オッズを取得", icon=":material/link:"):
            try:
                parsed, transcript = fetch_netkeiba_popular_odds(odds_url)
                race["popular_odds_snapshot_text"] = transcript
                race["popular_odds_image_method"] = "netkeiba URL取得"
                race["popular_odds_image_parsed"] = parsed
                persist("netkeibaのURLから人気上位オッズを取得しました")
                st.rerun()
            except Exception as exc:
                st.error(f"URLからオッズを取得できませんでした: {exc}")
                st.caption("ログインが必要なページ、アクセス制限、ページ形式変更の可能性があります。その場合は画像アップロードかテキスト貼り付けを使ってください。")
        odds_images = st.file_uploader(
            "オッズ表画像をアップロード（複数可）",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key="popular_odds_image",
            help="全券種まとめ画像より、単勝・馬連・ワイド・3連複など券種別の上位人気スクショを複数入れる方が精度が上がります。",
        )
        odds_reading_mode = st.radio(
            "オッズ画像の解析モード",
            ["軽量", "標準", "詳細"],
            horizontal=True,
            index=0,
            help="軽量は3連系の人気順を上位30件までに絞ります。標準は50件、詳細は100件まで読みます。馬連・ワイド・馬単の全組み合わせ表は専用処理で読みます。",
        )
        max_rows_by_mode = {"軽量": 30, "標準": 50, "詳細": 100}
        max_vertical_rows = max_rows_by_mode.get(odds_reading_mode, 30)
        ocr_mode = st.radio(
            "画像読み取り方法",
            ["固定レイアウトOCR", "無料OCRを優先"],
            horizontal=True,
            help="固定レイアウトOCRはnetkeibaの人気上位表スクショ向きです。通常はこちらを使います。",
        )
        image_parsed = race.get("popular_odds_image_parsed", {})
        if odds_images:
            st.caption(f"{len(odds_images)}枚のオッズ画像を選択中。{odds_reading_mode}モードでは、縦長の人気順表は上位{max_vertical_rows}件まで読みます。")
            preview_cols = st.columns(min(3, len(odds_images)))
            for idx, odds_image in enumerate(odds_images[:3]):
                with preview_cols[idx % len(preview_cols)]:
                    st.image(odds_image.getvalue(), caption=getattr(odds_image, "name", f"画像{idx + 1}"), width="stretch")
            if len(odds_images) > 3:
                st.caption(f"ほか {len(odds_images) - 3} 枚")
            if st.button("画像から人気上位オッズを読み取る", icon=":material/image_search:"):
                try:
                    merged_parsed = {}
                    transcript_parts = []
                    method_parts = []
                    errors = []
                    cache = race.setdefault("popular_odds_image_cache", {})
                    cache_hits = 0
                    for odds_image in odds_images:
                        image_bytes_data = odds_image.getvalue()
                        digest = hashlib.sha256(image_bytes_data).hexdigest()
                        cache_key = f"v2:{ocr_mode}:{odds_reading_mode}:{max_vertical_rows}:{digest}"
                        local_mode = ocr_mode
                        transcript = ""
                        parsed = {}
                        method = ""
                        name = getattr(odds_image, "name", "画像")
                        cached = cache.get(cache_key)
                        if isinstance(cached, dict) and cached.get("parsed"):
                            parsed = cached.get("parsed", {})
                            transcript = cached.get("transcript", "")
                            method = cached.get("method", "画像OCRキャッシュ")
                            cache_hits += 1
                        if local_mode == "固定レイアウトOCR":
                            if not parsed:
                                try:
                                    parsed, transcript = parse_netkeiba_popular_odds_image_layout(image_bytes_data, max_vertical_rows=max_vertical_rows)
                                    method = f"固定レイアウトOCR（{odds_reading_mode}）"
                                except Exception as layout_exc:
                                    errors.append(f"{name}: 固定レイアウトOCR不可 → 無料OCRへ切替（{layout_exc}）")
                                    local_mode = "無料OCRを優先"
                        if local_mode == "無料OCRを優先" and not parsed:
                            try:
                                transcript = ocr_text_with_macos_vision(image_bytes_data) if IS_MAC else ocr_popular_odds_image_with_tesseract(image_bytes_data)
                                parsed = parse_popular_odds_snapshot(transcript)
                                method = "Mac標準OCR" if IS_MAC else "Tesseract無料OCR"
                            except Exception as local_exc:
                                raise local_exc
                        if parsed:
                            merged_parsed.update(parsed)
                            transcript_parts.append(f"【{name} / {method or '画像OCR'}】\n{transcript}")
                            method_parts.append(method or "画像OCR")
                            cache[cache_key] = {
                                "name": name,
                                "parsed": parsed,
                                "transcript": transcript,
                                "method": method or "画像OCR",
                                "count": len(parsed),
                                "created_at": datetime.now().isoformat(timespec="seconds"),
                            }
                        else:
                            errors.append(f"{name}: オッズ表を読み取れませんでした")
                    if not merged_parsed:
                        raise ValueError("画像内のオッズ表を読み取れませんでした。画像の解像度や表示範囲を確認してください。")
                    if errors:
                        for message in errors[:5]:
                            st.warning(message)
                    if cache_hits:
                        st.info(f"{cache_hits}枚は保存済みの読み取り結果を使いました。", icon=":material/cached:")
                    race["popular_odds_snapshot_text"] = "\n\n".join(transcript_parts)
                    race["popular_odds_image_method"] = " / ".join(sorted(set(method_parts))) or "画像OCR"
                    race["popular_odds_image_parsed"] = merged_parsed
                    image_parsed = merged_parsed
                    persist("オッズ表画像の読み取り結果を保存しました")
                    st.rerun()
                except Exception as exc:
                    st.error(f"画像からオッズを読み取れませんでした: {exc}")
        if image_parsed:
            st.success(f"画像から{len(image_parsed)}件のオッズを読み取り済みです。方式: {race.get('popular_odds_image_method', '画像OCR')}", icon=":material/photo_camera:")
        popular_snapshot = st.text_area(
            "人気上位表テキスト",
            value=race.get("popular_odds_snapshot_text", ""),
            height=170,
            placeholder="例）\n単勝・複勝\n1 3 5 イガッチ 5.9 2.2 - 2.5\n...\n馬連・ワイド\n1 5 - 8 15.3 9.6 - 10.1\n...\n3連単\n1 11 > 12 > 4 73.1",
        )
        race["popular_odds_snapshot_text"] = popular_snapshot
        parsed_popular = {**image_parsed, **parse_popular_odds_snapshot(popular_snapshot)}
        if parsed_popular:
            st.success(f"{len(parsed_popular)}件の人気上位オッズを読み取りました。", icon=":material/check_circle:")
            preview = pd.DataFrame([{"買い目": key, "オッズ": value} for key, value in sorted(parsed_popular.items())[:20]])
            st.dataframe(preview, hide_index=True, width="stretch")
        else:
            st.caption("貼り付けると、ここに読み取り結果が表示されます。")
    texts = {}
    odds_tabs = st.tabs(["単勝", "複勝", "ワイド", "馬連", "馬単", "3連複", "3連単"])
    for tab, kind in zip(odds_tabs, ["単勝","複勝","ワイド","馬連","馬単","3連複","3連単"]):
        with tab: texts[kind] = st.text_area(f"{kind}オッズ", height=170, placeholder="例: 1 3.2\n2 5.8" if kind=="単勝" else "例: 1-3 4.5", label_visibility="collapsed")
    c1,c2 = st.columns(2)
    with c1: acquired = st.text_input("オッズ取得時刻", datetime.now().strftime("%Y-%m-%d %H:%M"))
    with c2: memo = st.text_input("更新メモ")
    if st.button("オッズを反映", type="primary", icon=":material/refresh:"):
        current = dict(parsed_popular)
        [current.update(parse_odds(texts[k], k)) for k in texts]
        previous = race["odds_history"][-1].get("odds", {}) if race["odds_history"] else {}
        comparisons, alerts = compare_odds(previous, current, float(st.session_state.min_odds))
        race["odds_history"].append({"取得時刻": acquired, "更新メモ": memo, "odds": current, "comparisons": comparisons, "入力種別": "人気上位表＋手動入力" if parsed_popular else "手動入力"})
        race["alerts"] = alerts
        for horse in race.get("horses", []):
            key = f'単勝 {horse.get("馬番")}'
            if key in current:
                horse["単勝オッズ"] = current[key]
        # 基礎8項目は固定。オッズ由来の妙味だけを穏やかに補正し、買い目・配分を更新。
        for key, now in current.items():
            if key.startswith("単勝 "):
                no = key.split()[1]; prev = previous.get(key)
                if no in race["final_scores"] and prev:
                    ratio = now / prev
                    old = race["final_scores"][no]["妙味"]
                    race["final_scores"][no]["妙味"] = max(1, min(5, old + (1 if ratio >= 1.25 else -1 if ratio <= .7 else 0)))
        race["score_results"] = calculate_scores(race["horses"], race["final_scores"], race["weights"])
        race["bet_plans"] = propose_bet_plans(race["score_results"], race["marks"], int(st.session_state.budget), int(st.session_state.unit), float(st.session_state.min_odds), current, load_prediction_profile(), allow_torigami=bool(race.get("allow_torigami", True)))
        selected_name = race.get("selected_bet_plan")
        if selected_name not in race["bet_plans"]:
            selected_name = next((name for name, plan in race["bet_plans"].items() if plan.get("recommended")), next(iter(race["bet_plans"]), ""))
        selected_plan = race["bet_plans"].get(selected_name, {})
        race["selected_bet_plan"] = selected_name
        race["bets"], race["skipped_bets"] = selected_plan.get("bets", []), selected_plan.get("skipped", [])
        race["marks"] = align_marks_to_bets(race["score_results"], race["bets"], race.get("marks", {}))
        persist("オッズ履歴と再配分を保存しました")
    if race["odds_history"]:
        latest = race["odds_history"][-1]
        section_label("オッズ変動")
        st.dataframe(pd.DataFrame(latest["comparisons"]), hide_index=True, width="stretch")
        if race["alerts"]:
            for alert in race["alerts"]: st.warning(alert)
        else: st.success("設定したアラート条件には該当しません。")
        st.caption("オッズ更新では妙味、買い目、配分のみを再計算し、他の評価項目は変更しません。")
    if st.button("買い目作成へ", type="primary", icon=":material/arrow_forward:"): st.session_state.step=5; st.rerun()


def step6():
    page_head(6, "予想を1枚にまとめる", "判断材料・印・買い目を、見返しやすいレースサマリーとして保存します。")
    summary = race["summary"]
    c1,c2 = st.columns(2)
    with c1:
        summary["レース総評"] = st.text_area("レース総評", summary.get("レース総評",""))
        summary["展開予想"] = st.text_area("展開予想", summary.get("展開予想",""))
        summary["買い判断"] = st.text_area("買い判断", summary.get("買い判断",""))
    with c2:
        summary["有利脚質"] = st.text_input("有利脚質", summary.get("有利脚質",""))
        summary["波乱度"] = st.select_slider("波乱度", ["低","中","高"], value=summary.get("波乱度","中"))
        summary["注意点"] = st.text_area("注意点", summary.get("注意点",""))
    if not race["score_results"]: st.warning("出力前に手順3でスコアを生成してください。"); return
    section_label("保存オプション")
    save_to_history = st.checkbox("この予想を履歴に保存して蓄積する", value=False, help="チェックした場合だけ、現在の評価・印・買い目・オッズをスナップショットとして保存します。")
    history_label = ""
    if save_to_history:
        default_label = " ".join(str(v) for v in [race["race_info"].get("日付", ""), race["race_info"].get("競馬場", ""), race["race_info"].get("レース名", "")] if v)
        history_label = st.text_input("保存名", value=default_label)
    if st.button("サマリーをプレビュー", type="primary", icon=":material/preview:"):
        race["output_data"] = {"generated_at": datetime.now().isoformat(), "layout": "top/left/center/right/bottom"}; persist("出力用データを保存しました")
        try:
            image = render_summary(race); st.session_state.summary_png = image_bytes(image, "PNG"); st.session_state.summary_pdf = image_bytes(image, "PDF")
            if save_to_history:
                archived = archive_prediction(race, history_label)
                st.success(f"予想履歴に保存しました: {archived.name}")
        except Exception as exc: st.error(f"サマリー生成に失敗しました: {exc}")
    if "summary_png" in st.session_state:
        section_label("プレビュー")
        st.image(st.session_state.summary_png, caption="1枚サマリー", width="stretch")
        c1,c2 = st.columns(2)
        c1.download_button("PNG画像を保存", st.session_state.summary_png, "race_summary.png", "image/png", width="stretch")
        c2.download_button("PDFを保存", st.session_state.summary_pdf, "race_summary.pdf", "application/pdf", width="stretch")
        st.caption("オッズは変動します。払戻・利益は目安であり、利益を保証するものではありません。")

    section_label("レース結果を共有して予想を磨く")
    existing_feedback = race.get("result_feedback", {})
    with st.expander("結果・振り返りを登録", expanded=bool(existing_feedback)):
        st.caption("結果はこのMac内に保存し、次回以降のAI仮評価へ集計情報と振り返りメモを反映します。同じレースは学習回数に重複計上しません。")
        result_order = st.text_area(
            "確定着順（馬番）",
            value=existing_feedback.get("確定着順", ""),
            height=100,
            placeholder="例）1着 7番\n2着 8番\n3着 6番　または 7-8-6",
            key="result_order",
        )
        result_c1, result_c2 = st.columns(2)
        with result_c1:
            actual_track_pace = st.text_area("実際の馬場・展開", existing_feedback.get("実際の馬場・展開", ""), height=110, key="actual_track_pace")
            correct_view = st.text_area("当たっていた見解", existing_feedback.get("当たっていた見解", ""), height=110, key="correct_view")
        with result_c2:
            missed_view = st.text_area("外れた見解", existing_feedback.get("外れた見解", ""), height=110, key="missed_view")
            next_lesson = st.text_area("次回への学び", existing_feedback.get("次回への学び", ""), height=110, key="next_lesson")
        money_c1, money_c2 = st.columns(2)
        default_spend = int(existing_feedback.get("実購入額", sum(int(b.get("推奨購入金額", 0)) for b in race.get("bets", []))))
        with money_c1: actual_spend = st.number_input("実購入額", min_value=0, step=100, value=default_spend, key="actual_spend")
        with money_c2: actual_return = st.number_input("実払戻額", min_value=0, step=100, value=int(existing_feedback.get("実払戻額", 0)), key="actual_return")
        if st.button("結果を保存して学習に反映", type="primary", icon=":material/model_training:"):
            feedback = {
                "確定着順": result_order,
                "実際の馬場・展開": actual_track_pace,
                "当たっていた見解": correct_view,
                "外れた見解": missed_view,
                "次回への学び": next_lesson,
                "実購入額": int(actual_spend),
                "実払戻額": int(actual_return),
                "収支": int(actual_return) - int(actual_spend),
                "登録日時": datetime.now().isoformat(),
            }
            try:
                actual_numbers = parse_finish_order(result_order)
                if not actual_numbers: raise ValueError("着順の馬番を入力してください")
                predicted_numbers = [str(r.get("馬番")) for r in race.get("score_results", [])]
                feedback["勝ち馬の事前順位"] = predicted_numbers.index(actual_numbers[0]) + 1 if actual_numbers[0] in predicted_numbers else ""
                feedback["上位3頭一致率"] = round(len(set(predicted_numbers[:3]) & set(actual_numbers[:3])) / max(1, min(3, len(actual_numbers))), 3)
                race["result_feedback"] = feedback
                learned_profile = learn_from_race_result(race, feedback)
                persist("結果と振り返りを保存しました")
                label = " ".join(str(v) for v in [race["race_info"].get("日付", ""), race["race_info"].get("競馬場", ""), race["race_info"].get("レース名", ""), "振り返り済み"] if v)
                archive_prediction(race, label)
                st.success(f'結果を反映しました。累計{learned_profile["result_learning"]["reviews"]}レースを次回評価の参考にします。')
            except Exception as exc:
                st.error(f"結果を保存できませんでした: {exc}")
    if race.get("result_feedback"):
        result = race["result_feedback"]
        r1, r2, r3 = st.columns(3)
        r1.metric("勝ち馬の事前順位", f'{result.get("勝ち馬の事前順位", "-")}位')
        r2.metric("上位3頭一致率", f'{float(result.get("上位3頭一致率", 0))*100:.0f}%')
        r3.metric("実収支", f'{int(result.get("収支", 0)):+,}円')

    section_label("過去の予想と結果をまとめて学習")
    with st.expander("過去データを一括取り込み", expanded=False):
        st.caption("このツールから書き出したレースJSON・予想履歴JSONを複数選択できます。確定着順と事前評価が揃ったレースだけを分析し、同じレースは重複計上しません。")
        history_files = st.file_uploader("結果付き予想JSONを選択", type="json", accept_multiple_files=True, key="result_history_files")
        if history_files and st.button("過去データを分析して蓄積", type="primary", icon=":material/history_edu:"):
            states, read_errors = [], []
            for uploaded in history_files:
                try:
                    payload = json.load(uploaded)
                    if isinstance(payload, list): states.extend(payload)
                    elif isinstance(payload, dict) and isinstance(payload.get("races"), list): states.extend(payload["races"])
                    elif isinstance(payload, dict): states.append(payload)
                    else: read_errors.append(f"{uploaded.name}: 対応していない形式")
                except Exception as exc:
                    read_errors.append(f"{uploaded.name}: {exc}")
            learned_profile, report = learn_from_result_history(states)
            st.session_state.prediction_policy = learned_profile.get("policy", st.session_state.prediction_policy)
            if report["新規反映"]:
                st.success(f'{report["新規反映"]}レースを新たに反映しました。累計{report["累計"]}レースです。')
            else:
                st.info("新たに反映できる結果付きレースはありませんでした。")
            st.caption(f'重複 {report["重複"]}件 / 結果・評価不足 {report["結果不足"]}件')
            for message in [*read_errors, *report["エラー"]]: st.warning(message)

    learned = load_prediction_profile().get("result_learning", {})
    review_count = int(learned.get("reviews", 0))
    if review_count:
        section_label("蓄積した分析")
        average_rank = float(learned.get("winner_rank_total", 0)) / review_count
        average_coverage = float(learned.get("top3_coverage_total", 0)) / review_count * 100
        signals = [(key, float(value)) for key, value in learned.get("category_signals", {}).items() if key in SCORE_KEYS]
        signals.sort(key=lambda item: item[1], reverse=True)
        strongest = "、".join(key for key, _ in signals[:3]) or "分析中"
        l1, l2, l3 = st.columns(3)
        l1.metric("学習済みレース", f"{review_count}件")
        l2.metric("勝ち馬の事前平均順位", f"{average_rank:.1f}位")
        l3.metric("上位3頭の平均一致率", f"{average_coverage:.0f}%")
        st.info(f"これまで相対的に結果との関連が強かった評価軸：{strongest}")
        lessons = learned.get("lessons", [])[-5:]
        if lessons:
            with st.expander("最近の振り返りメモ"):
                for lesson in reversed(lessons): st.write(f"・{lesson}")


[step1, step2, step3, step4, step5, step6][st.session_state.step-1]()
st.markdown('<div class="maker">競馬予想AI　制作：カミノ競馬クラブ</div>', unsafe_allow_html=True)
save_draft(race)
