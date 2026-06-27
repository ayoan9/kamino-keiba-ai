from __future__ import annotations

import json
import math
import os
import re
import base64
import getpass
import subprocess
import unicodedata
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

SCORE_KEYS = [
    "近走評価", "距離・コース適性", "馬場適性", "展開利", "本命適性",
    "妙味", "騎手評価", "厩舎・ローテ評価",
]

BASE_WEIGHTS = {
    "本命スコア": {"近走評価": .20, "距離・コース適性": .15, "展開利": .15, "本命適性": .30, "騎手評価": .10, "厩舎・ローテ評価": .10},
    # 血統は独立採点せず、距離・コース適性と馬場適性の判断材料へ統合する。
    "条件適性スコア": {"距離・コース適性": .35, "馬場適性": .30, "展開利": .20, "厩舎・ローテ評価": .15},
    "妙味スコア": {"妙味": .40, "近走評価": .15, "馬場適性": .30, "展開利": .15},
}

PRESETS = {
    "標準": {},
    "単勝勝負": {"本命適性": 1.5, "近走評価": 1.25, "妙味": .75},
    "軸安定": {"本命適性": 1.6, "距離・コース適性": 1.2, "妙味": .6},
    "穴狙い": {"妙味": 1.8, "距離・コース適性": 1.15, "馬場適性": 1.15, "本命適性": .75},
    "馬場重視": {"馬場適性": 1.8},
    "展開重視": {"展開利": 1.8, "近走評価": .9},
}

HORSE_COLUMNS = ["馬番", "枠番", "馬名", "性齢", "斤量", "騎手", "厩舎", "人気", "単勝オッズ", "脚質", "父", "母", "母父", "過去走テキスト", "コメント"]

DEFAULT_LAYOUT_PROFILE = {
    "name": "標準キャプチャ",
    "race_header": [0.0, 0.0, 1.0, 0.25],
    "horse_table": [0.0, 0.20, 1.0, 1.0],
}
KEYCHAIN_SERVICE = "jp.kamino.keiba-ai.openai"


def new_state() -> dict[str, Any]:
    return {
        "race_info": {k: "" for k in ["日付", "競馬場", "開催回", "開催日", "レース番号", "レース名", "芝/ダート", "距離", "馬場", "天候", "頭数", "発走時刻"]},
        "raw_inputs": {k: "" for k in ["レース情報", "出馬表", "過去走情報", "コメント", "任意メモ"]},
        "horses": [], "ai_scores": {}, "final_scores": {}, "ai_comments": {}, "risk_comments": {},
        "evaluation_source": "",
        "score_results": [], "marks": {}, "weights": {k: 1.0 for k in SCORE_KEYS},
        "bets": [], "bet_plans": {}, "selected_bet_plan": "AIおすすめ", "skipped_bets": [], "odds_history": [], "alerts": [],
        "jra_fetch_schedule": [], "jra_auto_fetch_log": [],
        "result_feedback": {}, "trend_analysis": {}, "web_history": {},
        "summary": {"レース総評": "", "展開予想": "", "有利脚質": "", "波乱度": "中", "買い判断": "", "注意点": "オッズは変動します。払戻・利益は目安です。"},
    }


def _find(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.I)
    return m.group(1).strip() if m else ""


def parse_inputs(raw: dict[str, str]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    info_text = raw.get("レース情報", "")
    all_text = "\n".join(raw.values())
    race_name = _find(r"\d{1,2}\s*R\s+(.+?)(?=\s+(?:芝|ダート|ダ)\s*\d{3,4})", info_text)
    if not race_name:
        race_name = _find(r"([^\n]*(?:賞|ステークス|カップ|記念|特別))", info_text)
    info = {
        "日付": _find(r"(20\d{2}[年/\-.]\s*\d{1,2}[月/\-.]\s*\d{1,2}日?)", info_text),
        "競馬場": _find(r"(東京|中山|阪神|京都|中京|札幌|函館|福島|新潟|小倉)", info_text),
        "開催回": _find(r"(\d+)\s*回(?:東京|中山|阪神|京都|中京|札幌|函館|福島|新潟|小倉)", info_text),
        "開催日": _find(r"\d+\s*回(?:東京|中山|阪神|京都|中京|札幌|函館|福島|新潟|小倉)\s*(\d+)\s*日", info_text),
        "レース番号": _find(r"(?:^|\s)(\d{1,2})\s*R\b", info_text),
        "レース名": race_name,
        "芝/ダート": _find(r"(芝|ダート|ダ)\s*\d{3,4}", info_text).replace("ダ", "ダート"),
        "距離": _find(r"(?:芝|ダート|ダ)\s*(\d{3,4})\s*m?", info_text),
        "馬場": _find(r"(?:馬場|馬場状態)\s*[:：]?\s*(良|稍重|重|不良)", info_text),
        "天候": _find(r"(?:天候|天気)\s*[:：]?\s*([^\s/]+)", info_text),
        "頭数": _find(r"(\d{1,2})\s*頭", info_text),
        "発走時刻": _find(r"(?:発走)?\s*(\d{1,2}:\d{2})", info_text),
    }
    past = raw.get("過去走情報", "")
    comments = raw.get("コメント", "")
    horses: list[dict[str, Any]] = []
    sep = r"[\s|｜,\t]+"
    line_re = re.compile(rf"^\s*(\d{{1,2}}){sep}(\d{{1,2}}){sep}(.+?){sep}(牡|牝|セ)\s*(\d{{1,2}})(?:{sep}([45-6]\d(?:\.\d)?))?(.*)$")
    for line in raw.get("出馬表", "").splitlines():
        m = line_re.match(line)
        if not m:
            continue
        frame, no, name, sex, age, weight, rest = m.groups()
        tokens = [x for x in re.split(r"[|｜\t, ]+", rest.strip()) if x]
        jockey = tokens[0] if tokens else ""
        stable = tokens[1] if len(tokens) > 1 else ""
        pop = next((x for x in tokens[2:] if re.fullmatch(r"\d{1,2}(?:番人気)?", x)), "").replace("番人気", "")
        odds = next((x for x in tokens[2:] if re.fullmatch(r"\d{1,3}\.\d", x)), "")
        style = next((x for x in tokens if x in {"逃げ", "先行", "差し", "追込", "追い込み"}), "")
        horse = {k: "" for k in HORSE_COLUMNS}
        horse.update({"枠番": int(frame), "馬番": int(no), "馬名": name.strip(), "性齢": f"{sex}{age}", "斤量": weight or "", "騎手": jockey, "厩舎": stable, "人気": pop, "単勝オッズ": odds, "脚質": style})
        horse["過去走テキスト"] = _horse_related_text(name.strip(), no, past)
        horse["コメント"] = _horse_related_text(name.strip(), no, comments)
        horses.append(horse)
    if not info["頭数"] and horses:
        info["頭数"] = str(len(horses))
    return info, horses


def _horse_related_text(name: str, number: str, text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if name in ln or re.match(rf"^\s*{number}[\s:：]", ln)]
    return " / ".join(lines[:5])


def _past_run_laps(text: str) -> list[dict]:
    runs = []
    for segment in str(text or "").split(" / "):
        condition = re.search(r"(芝|ダート|ダ)\s*(\d{3,4})\s+(\d{1,2})", segment)
        lap = re.search(r"(\d{2}\.\d)\s*([SMH])\s*(\d{2}\.\d)", segment)
        if not condition and not lap:
            continue
        going = re.search(r"(?:右|左|直)(?:外)?[A-D]?\s*(良|稍重|重|不良)", segment)
        runs.append({
            "芝/ダート": "ダート" if condition and condition.group(1) in {"ダート", "ダ"} else "芝" if condition else "",
            "距離": int(condition.group(2)) if condition else 0,
            "着順": int(condition.group(3)) if condition else 0,
            "馬場": going.group(1) if going else "",
            "前半3F": float(lap.group(1)) if lap else None,
            "ペース": lap.group(2) if lap else "",
            "上がり3F": float(lap.group(3)) if lap else None,
        })
    return runs


def analyze_race_trends(horses: list[dict], race_info: dict) -> dict:
    """Aggregate entrant past-run laps and rank projected race-pattern compatibility."""
    styles = [str(h.get("脚質", "")) for h in horses]
    escape = sum(style == "逃げ" for style in styles)
    forward = sum(style in {"逃げ", "先行"} for style in styles)
    projected = "H" if escape >= 2 or forward >= 5 else "S" if escape == 0 and forward <= 2 else "M"
    pace_label = {"S": "スロー", "M": "平均", "H": "ハイ"}[projected]
    favorable = {"S": "逃げ・先行", "M": "先行・差し", "H": "差し・追込"}[projected]
    surface = str(race_info.get("芝/ダート", ""))
    distance = int(float(race_info.get("距離", 0) or 0))
    track = str(race_info.get("馬場", ""))
    all_runs, parsed = [], {}
    for horse in horses:
        no = str(horse.get("馬番", ""))
        runs = _past_run_laps(horse.get("過去走テキスト", ""))
        parsed[no] = runs; all_runs.extend(runs)
    pace_counts = {key: sum(run.get("ペース") == key for run in all_runs) for key in ("S", "M", "H")}
    first_laps = [run["前半3F"] for run in all_runs if run.get("前半3F") is not None]
    last_laps = [run["上がり3F"] for run in all_runs if run.get("上がり3F") is not None]
    field_last_avg = sum(last_laps) / len(last_laps) if last_laps else None
    style_points = {
        "S": {"逃げ": 14, "先行": 10, "差し": -4, "追込": -9},
        "M": {"逃げ": 2, "先行": 9, "差し": 7, "追込": 0},
        "H": {"逃げ": -10, "先行": -4, "差し": 12, "追込": 10},
    }
    matches = []
    for horse in horses:
        no = str(horse.get("馬番", "")); style = str(horse.get("脚質", ""))
        runs = parsed.get(no, [])
        similar = [run for run in runs if (not surface or run["芝/ダート"] == surface) and (not distance or abs(run["距離"] - distance) <= 200)]
        pace_runs = [run for run in runs if run.get("ペース") == projected]
        score = 50 + style_points[projected].get(style, 0)
        reasons = [f"想定{pace_label}で{style or '脚質不明'}"]
        if similar:
            top3_rate = sum(0 < run["着順"] <= 3 for run in similar) / len(similar)
            score += (top3_rate - .30) * 24
            reasons.append(f"近似条件{len(similar)}走・3着内{top3_rate*100:.0f}%")
        else:
            reasons.append("近似条件の材料不足")
        if pace_runs:
            pace_top3 = sum(0 < run["着順"] <= 3 for run in pace_runs) / len(pace_runs)
            score += (pace_top3 - .30) * 16
            reasons.append(f"同ペース{len(pace_runs)}走")
        horse_lasts = [run["上がり3F"] for run in similar or runs if run.get("上がり3F") is not None]
        if horse_lasts and field_last_avg:
            last_avg = sum(horse_lasts) / len(horse_lasts)
            score += max(-8, min(8, (field_last_avg - last_avg) * 5))
            reasons.append(f"平均上がり{last_avg:.1f}秒")
        else:
            last_avg = None
        score = round(max(20, min(90, score)))
        matches.append({
            "馬番": horse.get("馬番"), "馬名": horse.get("馬名", ""), "脚質": style or "不明",
            "適合指数": score, "判定": "合いそう" if score >= 65 else "条件付き" if score >= 45 else "不向き寄り",
            "近似走数": len(similar), "平均上がり3F": round(last_avg, 1) if last_avg is not None else "",
            "根拠": " / ".join(reasons),
        })
    matches.sort(key=lambda item: item["適合指数"], reverse=True)
    return {
        "想定ペース": pace_label, "ペース記号": projected, "有利脚質": favorable,
        "逃げ候補数": escape, "先行候補を含む前方馬数": forward,
        "過去走サンプル数": len(all_runs), "ペース内訳": pace_counts,
        "平均前半3F": round(sum(first_laps) / len(first_laps), 1) if first_laps else "",
        "平均上がり3F": round(field_last_avg, 1) if field_last_avg is not None else "",
        "適合馬": matches,
    }


def merge_web_history(trend_analysis: dict, web_history: dict | None) -> dict:
    """Blend cached same-race/course trends into entrant compatibility without hiding the source."""
    trend = deepcopy(trend_analysis)
    if not web_history:
        return trend
    named = web_history.get("同名レース", {}); course = web_history.get("同条件レース", {})
    counts = {key: int(named.get("ペース内訳", {}).get(key, 0)) + int(course.get("ペース内訳", {}).get(key, 0)) * 2 for key in ("S", "M", "H")}
    if not any(counts.values()):
        trend["Web傾向"] = {"サンプル数": 0, "注意": "ラップを取得できる過去レースがありません"}
        return trend
    pace = max(counts, key=counts.get); pace_label = {"S": "スロー", "M": "平均", "H": "ハイ"}[pace]
    favorable = {"S": {"逃げ", "先行"}, "M": {"先行", "差し"}, "H": {"差し", "追込"}}[pace]
    opposed = {"S": {"追込"}, "M": set(), "H": {"逃げ"}}[pace]
    for item in trend.get("適合馬", []):
        style = item.get("脚質", "")
        adjustment = 7 if style in favorable else -6 if style in opposed else 0
        item["適合指数"] = max(20, min(90, int(item["適合指数"]) + adjustment))
        item["判定"] = "合いそう" if item["適合指数"] >= 65 else "条件付き" if item["適合指数"] >= 45 else "不向き寄り"
        item["根拠"] += f" / Web過去傾向は{pace_label}優勢"
    trend["適合馬"].sort(key=lambda item: item["適合指数"], reverse=True)
    trend["Web傾向"] = {
        "想定ペース": pace_label, "有利脚質": "・".join(sorted(favorable)), "加重ペース内訳": counts,
        "サンプル数": int(named.get("サンプル数", 0)) + int(course.get("サンプル数", 0)),
        "同名サンプル数": int(named.get("サンプル数", 0)), "同条件サンプル数": int(course.get("サンプル数", 0)),
    }
    return trend


def heuristic_evaluations(horses: list[dict[str, Any]], prediction_profile: dict | None = None, trend_analysis: dict | None = None) -> tuple[dict, dict, dict]:
    scores, comments, risks = {}, {}, {}
    prediction_profile = prediction_profile or {}
    learned = prediction_profile.get("adjustments", {})
    learned_count = int(prediction_profile.get("learning_samples", 0))
    fit_by_no = {str(item.get("馬番")): item for item in (trend_analysis or {}).get("適合馬", [])}
    for h in horses:
        no = str(h.get("馬番", "")); pop = _float(h.get("人気"), 9); odds = _float(h.get("単勝オッズ"), 20)
        recent = 5 if re.search(r"(?:1着|①|勝)", str(h.get("過去走テキスト", ""))) else 4 if pop <= 3 else 3
        value = 5 if odds >= 15 and pop <= 8 else 4 if odds >= 8 else 3 if odds >= 3 else 2
        score = {k: 3 for k in SCORE_KEYS}
        score.update({"近走評価": recent, "本命適性": 5 if pop == 1 else 4 if pop <= 3 else 3, "妙味": value, "騎手評価": 4 if pop <= 4 else 3})
        fit = fit_by_no.get(no, {})
        if fit:
            fit_index = int(fit.get("適合指数", 50))
            step = 1 if fit_index >= 65 else -1 if fit_index < 40 else 0
            score["展開利"] = max(1, min(5, score["展開利"] + step))
            if int(fit.get("近似走数", 0)) >= 2:
                score["距離・コース適性"] = max(1, min(5, score["距離・コース適性"] + step))
        if learned_count:
            for key in SCORE_KEYS:
                delta = float(learned.get(key, 0))
                step = int(math.copysign(math.floor(abs(delta) + .5), delta)) if delta else 0
                score[key] = max(1, min(5, score[key] + step))
        scores[no] = score
        learned_note = f"過去{learned_count}レースの手修正傾向を反映。" if learned_count else ""
        trend_note = f"傾向適合指数{fit.get('適合指数')}（{fit.get('判定')}）。" if fit else ""
        comments[no] = f"入力情報と人気・オッズを基にしたMVP仮評価です。{trend_note}{learned_note}適性や展開は手修正してください。"
        risks[no] = "材料不足の項目は3点（判断保留）です。直前気配とオッズを確認してください。"
    return scores, comments, risks


def _evaluation_schema() -> dict:
    return {"type": "object", "properties": {"horses": {"type": "array", "items": {"type": "object", "properties": {
        "horse_number": {"type": "string"}, "scores": {"type": "object", "properties": {k: {"type": "integer", "minimum": 1, "maximum": 5} for k in SCORE_KEYS}, "required": SCORE_KEYS, "additionalProperties": False},
        "ai_comment": {"type": "string"}, "risk_comment": {"type": "string"}}, "required": ["horse_number", "scores", "ai_comment", "risk_comment"], "additionalProperties": False}}}, "required": ["horses"], "additionalProperties": False}


def _evaluation_prompt(horses: list[dict], race_info: dict, prediction_policy: str = "", trend_analysis: dict | None = None) -> str:
    policy = prediction_policy.strip() or "未登録。一般的な基準で仮評価する。"
    return (
        "競馬予想の断定ではなく、ユーザーの検討を助ける仮評価を作成する。"
        "下記の予想方針を最優先し、資料に根拠がない項目は3点とする。"
        "父・母・母父などの血統情報は独立採点せず、距離・コース適性と馬場適性の根拠として反映する。"
        "各馬の根拠とリスクを日本語で簡潔に書く。\n\n"
        f"ユーザーの予想方針:\n{policy}\n\n"
        f"過去走ラップ・傾向分析:\n{json.dumps(trend_analysis or {}, ensure_ascii=False)}\n\n"
        + json.dumps({"race": race_info, "horses": horses}, ensure_ascii=False)
    )


def evaluate_with_openai(horses: list[dict], race_info: dict, api_key: str, model: str = "gpt-5.4-mini", prediction_policy: str = "", trend_analysis: dict | None = None) -> tuple[dict, dict, dict]:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    schema = _evaluation_schema()
    prompt = _evaluation_prompt(horses, race_info, prediction_policy, trend_analysis)
    response = client.responses.create(model=model, input=prompt, text={"format": {"type": "json_schema", "name": "horse_evaluations", "strict": True, "schema": schema}})
    data = json.loads(response.output_text)
    scores, comments, risks = {}, {}, {}
    for item in data["horses"]:
        no = str(item["horse_number"]); scores[no] = item["scores"]; comments[no] = item["ai_comment"]; risks[no] = item["risk_comment"]
    return scores, comments, risks


def available_ollama_models(base_url: str = "http://127.0.0.1:11434") -> list[str]:
    """Return locally installed Ollama models; an empty list means unavailable or no model."""
    from urllib.request import urlopen
    try:
        with urlopen(base_url.rstrip("/") + "/api/tags", timeout=1.2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [str(item.get("name", "")) for item in payload.get("models", []) if item.get("name")]
    except Exception:
        return []


def evaluate_with_ollama(horses: list[dict], race_info: dict, model: str, prediction_policy: str = "", base_url: str = "http://127.0.0.1:11434", trend_analysis: dict | None = None) -> tuple[dict, dict, dict]:
    """Evaluate locally through Ollama's JSON-schema chat API. No external API key is used."""
    from urllib.request import Request, urlopen
    schema = _evaluation_schema()
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": _evaluation_prompt(horses, race_info, prediction_policy, trend_analysis)}],
        "stream": False,
        "format": schema,
        "options": {"temperature": 0.1},
    }, ensure_ascii=False).encode("utf-8")
    request = Request(base_url.rstrip("/") + "/api/chat", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=240) as response:
        payload = json.loads(response.read().decode("utf-8"))
    data = json.loads(payload["message"]["content"])
    scores, comments, risks = {}, {}, {}
    for item in data["horses"]:
        no = str(item["horse_number"]); scores[no] = item["scores"]; comments[no] = item["ai_comment"]; risks[no] = item["risk_comment"]
    return scores, comments, risks


def load_prediction_profile(path: str = "data/prediction_profile.json") -> dict:
    profile_path = Path(path)
    default_result_learning = {"reviews": 0, "winner_rank_total": 0.0, "top3_coverage_total": 0.0, "category_signals": {k: 0.0 for k in SCORE_KEYS}, "lessons": [], "reviewed_races": []}
    default = {"policy": "", "adjustments": {k: 0.0 for k in SCORE_KEYS}, "learning_samples": 0, "result_learning": default_result_learning, "updated_at": ""}
    if not profile_path.exists(): return default
    try:
        loaded = json.loads(profile_path.read_text(encoding="utf-8"))
        result_learning = {**default_result_learning, **loaded.get("result_learning", {})}
        result_learning["category_signals"] = {**default_result_learning["category_signals"], **result_learning.get("category_signals", {})}
        return {**default, **loaded, "adjustments": {**default["adjustments"], **loaded.get("adjustments", {})}, "result_learning": result_learning}
    except Exception: return default


def save_prediction_profile(policy: str, path: str = "data/prediction_profile.json") -> Path:
    profile_path = Path(path); profile_path.parent.mkdir(parents=True, exist_ok=True)
    current = load_prediction_profile(path)
    current.update({"policy": policy.strip(), "updated_at": datetime.now().isoformat()})
    profile_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile_path


def learn_prediction_adjustments(ai_scores: dict, final_scores: dict, path: str = "data/prediction_profile.json") -> dict:
    """Accumulate the user's average score corrections without storing additional race data."""
    profile = load_prediction_profile(path)
    sample_diffs = {key: [] for key in SCORE_KEYS}
    for no, final in final_scores.items():
        original = ai_scores.get(str(no), {})
        for key in SCORE_KEYS:
            if key in original and key in final:
                sample_diffs[key].append(float(final[key]) - float(original[key]))
    if not any(sample_diffs.values()): return profile
    count = int(profile.get("learning_samples", 0)); new_count = count + 1
    for key, diffs in sample_diffs.items():
        if diffs:
            race_average = sum(diffs) / len(diffs)
            profile["adjustments"][key] = round((float(profile["adjustments"].get(key, 0)) * count + race_average) / new_count, 3)
    profile["learning_samples"] = new_count; profile["updated_at"] = datetime.now().isoformat()
    profile_path = Path(path); profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def prediction_policy_prompt(profile: dict) -> str:
    policy = str(profile.get("policy", "")).strip()
    samples = int(profile.get("learning_samples", 0))
    result_learning = profile.get("result_learning", {})
    reviews = int(result_learning.get("reviews", 0))
    sections = [policy] if policy else []
    trends = []
    for key in SCORE_KEYS:
        delta = float(profile.get("adjustments", {}).get(key, 0))
        if abs(delta) >= .1: trends.append(f"{key}:{delta:+.2f}点")
    if samples:
        sections.append("過去の手修正傾向（参考）: " + ("、".join(trends) if trends else "明確な偏りなし"))
    if reviews:
        avg_rank = float(result_learning.get("winner_rank_total", 0)) / reviews
        avg_coverage = float(result_learning.get("top3_coverage_total", 0)) / reviews * 100
        effective = sorted(result_learning.get("category_signals", {}).items(), key=lambda item: item[1], reverse=True)[:3]
        sections.append(f"結果振り返り{reviews}レース: 勝ち馬の事前平均順位{avg_rank:.1f}位、予想上位3頭と実際上位3頭の平均一致率{avg_coverage:.0f}%。相対的に結果と関連した評価軸: " + "、".join(k for k, _ in effective))
        lessons = result_learning.get("lessons", [])[-6:]
        if lessons: sections.append("過去の振り返りメモ:\n- " + "\n- ".join(str(x) for x in lessons))
    return "\n".join(sections)


def parse_finish_order(text: str) -> list[str]:
    """Parse horse numbers from '1着 7番' lines or a compact '7-8-6' order."""
    placed = [(int(place), str(int(number))) for place, number in re.findall(r"(\d{1,2})\s*着\s*[:：]?\s*(\d{1,2})\s*(?:番)?", text)]
    if placed:
        return [number for _, number in sorted(placed) if 1 <= int(number) <= 18]
    line_numbers = []
    for line in text.splitlines():
        match = re.match(r"\s*(\d{1,2})(?:\s|番|$)", line)
        if match and 1 <= int(match.group(1)) <= 18: line_numbers.append(str(int(match.group(1))))
    if len(line_numbers) >= 2: return list(dict.fromkeys(line_numbers))
    compact = [str(int(v)) for v in re.findall(r"\d{1,2}", text) if 1 <= int(v) <= 18]
    return list(dict.fromkeys(compact))


def learn_from_race_result(state: dict, feedback: dict, path: str = "data/prediction_profile.json") -> dict:
    """Store aggregate result feedback for future prompts; each race is counted once."""
    actual = parse_finish_order(str(feedback.get("確定着順", "")))
    if not actual: raise ValueError("確定着順から馬番を読み取れませんでした")
    info = state.get("race_info", {})
    race_key = "|".join(str(info.get(k, "")) for k in ("日付", "競馬場", "レース番号", "レース名")) or datetime.now().isoformat()
    profile = load_prediction_profile(path); learning = profile["result_learning"]
    if race_key in learning.get("reviewed_races", []): return profile
    predicted = [str(row.get("馬番")) for row in state.get("score_results", [])]
    winner_rank = predicted.index(actual[0]) + 1 if actual[0] in predicted else len(predicted) + 1
    top3_coverage = len(set(predicted[:3]) & set(actual[:3])) / max(1, min(3, len(actual)))
    reviews = int(learning.get("reviews", 0)); new_reviews = reviews + 1
    learning["reviews"] = new_reviews
    learning["winner_rank_total"] = float(learning.get("winner_rank_total", 0)) + winner_rank
    learning["top3_coverage_total"] = float(learning.get("top3_coverage_total", 0)) + top3_coverage
    top3 = set(actual[:3]); final_scores = state.get("final_scores", {})
    for key in SCORE_KEYS:
        all_values = [float(scores.get(key, 3)) for scores in final_scores.values()]
        hit_values = [float(final_scores[no].get(key, 3)) for no in top3 if no in final_scores]
        signal = (sum(hit_values) / len(hit_values) - sum(all_values) / len(all_values)) if hit_values and all_values else 0
        old = float(learning["category_signals"].get(key, 0))
        learning["category_signals"][key] = round((old * reviews + signal) / new_reviews, 3)
    lesson = str(feedback.get("次回への学び", "")).strip()
    missed = str(feedback.get("外れた見解", "")).strip()
    if missed: learning["lessons"].append("見誤り: " + missed)
    if lesson: learning["lessons"].append("次回: " + lesson)
    learning["lessons"] = learning["lessons"][-20:]
    learning.setdefault("reviewed_races", []).append(race_key); learning["reviewed_races"] = learning["reviewed_races"][-100:]
    profile["result_learning"] = learning; profile["updated_at"] = datetime.now().isoformat()
    profile_path = Path(path); profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def learn_from_result_history(states: list[dict], path: str = "data/prediction_profile.json") -> tuple[dict, dict]:
    """Import result-bearing prediction snapshots and aggregate them without double counting."""
    before = int(load_prediction_profile(path)["result_learning"].get("reviews", 0))
    processed, duplicates, skipped, errors = 0, 0, 0, []
    for index, state in enumerate(states, 1):
        if not isinstance(state, dict):
            skipped += 1
            continue
        feedback = state.get("result_feedback") or {}
        if not state.get("score_results") or not state.get("final_scores") or not parse_finish_order(str(feedback.get("確定着順", ""))):
            skipped += 1
            continue
        try:
            reviews_before = int(load_prediction_profile(path)["result_learning"].get("reviews", 0))
            profile = learn_from_race_result(state, feedback, path)
            reviews_after = int(profile["result_learning"].get("reviews", 0))
            if reviews_after > reviews_before: processed += 1
            else: duplicates += 1
        except Exception as exc:
            errors.append(f"{index}件目: {exc}")
    profile = load_prediction_profile(path)
    after = int(profile["result_learning"].get("reviews", 0))
    return profile, {"新規反映": processed, "重複": duplicates, "結果不足": skipped, "エラー": errors, "累計": after, "開始時": before}


def extract_media_with_openai(files: list[tuple[str, str, bytes]], api_key: str, model: str = "gpt-5.4-mini", high_accuracy: bool = True, crop_profile: dict | None = None) -> tuple[dict, list[dict], str, list[str]]:
    """Extract race data with visual preprocessing, OCR, structuring, and validation."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    visuals, local_text, prep_notes = _prepare_visual_inputs(files, crop_profile)
    ocr_content: list[dict[str, Any]] = [{
        "type": "input_text",
        "text": (
            "これは中央競馬のレース資料です。OCR担当として、見える文字を正確に転記してください。"
            "特にレース名、開催場、R番号、条件、発走時刻と、出馬表の各行を馬番ごとに保持してください。"
            "表は『馬番 | 枠番 | 馬名 | 性齢 | 斤量 | 騎手 | 厩舎 | 人気 | 単勝オッズ』のように行単位で記述し、"
            "過去走やコメントも馬名との対応を崩さないでください。読めない箇所は[不鮮明]とし、推測しないでください。"
        ),
    }]
    if local_text:
        ocr_content.append({"type": "input_text", "text": "PDF内の抽出可能テキスト（視覚情報と照合してください）:\n" + local_text[:60000]})
    # Keep original PDFs as context, then add high-resolution page/screenshot tiles.
    for name, mime, data in files[:3]:
        if mime == "application/pdf" or name.lower().endswith(".pdf"):
            encoded = base64.b64encode(data).decode("ascii")
            ocr_content.append({"type": "input_file", "filename": name, "file_data": f"data:application/pdf;base64,{encoded}"})
    for name, mime, data in visuals[:14]:
        encoded = base64.b64encode(data).decode("ascii")
        ocr_content.append({"type": "input_image", "image_url": f"data:{mime};base64,{encoded}", "detail": "high"})
    if high_accuracy:
        ocr_response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": ocr_content}],
            max_output_tokens=24000,
        )
        transcript = ocr_response.output_text
        structure_content = [{
            "type": "input_text",
            "text": (
                "次のOCR結果を中央競馬のレースデータとして構造化してください。推測は禁止です。"
                "同じ馬の情報が複数箇所にある場合だけ統合し、馬番・馬名の対応を最優先してください。"
                "距離は数字、頭数も数字、芝/ダートは『芝』か『ダート』で記述してください。\n\nOCR結果:\n"
                + transcript[:90000]
            ),
        }]
    else:
        transcript = local_text
        structure_content = ocr_content
    race_fields = ["日付", "競馬場", "レース番号", "レース名", "芝/ダート", "距離", "馬場", "天候", "頭数", "発走時刻"]
    horse_fields = HORSE_COLUMNS
    schema = {
        "type": "object",
        "properties": {
            "race_info": {"type": "object", "properties": {k: {"type": "string"} for k in race_fields}, "required": race_fields, "additionalProperties": False},
            "horses": {"type": "array", "items": {"type": "object", "properties": {k: {"type": "string"} for k in horse_fields}, "required": horse_fields, "additionalProperties": False}},
            "extracted_text": {"type": "string"},
        },
        "required": ["race_info", "horses", "extracted_text"],
        "additionalProperties": False,
    }
    response = client.responses.create(
        model=model,
        input=[{"role": "user", "content": structure_content}],
        text={"format": {"type": "json_schema", "name": "race_document_extraction", "strict": True, "schema": schema}},
        max_output_tokens=20000,
    )
    data = json.loads(response.output_text)
    horses = [_normalize_horse(h) for h in data["horses"]]
    extracted_text = transcript or data["extracted_text"]
    warnings = prep_notes + _validate_extraction(data["race_info"], horses)
    return data["race_info"], horses, extracted_text, warnings


def _prepare_visual_inputs(files: list[tuple[str, str, bytes]], crop_profile: dict | None = None) -> tuple[list[tuple[str, str, bytes]], str, list[str]]:
    """Render PDFs and enhance/split images so small racing-table text remains legible."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    from pypdf import PdfReader
    import fitz

    visuals: list[tuple[str, str, bytes]] = []
    texts: list[str] = []
    notes: list[str] = []

    def emit_image(name: str, image: Image.Image):
        image = ImageOps.exif_transpose(image).convert("RGB")
        if image.width < 1800:
            scale = min(2.5, 1800 / max(1, image.width))
            image = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
        image = ImageOps.autocontrast(image, cutoff=1)
        image = ImageEnhance.Contrast(image).enhance(1.12)
        image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=135, threshold=3))
        # Include an overview and overlapping vertical tiles for dense/tall tables.
        candidates = [("full", image)]
        if image.height > image.width * 1.25:
            tile_h = int(image.width * 1.15)
            stride = int(tile_h * .82)
            candidates = []
            top = 0; idx = 1
            while top < image.height and len(candidates) < 4:
                bottom = min(image.height, top + tile_h)
                candidates.append((f"part{idx}", image.crop((0, top, image.width, bottom))))
                if bottom == image.height: break
                top += stride; idx += 1
        for suffix, candidate in candidates:
            out = BytesIO()
            candidate.save(out, "JPEG", quality=92, optimize=True)
            visuals.append((f"{name}_{suffix}.jpg", "image/jpeg", out.getvalue()))

    def add_image(name: str, image: Image.Image):
        image = ImageOps.exif_transpose(image).convert("RGB")
        if not crop_profile:
            emit_image(name, image)
            return
        for zone_name, label in (("race_header", "レース情報"), ("horse_table", "出馬表")):
            zone = crop_profile.get(zone_name, DEFAULT_LAYOUT_PROFILE[zone_name])
            x1, y1, x2, y2 = [max(0.0, min(1.0, float(v))) for v in zone]
            if x2 <= x1 or y2 <= y1:
                notes.append(f"{label}の解析範囲が無効です")
                continue
            box = (int(image.width*x1), int(image.height*y1), max(int(image.width*x2), 1), max(int(image.height*y2), 1))
            emit_image(f"{name}_{zone_name}_{label}", image.crop(box))

    for name, mime, data in files[:6]:
        try:
            if mime == "application/pdf" or name.lower().endswith(".pdf"):
                reader = PdfReader(BytesIO(data))
                texts.extend(page.extract_text() or "" for page in reader.pages[:20])
                doc = fitz.open(stream=data, filetype="pdf")
                if len(doc) > 8: notes.append(f"{name}: 先頭8ページを画像解析しました（全{len(doc)}ページ）")
                for page_index in range(min(8, len(doc))):
                    page_no = page_index + 1
                    page = doc.load_page(page_index)
                    pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False)
                    add_image(f"{name}_p{page_no}", Image.open(BytesIO(pix.tobytes("png"))))
                doc.close()
            else:
                add_image(name, Image.open(BytesIO(data)))
        except Exception as exc:
            notes.append(f"{name}: 前処理の一部に失敗しました（{exc}）")
    if crop_profile:
        notes.append(f"固定範囲テンプレート「{crop_profile.get('name', '名称未設定')}」を適用しました")
    return visuals[:14], "\n".join(texts).strip(), notes


def save_layout_profile(name: str, race_header: list[float], horse_table: list[float], path: str = "data/layout_profiles.json") -> dict:
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    profiles = load_layout_profiles(path)
    profile = {"name": name.strip() or "マイテンプレート", "race_header": race_header, "horse_table": horse_table}
    profiles[profile["name"]] = profile
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, target)
    return profile


def load_layout_profiles(path: str = "data/layout_profiles.json") -> dict[str, dict]:
    profiles = {DEFAULT_LAYOUT_PROFILE["name"]: deepcopy(DEFAULT_LAYOUT_PROFILE)}
    target = Path(path)
    if target.exists():
        try:
            saved = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(saved, dict): profiles.update(saved)
        except (OSError, json.JSONDecodeError):
            pass
    return profiles


def render_layout_preview(name: str, mime: str, data: bytes, profile: dict) -> bytes:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    import fitz
    if mime == "application/pdf" or name.lower().endswith(".pdf"):
        doc = fitz.open(stream=data, filetype="pdf")
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
        image = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
        doc.close()
    else:
        image = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    colors = {"race_header": (220, 54, 54, 60), "horse_table": (0, 130, 84, 55)}
    outlines = {"race_header": (220, 54, 54, 255), "horse_table": (0, 130, 84, 255)}
    for zone_name in ("race_header", "horse_table"):
        x1, y1, x2, y2 = profile.get(zone_name, DEFAULT_LAYOUT_PROFILE[zone_name])
        box = (int(image.width*x1), int(image.height*y1), int(image.width*x2), int(image.height*y2))
        draw.rectangle(box, fill=colors[zone_name], outline=outlines[zone_name], width=max(3, image.width//400))
    if image.width > 1200:
        ratio = 1200/image.width
        image = image.resize((1200, int(image.height*ratio)), Image.Resampling.LANCZOS)
    out = BytesIO(); image.save(out, "PNG"); return out.getvalue()


def get_keychain_api_key() -> str:
    try:
        result = subprocess.run(["security", "find-generic-password", "-a", getpass.getuser(), "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def save_keychain_api_key(api_key: str) -> bool:
    if not api_key.strip(): return False
    try:
        result = subprocess.run(["security", "add-generic-password", "-U", "-a", getpass.getuser(), "-s", KEYCHAIN_SERVICE, "-w", api_key.strip()], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def delete_keychain_api_key() -> bool:
    try:
        result = subprocess.run(["security", "delete-generic-password", "-a", getpass.getuser(), "-s", KEYCHAIN_SERVICE], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def save_local_api_key(api_key: str, path: str = ".streamlit/secrets.toml") -> bool:
    if not api_key.strip(): return False
    try:
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
        # JSON string escaping is compatible with TOML basic strings here.
        target.write_text(f"OPENAI_API_KEY = {json.dumps(api_key.strip())}\n", encoding="utf-8")
        os.chmod(target, 0o600)
        return True
    except OSError:
        return False


def delete_local_api_key(path: str = ".streamlit/secrets.toml") -> bool:
    try:
        target = Path(path)
        if target.exists(): target.unlink()
        return True
    except OSError:
        return False


def _validate_extraction(info: dict, horses: list[dict]) -> list[str]:
    warnings = []
    expected = int(re.sub(r"\D", "", str(info.get("頭数", ""))) or 0)
    actual = len(horses)
    numbers = [h.get("馬番") for h in horses if isinstance(h.get("馬番"), int)]
    if expected and actual != expected:
        warnings.append(f"頭数不一致: 資料は{expected}頭、抽出結果は{actual}頭です")
    if len(numbers) != len(set(numbers)):
        warnings.append("馬番の重複があります")
    if numbers and expected:
        missing = sorted(set(range(1, expected + 1)) - set(numbers))
        if missing: warnings.append("未抽出の可能性がある馬番: " + ", ".join(map(str, missing)))
    unnamed = [str(h.get("馬番", "?")) for h in horses if not str(h.get("馬名", "")).strip()]
    if unnamed: warnings.append("馬名が読めなかった馬番: " + ", ".join(unnamed))
    if not horses: warnings.append("出走馬を抽出できませんでした。画像の解像度や対象ページを確認してください")
    return warnings


def extract_text_pdfs(files: list[tuple[str, str, bytes]]) -> tuple[dict, list[dict], str]:
    """Local fallback for PDFs that contain selectable text."""
    from pypdf import PdfReader
    chunks = []
    for name, mime, data in files:
        if mime == "application/pdf" or name.lower().endswith(".pdf"):
            reader = PdfReader(BytesIO(data))
            chunks.extend(page.extract_text() or "" for page in reader.pages[:20])
    text = "\n".join(chunks).strip()
    if not text:
        return {}, [], ""
    raw = {"レース情報": text, "出馬表": text, "過去走情報": text, "コメント": text, "任意メモ": ""}
    info, horses = parse_inputs(raw)
    return info, horses, text


def extract_screenshot_with_macos_vision(data: bytes, filename: str = "screenshot.png", mime: str = "image/png") -> tuple[dict, list[dict], str, list[str]]:
    """Free on-device OCR for the fixed netkeiba-style race table layout."""
    if mime == "application/pdf" or filename.lower().endswith(".pdf"):
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        if not len(doc): raise ValueError("PDFにページがありません")
        pix = doc.load_page(0).get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False)
        data = pix.tobytes("png"); doc.close()
    items, width, height = _macos_vision_items(data)
    info, horses, warnings = _parse_fixed_race_ocr(items)
    expected = int(re.sub(r"\D", "", str(info.get("頭数", ""))) or 0)
    if expected and len(horses) < expected:
        recovered = _recover_fixed_layout_rows(data, set(range(1, expected + 1)) - {int(h["馬番"]) for h in horses if str(h.get("馬番", "")).isdigit()})
        if recovered:
            by_number = {int(h["馬番"]): h for h in horses}
            by_number.update({int(h["馬番"]): h for h in recovered})
            horses = [by_number[n] for n in sorted(by_number)]
            warnings = [w for w in warnings if "頭をローカル抽出しました" not in w]
            if info.get("レース名"): warnings.append(f"{info['レース名']}: {len(horses)}頭をローカル抽出しました")
            warnings.append("欠けた行を個別に再読み取りしました: " + ", ".join(str(h["馬番"]) for h in recovered))
    transcript = "\n".join(item["text"] for item in sorted(items, key=lambda x: (-x["y"], x["x"])))
    warnings.extend(_validate_extraction(info, horses))
    if not horses:
        raise ValueError("固定レイアウトから出走馬を抽出できませんでした。添付例と同じ出馬表画面・倍率でキャプチャしてください。")
    return info, horses, transcript, list(dict.fromkeys(warnings))


def extract_netkeiba_newspaper_pdf(data: bytes) -> tuple[dict, list[dict], dict, str, list[str]]:
    """Parse the fixed one-page netkeiba vertical newspaper from PDF text coordinates."""
    import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    if not len(doc): raise ValueError("PDFにページがありません")
    page = doc.load_page(0)
    words = page.get_text("words")
    full_text = page.get_text("text")

    def norm(text): return unicodedata.normalize("NFKC", str(text)).strip()
    header_words = [w for w in words if w[1] < 55]
    header_text = " ".join(norm(w[4]) for w in sorted(header_words, key=lambda w: (w[1], w[0])))
    date_m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", header_text)
    venue_m = re.search(r"(東京|中山|阪神|京都|中京|札幌|函館|福島|新潟|小倉)", header_text)
    race_no_m = re.search(r"(?:^|\s)(\d{1,2})(?:\s|$)", " ".join(norm(w[4]) for w in header_words if w[0] < 35))
    race_title_word = next((norm(w[4]) for w in words if 20 < w[1] < 35 and 35 < w[0] < 190 and re.search(r"(?:S|賞|ステークス|カップ|記念|特別|G[ⅠIV]+)", norm(w[4]), re.I)), "")
    race_name = re.sub(r"G(?:III|II|I)$", "", race_title_word, flags=re.I)
    surface_m = re.search(r"(芝|ダート|ダ)\s*(\d{3,4})m?", header_text)
    start_m = re.search(r"(?:発走時刻\s*:?|発走)\s*(\d{1,2}:\d{2})", header_text)
    count_m = re.search(r"(\d{1,2})頭", header_text)
    meeting_m = re.search(r"(\d+)回(?:東京|中山|阪神|京都|中京|札幌|函館|福島|新潟|小倉)(\d+)日目?", header_text)
    info = {k: "" for k in ["日付", "競馬場", "開催回", "開催日", "レース番号", "レース名", "芝/ダート", "距離", "馬場", "天候", "頭数", "発走時刻"]}
    info.update({
        "日付": f"{date_m.group(1)}-{int(date_m.group(2)):02d}-{int(date_m.group(3)):02d}" if date_m else "",
        "競馬場": venue_m.group(1) if venue_m else "",
        "開催回": meeting_m.group(1) if meeting_m else "",
        "開催日": meeting_m.group(2) if meeting_m else "",
        "レース番号": race_no_m.group(1) if race_no_m else "",
        "レース名": race_name,
        "芝/ダート": "ダート" if surface_m and surface_m.group(1) in {"ダ", "ダート"} else "芝" if surface_m else "",
        "距離": surface_m.group(2) if surface_m else "",
        "頭数": count_m.group(1) if count_m else "",
        "発走時刻": start_m.group(1) if start_m else "",
    })

    number_centers: dict[int, float] = {}
    for w in words:
        text = norm(w[4])
        if 64 <= w[1] <= 82 and re.fullmatch(r"\d{1,2}", text):
            number = int(text)
            if 1 <= number <= 18:
                number_centers[number] = (w[0] + w[2]) / 2
    field_size = int(info["頭数"]) if str(info.get("頭数", "")).isdigit() else 0
    if not field_size and number_centers:
        field_size = max(number_centers)
    field_size = max(1, min(18, field_size or 16))

    def column_left(number: int) -> float:
        if number in number_centers:
            return number_centers[number] - 14.5
        return 7 + (field_size-number)*30.24

    def column_words(number: int, y0: float, y1: float, rel_x0: float = 0, rel_x1: float = 29):
        left = column_left(number)
        return [w for w in words if left+rel_x0 <= (w[0]+w[2])/2 < left+rel_x1 and y0 <= w[1] < y1]

    def joined(number: int, y0: float, y1: float, rel_x0: float = 0, rel_x1: float = 29):
        ws = column_words(number, y0, y1, rel_x0, rel_x1)
        return "".join(norm(w[4]) for w in sorted(ws, key=lambda w: (w[1], w[0])))

    def joined_by_size(number: int, y0: float, y1: float, rel_x0: float, rel_x1: float, min_height: float | None = None, max_height: float | None = None):
        ws = []
        for w in column_words(number, y0, y1, rel_x0, rel_x1):
            height = w[3] - w[1]
            if min_height is not None and height < min_height:
                continue
            if max_height is not None and height > max_height:
                continue
            token = norm(w[4])
            if token in {"✓", "☆", "--"}:
                continue
            ws.append(w)
        return "".join(norm(w[4]) for w in sorted(ws, key=lambda w: (w[1], w[0])))

    date_rows = sorted(w[1] for w in words if 250 <= w[1] <= 700 and re.search(r"\d{2}/\d{2}", norm(w[4])))
    clusters: list[list[float]] = []
    for y in date_rows:
        if not clusters or abs(y - clusters[-1][-1]) > 12:
            clusters.append([y])
        else:
            clusters[-1].append(y)
    section_starts = [sum(cluster) / len(cluster) for cluster in clusters[:5]] or [315.4, 394.6, 473.7, 552.9, 632.0]
    style_map = {"逃": "逃げ", "先": "先行", "差": "差し", "追": "追込"}
    horses = []
    for number in range(1, field_size + 1):
        name = joined_by_size(number, 75, 146, 8, 22, min_height=7.5)
        # PDFの縦3列は左から「母 / 馬名 / 父」。母父はその下の横書き欄。
        dam = joined_by_size(number, 78, 124, 0, 8, max_height=7.4)
        sire = joined_by_size(number, 78, 124, 24, 30, max_height=7.4)
        dam_sire = joined(number, 172, 182, 6, 24)
        style_char = joined(number, 148, 157, 20, 29)[:1]
        sex_text = joined(number, 183, 190, 0, 15)
        weight_text = joined(number, 191, 198)
        jockey_text = joined(number, 198, 205)
        odds_text = joined(number, 225, 231)
        pop_text = joined(number, 231, 238)
        stable_text = joined(number, 241, 248)
        frame_text = joined(number, 58, 66, 10, 20)
        runs, position_sets = [], []
        for start in section_starts:
            section = column_words(number, start-.5, start+78.5)
            section_text = " ".join(norm(w[4]) for w in sorted(section, key=lambda w: (w[1], w[0])))
            if not re.search(r"\d{2}/\d{2}", section_text): continue
            corner_words = [norm(w[4]) for w in section if start+46 <= w[1] <= start+58 and re.fullmatch(r"\d{1,2}", norm(w[4]))]
            corners = [int(v) for v in corner_words if 1 <= int(v) <= 18]
            if corners: position_sets.append(corners)
            runs.append(section_text)
        explicit_style = style_map.get(style_char, "")
        inferred_style, style_reason = infer_running_style(position_sets)
        style = explicit_style or inferred_style
        sex_m = re.search(r"[牡牝セ]\d+", sex_text)
        weight_m = re.search(r"\d{2}(?:\.\d)?", weight_text)
        odds_m = re.search(r"\d+(?:\.\d+)?", odds_text)
        pop_m = re.search(r"(\d{1,2})人気", pop_text)
        stable = re.sub(r"^(美浦|栗東)", "", stable_text)
        style_source = f"PDF記載:{explicit_style}" if explicit_style else style_reason
        horse = {k: "" for k in HORSE_COLUMNS}
        horse.update({
            "馬番": number,
            "枠番": int(frame_text) if frame_text.isdigit() else "",
            "馬名": name,
            "性齢": sex_m.group() if sex_m else "",
            "斤量": weight_m.group() if weight_m else "",
            "騎手": re.sub(r"^替", "", jockey_text),
            "厩舎": stable,
            "人気": int(pop_m.group(1)) if pop_m else "",
            "単勝オッズ": float(odds_m.group()) if odds_m else "",
            "脚質": style,
            "父": sire,
            "母": dam,
            "母父": dam_sire,
            "過去走テキスト": " / ".join(runs),
            "コメント": f"脚質根拠: {style_source}",
        })
        if name: horses.append(horse)

    summary_text = "".join(norm(w[4]) for w in sorted([w for w in words if 200 <= w[0] <= 460 and 54 <= w[1] <= 87], key=lambda w: (w[1], w[0])))
    pace_words = [norm(w[4]) for w in words if 320 <= w[0] <= 500 and 12 <= w[1] <= 52]
    summary = {
        "レース総評": summary_text,
        "展開予想": "PDF展開予想: " + " ".join(pace_words),
        "有利脚質": "",
        "波乱度": "中",
        "買い判断": "",
        "注意点": "PDF記載情報と通過順位を基に整理。最終判断はユーザー自身で行ってください。",
    }
    warnings = ["netkeiba競馬新聞PDF専用パーサーで文字座標を直接解析しました"]
    warnings.extend(_validate_extraction(info, horses))
    if any(len(str(h.get("母父", ""))) >= 10 for h in horses):
        warnings.append("母父名はPDF表示幅により省略されている場合があります")
    doc.close()
    return info, horses, summary, full_text, warnings


def infer_running_style(position_sets: list[list[int]]) -> tuple[str, str]:
    """Infer a broad style from recent corner positions when no explicit label exists."""
    early = [positions[0] for positions in position_sets if positions]
    if not early: return "", "通過順位不足"
    avg = sum(early) / len(early)
    lead_rate = sum(1 for p in early if p <= 2) / len(early)
    if lead_rate >= .5 or avg <= 2.0: style = "逃げ"
    elif avg <= 5.0: style = "先行"
    elif avg <= 10.0: style = "差し"
    else: style = "追込"
    return style, f"直近{len(early)}走の序盤平均位置{avg:.1f}番手"


def _macos_vision_items(data: bytes) -> tuple[list[dict], int, int]:
    from PIL import Image
    original_items, width, height = _macos_vision_single(data)
    # A dedicated table crop removes the surrounding navigation/footer and
    # recovers rows that full-page OCR may skip.
    table_left, table_top, table_right, table_bottom = .065, .25, .68, .94
    crop = Image.open(BytesIO(data)).convert("RGB")
    crop = crop.crop((int(crop.width*table_left), int(crop.height*table_top), int(crop.width*table_right), int(crop.height*table_bottom)))
    crop_bytes = BytesIO(); crop.save(crop_bytes, "PNG")
    cropped_items, _, _ = _macos_vision_single(crop_bytes.getvalue())
    mapped_cropped_items = []
    for item in cropped_items:
        mapped = dict(item)
        mapped["x"] = table_left + item["x"] * (table_right-table_left)
        mapped["y"] = (1-table_bottom) + item["y"] * (table_bottom-table_top)
        mapped["width"] = item["width"] * (table_right-table_left)
        mapped["height"] = item["height"] * (table_bottom-table_top)
        mapped_cropped_items.append(mapped)
    merged = list(original_items)
    for item in mapped_cropped_items:
        duplicate = any(existing["text"] == item["text"] and abs(existing["x"]-item["x"]) < .012 and abs(existing["y"]-item["y"]) < .012 for existing in merged)
        if not duplicate: merged.append(item)
    return merged, width, height


def _macos_vision_single(data: bytes) -> tuple[list[dict], int, int]:
    try:
        from Foundation import NSData
        from Quartz import CGImageSourceCreateWithData, CGImageSourceCreateImageAtIndex, CGImageGetWidth, CGImageGetHeight
        import Vision
    except ImportError as exc:
        raise RuntimeError("MacローカルOCRが未導入です。requirements.txtを再インストールしてください。") from exc
    nsdata = NSData.dataWithBytes_length_(data, len(data))
    source = CGImageSourceCreateWithData(nsdata, None)
    image = CGImageSourceCreateImageAtIndex(source, 0, None) if source else None
    if image is None: raise ValueError("画像を開けませんでした")
    request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(None)
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(["ja-JP", "en-US"])
    request.setUsesLanguageCorrection_(True)
    request.setMinimumTextHeight_(0.006)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, {})
    success, error = handler.performRequests_error_([request], None)
    if not success: raise RuntimeError(f"Mac Vision OCRに失敗しました: {error or '原因不明'}")
    result = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates: continue
        candidate = candidates[0]; box = observation.boundingBox()
        result.append({"text": str(candidate.string()), "confidence": float(candidate.confidence()), "x": float(box.origin.x), "y": float(box.origin.y), "width": float(box.size.width), "height": float(box.size.height)})
    return result, int(CGImageGetWidth(image)), int(CGImageGetHeight(image))


def _recover_fixed_layout_rows(data: bytes, missing_numbers: set[int]) -> list[dict]:
    from PIL import Image
    image = Image.open(BytesIO(data)).convert("RGB")
    recovered = []
    for number in sorted(missing_numbers):
        # Row centers in the fixed desktop capture run from y=.646 downward.
        center_y = .646 - (number - 1) * .037
        top = int(image.height * (1 - (center_y + .023)))
        bottom = int(image.height * (1 - (center_y - .023)))
        left, right = int(image.width*.09), int(image.width*.67)
        crop = image.crop((left, max(0, top), right, min(image.height, bottom)))
        out = BytesIO(); crop.save(out, "PNG")
        try: items, _, _ = _macos_vision_single(out.getvalue())
        except Exception: continue
        name_candidates = [x for x in items if x["x"] < .34 and len(x["text"].strip()) >= 2 and not re.search(r"(?:[牝牡セ]\s*\d|\d+\.\d|切替)", x["text"])]
        if not name_candidates: continue
        name = max(name_candidates, key=lambda x: x["confidence"] + min(len(x["text"]), 12)*.01)["text"]
        def pick(x1, x2, pattern=None):
            candidates = [x for x in items if x1 <= x["x"] < x2 and (pattern is None or re.search(pattern, x["text"]))]
            return max(candidates, key=lambda x: x["confidence"])["text"].strip() if candidates else ""
        combined_parts = [x["text"].strip() for x in sorted(items, key=lambda x: x["x"]) if .32 <= x["x"] < .58]
        combined = " ".join(dict.fromkeys(combined_parts))
        combined = re.sub(r"^¥(?=\d)", "牝", combined)
        sex_match = re.search(r"[牡牝セ]\s*\d+", combined)
        weight_match = re.search(r"\d{2}(?:\.\d)?", combined)
        sex_age = sex_match.group() if sex_match else ""
        weight = weight_match.group() if weight_match else ""
        jockey = re.sub(r"^(?:[牡牝セ]\s*\d+\s*)?(?:\d{2}(?:\.\d)?\s*)?", "", combined).strip()
        stable = re.sub(r"^(?:美浦|栗東)\s*", "", pick(.56, .82))
        odds = pick(.80, .92, r"\d+\.\d")
        popularity = pick(.90, 1.0, r"^\d{1,2}$")
        horse = {k: "" for k in HORSE_COLUMNS}
        horse.update({"馬番": number, "馬名": re.sub(r"^[^0-9A-Za-zぁ-んァ-ヶ一-龠]+", "", name), "性齢": sex_age, "斤量": weight, "騎手": jockey, "厩舎": stable, "単勝オッズ": float(odds) if re.fullmatch(r"\d+\.\d", odds) else "", "人気": int(popularity) if popularity.isdigit() else ""})
        recovered.append(horse)
    return recovered


def _parse_fixed_race_ocr(items: list[dict]) -> tuple[dict, list[dict], list[str]]:
    """Map OCR coordinates from the supplied netkeiba desktop screenshot to fields."""
    warnings = ["MacローカルOCR（固定出馬表レイアウト）で解析しました"]
    top = [x for x in items if x["y"] >= .86]
    all_top = " ".join(x["text"] for x in sorted(top, key=lambda x: (-x["y"], x["x"])))
    race_no = next((re.sub(r"\D", "", x["text"]) for x in top if re.fullmatch(r"\s*\d{1,2}\s*R\s*", x["text"], re.I)), "")
    race_name = next((x["text"].strip() for x in top if .05 <= x["x"] <= .45 and re.search(r"(?:S|賞|ステークス|カップ|記念|特別)$", x["text"].strip(), re.I)), "")
    meta = next((x["text"] for x in top if re.search(r"発走.*(?:芝|ダート|ダ)\s*\d{3,4}", x["text"])), all_top)
    venue_match = re.search(r"(東京|中山|阪神|京都|中京|札幌|函館|福島|新潟|小倉)", all_top)
    surface_match = re.search(r"(芝|ダート|ダ)\s*(\d{3,4})", meta)
    start_match = re.search(r"(\d{1,2}:\d{2})\s*発走", meta)
    weather_match = re.search(r"天候\s*[:：]\s*([晴曇雨雪小]+)", meta)
    track_match = re.search(r"馬場\s*[:：]\s*(良|稍|稍重|重|不良)", meta)
    count_match = re.search(r"(\d{1,2})\s*頭", all_top)
    info = {k: "" for k in ["日付", "競馬場", "レース番号", "レース名", "芝/ダート", "距離", "馬場", "天候", "頭数", "発走時刻"]}
    info.update({
        "競馬場": venue_match.group(1) if venue_match else "",
        "レース番号": race_no,
        "レース名": race_name,
        "芝/ダート": ("ダート" if surface_match and surface_match.group(1) in {"ダ", "ダート"} else "芝" if surface_match else ""),
        "距離": surface_match.group(2) if surface_match else "",
        "馬場": ("稍重" if track_match and track_match.group(1) == "稍" else track_match.group(1) if track_match else ""),
        "天候": weather_match.group(1)[0] if weather_match else "",
        "頭数": count_match.group(1) if count_match else "",
        "発走時刻": start_match.group(1) if start_match else "",
    })
    # Horse names occupy a stable column around x=0.11 in this desktop layout.
    excluded = {"馬名", "出走馬", "競馬新聞", "専門紙", "タイム指数", "持ちタイム", "パドック", "血統", "対戦表"}
    name_items = [x for x in items if .095 <= x["x"] <= .27 and .075 <= x["y"] <= .67 and x["text"] not in excluded and len(x["text"].strip()) >= 2 and not re.fullmatch(r"[\d.]+", x["text"])]
    name_items = sorted(name_items, key=lambda x: x["y"], reverse=True)
    # Remove controls/headings accidentally falling inside the name column.
    name_items = [x for x in name_items if not re.search(r"(?:馬柱|メモ|切替|オッズ|予想|登録)", x["text"])]
    name_clusters: list[list[dict]] = []
    for item in name_items:
        cluster = next((c for c in name_clusters if abs(c[0]["y"] - item["y"]) < .018), None)
        if cluster is None: name_clusters.append([item])
        else: cluster.append(item)
    name_items = [max(cluster, key=lambda x: x["confidence"] + min(len(x["text"]), 12)*.008) for cluster in name_clusters]
    name_items = sorted(name_items, key=lambda x: x["y"], reverse=True)
    horses = []
    for index, name_item in enumerate(name_items[:18], 1):
        y = name_item["y"]
        row = [x for x in items if abs(x["y"] - y) <= .014 and x["y"] < .68]
        def at(x1, x2, pattern=None):
            values = [x for x in row if x1 <= x["x"] < x2 and (pattern is None or re.search(pattern, x["text"]))]
            return max(values, key=lambda x: x["confidence"] - abs(x["y"]-y)*4)["text"].strip() if values else ""
        sex_age = at(.275, .323, r"[牡牝セ]\s*\d+")
        weight = at(.318, .36, r"\d{2}(?:\.\d)?")
        jockey = at(.35, .425)
        stable = at(.415, .56)
        odds = at(.555, .62, r"\d+\.\d")
        popularity = at(.61, .66, r"^\d{1,2}$")
        frame_text = at(.012, .045, r"^\d$")
        stable = re.sub(r"^(?:美浦|栗東)\s*", "", stable)
        horse = {k: "" for k in HORSE_COLUMNS}
        horse.update({
            "馬番": index,
            "枠番": int(frame_text) if frame_text.isdigit() else "",
            "馬名": re.sub(r"^[^0-9A-Za-zぁ-んァ-ヶ一-龠]+", "", name_item["text"].strip()),
            "性齢": sex_age,
            "斤量": weight,
            "騎手": jockey,
            "厩舎": stable,
            "人気": int(popularity) if popularity.isdigit() else "",
            "単勝オッズ": float(odds) if re.fullmatch(r"\d+\.\d", odds) else "",
        })
        horses.append(horse)
    if race_name and horses: warnings.append(f"{race_name}: {len(horses)}頭をローカル抽出しました")
    return info, horses, warnings


def _normalize_horse(horse: dict) -> dict:
    item = {k: horse.get(k, "") for k in HORSE_COLUMNS}
    for key in ("馬番", "枠番", "人気"):
        value = re.sub(r"\D", "", str(item.get(key, "")))
        item[key] = int(value) if value else ""
    odds = re.search(r"\d+(?:\.\d+)?", str(item.get("単勝オッズ", "")))
    item["単勝オッズ"] = float(odds.group()) if odds else ""
    return item


def calculate_scores(horses: list[dict], final_scores: dict, multipliers: dict) -> list[dict]:
    rows = []
    evidence_signals = []
    field_size = max(2, len(horses))
    for h in horses:
        no = str(h.get("馬番", "")); s = final_scores.get(no, {k: 3 for k in SCORE_KEYS})
        subs = {}
        for label, weights in BASE_WEIGHTS.items():
            weighted = sum(float(s.get(k, 3)) * w * float(multipliers.get(k, 1)) for k, w in weights.items())
            denom = sum(w * float(multipliers.get(k, 1)) for k, w in weights.items())
            subs[label] = weighted / denom if denom else 0
        total = subs["本命スコア"] * .45 + subs["条件適性スコア"] * .30 + subs["妙味スコア"] * .25
        finishes = [int(v) for v in re.findall(r"(?:芝|ダート|ダ)\s*\d{3,4}\s+(\d{1,2})\s+(?:右|左|直)", str(h.get("過去走テキスト", "")))[:5]]
        recent = 1 - (min(field_size, sum(finishes) / len(finishes)) - 1) / (field_size - 1) if finishes else .5
        popularity = max(1, min(field_size, int(_float(h.get("人気"), field_size))))
        market = 1 - (popularity - 1) / (field_size - 1)
        odds = max(1.0, _float(h.get("単勝オッズ"), 10))
        value = min(1.0, math.log1p(odds) / math.log1p(50))
        evidence_signals.append(recent * .60 + market * .25 + value * .15)
        rows.append({"馬番": h.get("馬番"), "枠番": h.get("枠番", ""), "馬名": h.get("馬名"), "人気": h.get("人気", ""), "単勝オッズ": h.get("単勝オッズ", ""), **{k: round(v, 3) for k, v in subs.items()}, "総合スコア": round(total, 3)})

    if not rows:
        return []
    signal_mean = sum(evidence_signals) / len(evidence_signals)
    signal_sd = math.sqrt(sum((v - signal_mean) ** 2 for v in evidence_signals) / len(evidence_signals)) or 1.0
    adjusted_totals = []
    for row, signal in zip(rows, evidence_signals):
        adjustment = max(-.12, min(.12, (signal - signal_mean) / signal_sd * .06))
        adjusted = row["総合スコア"] + adjustment
        row["自動補正"] = round(adjustment, 3)
        adjusted_totals.append(adjusted)
    adjusted_mean = sum(adjusted_totals) / len(adjusted_totals)
    adjusted_sd = math.sqrt(sum((v - adjusted_mean) ** 2 for v in adjusted_totals) / len(adjusted_totals))
    for row, adjusted in zip(rows, adjusted_totals):
        index = 50 if not adjusted_sd else round(max(20, min(95, 50 + 12 * (adjusted - adjusted_mean) / adjusted_sd)))
        row["レース内指数"] = index
    return sorted(rows, key=lambda x: (x["レース内指数"], x["総合スコア"]), reverse=True)


def generate_marks(rows: list[dict]) -> dict[str, str]:
    if not rows: return {}
    marks = {str(r["馬番"]): "△" for r in rows}
    overall = rows
    honmei = sorted(rows, key=lambda x: x["本命スコア"], reverse=True)
    condition = sorted(rows, key=lambda x: x["条件適性スコア"], reverse=True)
    value = sorted(rows, key=lambda x: x["妙味スコア"], reverse=True)
    marks[str(overall[0]["馬番"])] = "◎"
    if len(overall) > 1: marks[str(overall[1]["馬番"])] = "○"
    if len(overall) > 2: marks[str(overall[2]["馬番"])] = "▲"
    # ☆は4〜7位を優先し、妙味上位かつ既存の上位印でない馬を拾う。
    candidates = [r for r in value if str(r["馬番"]) not in {str(x["馬番"]) for x in overall[:3]} and r in overall[3:7]]
    if candidates: marks[str(candidates[0]["馬番"])] = "☆"
    if len(rows) >= 6:
        cutoff = sorted(r.get("レース内指数", r["総合スコア"]) for r in rows)[max(0, len(rows)//4 - 1)]
        for r in rows:
            if r.get("レース内指数", r["総合スコア"]) <= cutoff and marks[str(r["馬番"])] == "△": marks[str(r["馬番"])] = "消"
    return marks


ALL_BET_TYPES = ["単勝", "複勝", "枠連", "馬連", "ワイド", "馬単", "3連複", "3連単"]


def _bet_combinations(rows: list[dict], marks: dict, bet_type: str) -> list[list[str]]:
    """Build a deliberately compact candidate universe; point count is decided internally."""
    active = [r for r in rows if marks.get(str(r["馬番"])) != "消"]
    primary = active[:min(6, len(active))]
    anchor = str(next((r["馬番"] for r in rows if marks.get(str(r["馬番"])) == "◎"), rows[0]["馬番"]))
    numbers = [str(r["馬番"]) for r in primary]
    opponents = [n for n in numbers if n != anchor]
    if bet_type in {"単勝", "複勝"}:
        return [[str(r["馬番"])] for r in primary[:4]]
    if bet_type == "枠連":
        by_no = {str(r["馬番"]): str(r.get("枠番") or r["馬番"]) for r in rows}
        anchor_frame = by_no[anchor]
        return [[anchor_frame, frame] for frame in dict.fromkeys(by_no[n] for n in opponents) if frame != anchor_frame]
    if bet_type in {"馬連", "ワイド"}:
        return [[anchor, n] for n in opponents]
    if bet_type == "馬単":
        combos = [[anchor, n] for n in opponents]
        # 対抗まで力差が小さい場合は逆転目も候補に残す。
        if len(rows) > 1 and rows[0].get("レース内指数", 50) - rows[1].get("レース内指数", 50) <= 8:
            combos += [[n, anchor] for n in opponents[:3]]
        return combos
    triples = []
    secondary = opponents[:4]
    for i, left in enumerate(secondary):
        for right in secondary[i + 1:]:
            triples.append([anchor, left, right])
    if bet_type == "3連複":
        return triples
    # 三連単は◎1着固定を基本とし、上位2頭だけは入替候補にする。
    ordered = []
    for _, left, right in triples:
        ordered.extend([[anchor, left, right], [anchor, right, left]])
    if opponents:
        ordered.extend([[opponents[0], anchor, n] for n in opponents[1:3]])
    return ordered


def _estimated_odds(bet_type: str, rs: list[dict]) -> float:
    singles = [max(1.1, _float(r.get("単勝オッズ"), 8)) for r in rs]
    powers = {"単勝": 1.0, "複勝": .42, "枠連": .48, "馬連": .58, "ワイド": .40, "馬単": .72, "3連複": .72, "3連単": .96}
    discounts = {"単勝": 1.0, "複勝": .72, "枠連": .82, "馬連": .90, "ワイド": .70, "馬単": 1.05, "3連複": 1.15, "3連単": 1.35}
    return max(1.1, math.prod(singles) ** powers[bet_type] * discounts[bet_type])


def _odds_lookup_key(bet_type: str, nums: list[str]) -> str:
    unordered = {"枠連", "馬連", "ワイド", "3連複"}
    normalized = [str(int(float(n))) if re.fullmatch(r"\d+(?:\.0+)?", str(n)) else str(n) for n in nums]
    if bet_type in unordered:
        normalized = sorted(normalized, key=lambda x: int(x) if x.isdigit() else x)
    return f"{bet_type} {'-'.join(normalized)}"


def optimize_bets(rows: list[dict], marks: dict, budget: int, unit: int, types: list[str], mode: str, max_bets: int, min_odds: float, odds_map: dict[str, float] | None = None) -> tuple[list[dict], list[dict]]:
    if not rows or budget < unit: return [], []
    odds_map = odds_map or {}
    by_no = {str(r["馬番"]): r for r in rows}; anchor = next((n for n, m in marks.items() if m == "◎"), str(rows[0]["馬番"]))
    by_frame = {str(r.get("枠番") or r["馬番"]): r for r in rows}
    aggression = {"安定回収": (.60, .25, .15), "標準": (.45, .35, .20), "攻め": (.35, .45, .20)}[mode]
    candidates, skipped = [], []
    for bet_type in types:
        numbers = _bet_combinations(rows, marks, bet_type)
        for nums in numbers:
            key = _odds_lookup_key(bet_type, nums)
            lookup = by_frame if bet_type == "枠連" else by_no
            if any(n not in lookup for n in nums):
                continue
            rs = [lookup[n] for n in nums]
            confidence = sum(r["本命スコア"] for r in rs) / len(rs) / 5
            value = sum(r["妙味スコア"] for r in rs) / len(rs) / 5
            relation = 1.0 if anchor in nums else .55
            score = confidence * aggression[0] + value * aggression[1] + relation * aggression[2]
            default_odds = _estimated_odds(bet_type, rs)
            has_live_odds = key in odds_map
            odds = float(odds_map.get(key, default_odds))
            hit_factor = {"単勝": .52, "複勝": .82, "枠連": .56, "馬連": .48, "ワイド": .70, "馬単": .36, "3連複": .32, "3連単": .17}[bet_type]
            hit_index = max(5, min(90, confidence * hit_factor * 100))
            value_index = max(10, min(99, score * 72 + math.log1p(odds) * 6))
            utility_weights = {"安定回収": (.72, .28), "標準": (.52, .48), "攻め": (.30, .70)}[mode]
            utility = hit_index * utility_weights[0] + value_index * utility_weights[1]
            item = {
                "買い目": key, "券種": bet_type, "買い目スコア": round(utility / 100, 4),
                "現在オッズ": round(odds, 2), "オッズ区分": "取得値" if has_live_odds else "推定値",
                "的中期待度": round(hit_index, 1), "回収期待指数": round(value_index, 1),
                "狙い": f"信頼{hit_index:.0f}・回収妙味{value_index:.0f}のバランス", "見送り理由": "",
            }
            if odds < min_odds:
                item["見送り理由"] = f"最低買いオッズ{min_odds:.1f}未満"; skipped.append(item)
            else: candidates.append(item)
    selected = sorted(candidates, key=lambda x: x["買い目スコア"], reverse=True)[:max_bets]
    if not selected: return [], skipped
    usable = (budget // unit) * unit
    total = sum(x["買い目スコア"] for x in selected)
    amounts = [math.floor((usable * x["買い目スコア"] / total) / unit) * unit for x in selected]
    remainder = usable - sum(amounts)
    for i in range(remainder // unit): amounts[i % len(amounts)] += unit
    output = []
    for item, amount in zip(selected, amounts):
        if amount <= 0: skipped.append({**item, "見送り理由": "配分額が最小購入単位未満"}); continue
        payout = int(amount * item["現在オッズ"])
        output.append({**item, "推奨購入金額": amount, "想定払戻": payout, "想定利益": payout - amount})
    return output, skipped


def propose_bet_plans(rows: list[dict], marks: dict, budget: int, unit: int, min_odds: float, odds_map: dict[str, float] | None = None) -> dict[str, dict]:
    """Compare all ticket types and return distinct, budget-safe portfolio viewpoints."""
    if not rows or budget < unit:
        return {}
    available_units = max(1, budget // unit)
    settings = {
        "的中重視": (["複勝", "ワイド", "枠連", "馬連", "3連複"], "安定回収", min(available_units, 7)),
        "バランス": (ALL_BET_TYPES, "標準", min(available_units, 9)),
        "高回収狙い": (["単勝", "馬単", "3連複", "3連単"], "攻め", min(available_units, 10)),
    }
    plans = {}
    for name, (types, mode, internal_limit) in settings.items():
        bets, skipped = optimize_bets(rows, marks, budget, unit, types, mode, internal_limit, min_odds, odds_map)
        if not bets:
            continue
        avg_hit = sum(b["的中期待度"] * b["推奨購入金額"] for b in bets) / sum(b["推奨購入金額"] for b in bets)
        avg_value = sum(b["回収期待指数"] * b["推奨購入金額"] for b in bets) / sum(b["推奨購入金額"] for b in bets)
        plans[name] = {
            "bets": bets, "skipped": skipped,
            "summary": {"点数": len(bets), "的中期待指数": round(avg_hit, 1), "回収期待指数": round(avg_value, 1)},
        }
    if plans:
        # 両指数の調和平均が最も高い案を、レースごとのAIおすすめとして提示する。
        recommended = max(plans, key=lambda name: 2 * plans[name]["summary"]["的中期待指数"] * plans[name]["summary"]["回収期待指数"] / max(1, plans[name]["summary"]["的中期待指数"] + plans[name]["summary"]["回収期待指数"]))
        plans[recommended]["recommended"] = True
    return plans


def parse_odds(text: str, bet_type: str) -> dict[str, float]:
    result = {}
    for line in text.splitlines():
        nums = re.findall(r"\d+(?:\.\d+)?", line)
        if bet_type in {"単勝", "複勝"} and len(nums) >= 2:
            result[f"{bet_type} {int(float(nums[0]))}"] = float(nums[-1])
        elif bet_type in {"枠連", "ワイド", "馬連", "馬単"} and len(nums) >= 3:
            a, b = int(float(nums[0])), int(float(nums[1]))
            result[_odds_lookup_key(bet_type, [str(a), str(b)])] = float(nums[-1])
        elif bet_type in {"3連複", "3連単"} and len(nums) >= 4:
            a, b, c = int(float(nums[0])), int(float(nums[1])), int(float(nums[2]))
            result[_odds_lookup_key(bet_type, [str(a), str(b), str(c)])] = float(nums[-1])
    return result


def parse_popular_odds_snapshot(text: str) -> dict[str, float]:
    """Parse compact netkeiba-style popular odds tables pasted as text.

    The input may contain several sections such as 単勝・複勝, 馬連・ワイド,
    馬単, 3連複, 3連単.  Only visible popular rows are parsed; missing tickets
    continue to use model estimates in optimize_bets.
    """
    result: dict[str, float] = {}
    current = ""
    section_aliases = [
        ("単勝", re.compile(r"単勝|複勝")),
        ("3連単", re.compile(r"3\s*連\s*単|三\s*連\s*単")),
        ("3連複", re.compile(r"3\s*連\s*複|三\s*連\s*複")),
        ("馬連ワイド", re.compile(r"馬連|ワイド")),
        ("馬単", re.compile(r"馬単")),
        ("枠連", re.compile(r"枠連")),
    ]
    for raw_line in text.splitlines():
        line = unicodedata.normalize("NFKC", raw_line).strip()
        if not line:
            continue
        for name, pattern in section_aliases:
            if pattern.search(line):
                current = name
                break
        numbers = re.findall(r"\d+(?:\.\d+)?", line)
        if not numbers:
            continue
        # 単勝・複勝表: 人気 枠 馬番 ... 単勝 複勝下限 複勝上限 の形を想定。
        if current == "単勝" and len(numbers) >= 4:
            horse_no = int(float(numbers[2] if len(numbers) >= 6 else numbers[0]))
            single = float(numbers[-3])
            place_low, place_high = float(numbers[-2]), float(numbers[-1])
            result[f"単勝 {horse_no}"] = single
            result[f"複勝 {horse_no}"] = round((place_low + place_high) / 2, 2)
            continue
        if current in {"馬単", "3連単"}:
            need = 2 if current == "馬単" else 3
            pattern = r"(\d{1,2})\s*[>＞]\s*(\d{1,2})" if need == 2 else r"(\d{1,2})\s*[>＞]\s*(\d{1,2})\s*[>＞]\s*(\d{1,2})"
            match = re.search(pattern, line)
            if match:
                combo = [str(int(v)) for v in match.groups()]
                odds = float(numbers[-1])
                result[_odds_lookup_key(current, combo)] = odds
            elif len(numbers) >= need + 1:
                offset = 1 if len(numbers) >= need + 2 else 0
                combo = [str(int(float(v))) for v in numbers[offset:offset + need]]
                odds = float(numbers[-1])
                result[_odds_lookup_key(current, combo)] = odds
            continue
        if current in {"枠連", "馬連ワイド", "3連複"}:
            need = 2 if current != "3連複" else 3
            pattern = r"(\d{1,2})\s*[-ー]\s*(\d{1,2})" if need == 2 else r"(\d{1,2})\s*[-ー]\s*(\d{1,2})\s*[-ー]\s*(\d{1,2})"
            match = re.search(pattern, line)
            if match:
                combo = [str(int(v)) for v in match.groups()]
            elif len(numbers) >= need + 1:
                offset = 1 if len(numbers) >= need + 2 else 0
                combo = [str(int(float(v))) for v in numbers[offset:offset + need]]
            else:
                continue
            if len(numbers) >= need + 1:
                odds = float(numbers[-1])
                if current == "馬連ワイド":
                    # 馬連・ワイドの同一行では、先に馬連オッズ、最後にワイド上限が並ぶことが多い。
                    result[_odds_lookup_key("馬連", combo)] = float(numbers[-3]) if len(numbers) >= need + 4 else odds
                    result[_odds_lookup_key("ワイド", combo)] = odds
                else:
                    result[_odds_lookup_key(current, combo)] = odds
    return result


def ocr_text_with_macos_vision(data: bytes) -> str:
    """Return generic OCR text from an image using macOS Vision."""
    items, _, _ = _macos_vision_single(data)
    rows: list[list[dict]] = []
    for item in sorted(items, key=lambda x: -x["y"]):
        if not rows or abs(rows[-1][0]["y"] - item["y"]) > 0.012:
            rows.append([item])
        else:
            rows[-1].append(item)
    lines = []
    for row in rows:
        tokens = [item["text"] for item in sorted(row, key=lambda x: x["x"]) if item.get("text")]
        if tokens:
            lines.append(" ".join(tokens))
    return "\n".join(lines)


def ocr_popular_odds_image_with_tesseract(data: bytes) -> str:
    """OCR a fixed-ish popular odds screenshot without paid APIs.

    The full image plus coarse left/right and lower-table crops are OCR'd because
    netkeiba-style screenshots often contain multiple independent odds tables.
    """
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("Tesseract OCR用のPythonライブラリが未導入です。") from exc
    image = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
    image = ImageOps.autocontrast(image, cutoff=1)
    if image.width < 1400:
        scale = min(2.5, 1400 / max(1, image.width))
        image = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
    image = ImageEnhance.Contrast(image).enhance(1.25)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.1, percent=145, threshold=3))
    crops = [("全体", image)]
    w, h = image.size
    boxes = [
        ("左上", (0, 0, int(w * .62), int(h * .50))),
        ("右上", (int(w * .58), 0, w, int(h * .50))),
        ("左下", (0, int(h * .46), int(w * .36), h)),
        ("中央下", (int(w * .32), int(h * .46), int(w * .68), h)),
        ("右下", (int(w * .64), int(h * .46), w, h)),
    ]
    for name, box in boxes:
        crop = image.crop(box)
        if crop.width > 80 and crop.height > 80:
            crops.append((name, crop))
    texts = []
    for name, crop in crops:
        text = pytesseract.image_to_string(crop, lang="jpn+eng", config="--psm 6")
        if text.strip():
            texts.append(f"【{name}】\n{text.strip()}")
    if not texts:
        raise RuntimeError("Tesseract OCRで文字を読み取れませんでした。")
    return "\n".join(texts)


def parse_popular_odds_image_with_openai(data: bytes, mime: str, api_key: str, model: str = "gpt-5.4-mini") -> tuple[dict[str, float], str]:
    """Read a popular-odds screenshot and return normalized odds keys."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    encoded = base64.b64encode(data).decode("ascii")
    schema = {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "bet_type": {"type": "string", "enum": ["単勝", "複勝", "枠連", "馬連", "ワイド", "馬単", "3連複", "3連単"]},
                        "numbers": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
                        "odds": {"type": "number"},
                        "source_text": {"type": "string"},
                    },
                    "required": ["bet_type", "numbers", "odds", "source_text"],
                    "additionalProperties": False,
                },
            },
            "transcript": {"type": "string"},
        },
        "required": ["rows", "transcript"],
        "additionalProperties": False,
    }
    response = client.responses.create(
        model=model,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": (
                "これは競馬のオッズ人気上位表のスクリーンショットです。"
                "見えている単勝・複勝・馬連・ワイド・馬単・3連複・3連単の組み合わせとオッズを抽出してください。"
                "馬連/ワイドのように1行に複数券種がある場合は、それぞれ別行として出してください。"
                "複勝が範囲表示の場合は上下限の平均値をoddsにしてください。"
                "人気順位はnumbersに含めず、馬番または枠番だけを入れてください。読めない行は出力しないでください。"
            )},
            {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}", "detail": "high"},
        ]}],
        text={"format": {"type": "json_schema", "name": "popular_odds_image", "strict": True, "schema": schema}},
        max_output_tokens=8000,
    )
    payload = json.loads(response.output_text)
    result: dict[str, float] = {}
    for row in payload.get("rows", []):
        bet_type = str(row.get("bet_type", ""))
        numbers = [str(int(float(v))) for v in row.get("numbers", []) if re.fullmatch(r"\d+(?:\.\d+)?", str(v))]
        if not bet_type or not numbers:
            continue
        result[_odds_lookup_key(bet_type, numbers)] = float(row["odds"])
    return result, str(payload.get("transcript", ""))


def compare_odds(previous: dict[str, float], current: dict[str, float], min_odds: float) -> tuple[list[dict], list[str]]:
    rows, alerts = [], []
    for key, now in current.items():
        before = previous.get(key); change = ((now - before) / before * 100) if before else None
        threshold = -30 if key.startswith("単勝") else -20
        decision = "買い"
        if now < min_odds: decision = "見送り"; alerts.append(f"{key}: 最低買いオッズを下回りました")
        elif change is None: decision = "要確認"
        elif change <= threshold: decision = "減額"; alerts.append(f"{key}: オッズが{abs(change):.1f}%低下")
        elif change >= 25: alerts.append(f"{key}: 妙味が大きく上昇（オッズ{change:.1f}%上昇）")
        rows.append({"買い目": key, "現在オッズ": now, "前回オッズ": before, "変動率(%)": round(change, 1) if change is not None else None, "最低買いオッズ": min_odds, "判定": decision})
    return rows, alerts


def save_json(state: dict, root: str = "data/races") -> Path:
    Path(root).mkdir(parents=True, exist_ok=True)
    info = state.get("race_info", {}); slug = re.sub(r"[^\w\-]+", "_", f"{info.get('日付','')}_{info.get('競馬場','')}_{info.get('レース番号','')}_{info.get('レース名','')}").strip("_") or datetime.now().strftime("race_%Y%m%d_%H%M%S")
    path = Path(root) / f"{slug}.json"; temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(temp, path)
    return path


def archive_prediction(state: dict, label: str = "", root: str = "data/predictions") -> Path:
    """Create an immutable, user-selected prediction snapshot."""
    Path(root).mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    info = state.get("race_info", {})
    title = label.strip() or " ".join(str(v) for v in [info.get("日付", ""), info.get("競馬場", ""), info.get("レース番号", ""), info.get("レース名", "")] if v) or "名称未設定"
    slug = re.sub(r"[^\w\-]+", "_", title).strip("_")[:80] or "prediction"
    path = Path(root) / f"{now.strftime('%Y%m%d_%H%M%S_%f')}_{slug}.json"
    snapshot = deepcopy(state)
    snapshot["prediction_meta"] = {"title": title, "saved_at": now.isoformat(timespec="seconds"), "creator": "カミノ競馬クラブ"}
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(temp, path)
    return path


def list_predictions(root: str = "data/predictions", limit: int = 50) -> list[dict]:
    """Return recent prediction snapshots without scanning/rendering an unbounded list.

    Shared deployments can accumulate files quickly.  Keeping the sidebar list capped
    avoids slow reruns while still making recent predictions easy to reopen.
    """
    result = []
    for path in sorted(Path(root).glob("*.json"), reverse=True) if Path(root).exists() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            meta = data.get("prediction_meta", {})
            result.append({"path": str(path), "title": meta.get("title", path.stem), "saved_at": meta.get("saved_at", "")})
            if len(result) >= limit:
                break
        except (OSError, json.JSONDecodeError):
            continue
    return result


def load_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _float(value, default=0.0) -> float:
    try: return float(value)
    except (TypeError, ValueError): return float(default)
