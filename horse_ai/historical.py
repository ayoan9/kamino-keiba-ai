from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

from lxml import html

from .core import data_path
from .jra_fetcher import _anchor_actions, _post_jra, _tables


ENDPOINT = "/JRADB/accessS.html"
PAST_START = "pw01skl00999999/B3"
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def _normal_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s|第\d+回|G(?:I{1,3}|1|2|3)|Jpn\d", "", text, flags=re.I)
    return text.replace("ステークス", "S").replace("牝馬", "牝馬").lower()


def _display_month(document: str) -> tuple[int, int]:
    tree = html.fromstring(document)
    text = " ".join(tree.xpath("//text()"))
    matches = re.findall(r"(20\d{2})年\s*(\d{1,2})月", text)
    if not matches:
        raise ValueError("JRA過去結果の表示月を読み取れませんでした")
    counts = {}
    for item in matches: counts[item] = counts.get(item, 0) + 1
    year, month = max(counts, key=counts.get)
    return int(year), int(month)


def _available_month_tokens(document: str) -> dict[tuple[int, int], str]:
    output = {}
    for year, month, suffix in re.findall(r'objParam\["(\d{2})(\d{2})"\]\s*=\s*"([A-Z0-9]+)"', document):
        full_year = 2000 + int(year)
        output[(full_year, int(month))] = f"pw01skl10{full_year}{int(month):02d}/{suffix}"
    return output


def _month_link(document: str, year: int, month: int) -> str:
    label = f"{year}年{month}月"
    return next((token for text, token in _anchor_actions(document, ENDPOINT) if label in text), "")


def _previous_year_link(document: str) -> str:
    return next((token for text, token in _anchor_actions(document, ENDPOINT) if text.strip() == "前年"), "")


def _venue_day_links(document: str, venue: str) -> list[tuple[str, str]]:
    output = []
    for label, token in _anchor_actions(document, ENDPOINT):
        if venue in label and re.search(r"\d+回.+\d+日", label):
            output.append((label.strip(), token))
    return output


def _day_races(document: str, venue: str, day_label: str) -> list[dict]:
    tables = _tables(document)
    table = next((item for item in tables if {"レース名", "距離", "馬場"}.issubset(set(item.columns))), None)
    if table is None:
        return []
    tokens = re.findall(r"pw01sde[^'\"\s<]+", document)
    tokens = list(dict.fromkeys(tokens))
    date_tokens = re.findall(r"20\d{6}", tokens[0]) if tokens else []
    day_match = re.fullmatch(r"(20\d{2})(\d{2})(\d{2})", date_tokens[-1]) if date_tokens else None
    day_value = f"{day_match.group(1)}-{day_match.group(2)}-{day_match.group(3)}" if day_match else ""
    output = []
    for index, row in table.reset_index(drop=True).iterrows():
        distance_match = re.search(r"\d[\d,]{2,4}", str(row.get("距離", "")))
        surface = str(row.get("馬場", "")).strip()
        output.append({
            "日付": day_value, "競馬場": venue, "開催": day_label,
            "レース番号": index + 1, "レース名": str(row.get("レース名", "")).strip(),
            "距離": int(distance_match.group().replace(",", "")) if distance_match else 0,
            "芝/ダート": "ダート" if "ダート" in surface else "芝" if "芝" in surface else surface,
            "頭数": int(re.sub(r"\D", "", str(row.get("出走頭数", ""))) or 0),
            "result_token": tokens[index] if index < len(tokens) else "",
        })
    return output


def _result_detail(document: str, base: dict) -> dict:
    tree = html.fromstring(document)
    text = " ".join(" ".join(tree.xpath("//text()")).split())
    laps_match = re.search(r"ハロンタイム\s*((?:\d{2}\.\d\s*-\s*)+\d{2}\.\d)", text)
    laps = [float(value) for value in re.findall(r"\d{2}\.\d", laps_match.group(1))] if laps_match else []
    going_match = re.search(r"(?:芝|ダート)\s*(良|稍重|重|不良)", text)
    tables = _tables(document)
    result_table = next((item for item in tables if "着順" in item.columns and "馬番" in item.columns), None)
    winners = []
    if result_table is not None:
        for _, row in result_table.head(3).iterrows():
            winners.append({str(key): (value.item() if hasattr(value, "item") else value) for key, value in row.items()})
    first3 = round(sum(laps[:3]), 1) if len(laps) >= 6 else ""
    last3 = round(sum(laps[-3:]), 1) if len(laps) >= 3 else ""
    pace = ""
    if first3 != "" and last3 != "":
        difference = first3 - last3
        pace = "H" if difference <= -1.0 else "S" if difference >= 1.0 else "M"
    return {**base, "馬場": going_match.group(1) if going_match else "", "ハロン": laps, "前半3F": first3, "上がり3F": last3, "ペース": pace, "上位3頭": winners}


def aggregate_history(races: list[dict], label: str) -> dict:
    valid = [race for race in races if race.get("ハロン")]
    pace_counts = {key: sum(race.get("ペース") == key for race in valid) for key in ("S", "M", "H")}
    first = [float(race["前半3F"]) for race in valid if race.get("前半3F") != ""]
    last = [float(race["上がり3F"]) for race in valid if race.get("上がり3F") != ""]
    winner_popularity = []
    for race in valid:
        winner = (race.get("上位3頭") or [{}])[0]
        for key, value in winner.items():
            if "人気" in key:
                number = re.sub(r"\D", "", str(value))
                if number: winner_popularity.append(int(number))
                break
    return {
        "区分": label, "サンプル数": len(valid), "ペース内訳": pace_counts,
        "平均前半3F": round(sum(first) / len(first), 1) if first else "",
        "平均上がり3F": round(sum(last) / len(last), 1) if last else "",
        "勝ち馬平均人気": round(sum(winner_popularity) / len(winner_popularity), 1) if winner_popularity else "",
        "対象レース": valid,
    }


def load_cached_history(race_info: dict, root: str = "data/history") -> dict | None:
    key = history_key(race_info)
    path = data_path(root) / "aggregates" / f"{key}.json"
    if not path.exists(): return None
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return None


def history_key(race_info: dict) -> str:
    return re.sub(r"[^\w-]+", "_", f'{race_info.get("レース名","")}_{race_info.get("競馬場","")}_{race_info.get("芝/ダート","")}{race_info.get("距離","")}').strip("_")


def history_job_status(race_info: dict) -> dict:
    with _JOBS_LOCK:
        return dict(_JOBS.get(history_key(race_info), {}))


def start_history_job(race_info: dict, force: bool = False, root: str = "data/history") -> dict:
    key = history_key(race_info)
    with _JOBS_LOCK:
        existing = _JOBS.get(key, {})
        if existing.get("状態") == "取得中": return dict(existing)
        _JOBS[key] = {"状態": "取得中", "開始日時": datetime.now().isoformat(timespec="seconds"), "メッセージ": "JRA公式結果を低頻度で収集中です"}
    def worker():
        try:
            result = fetch_historical_trends(race_info, root=root, force=force)
            with _JOBS_LOCK: _JOBS[key] = {"状態": "完了", "完了日時": datetime.now().isoformat(timespec="seconds"), "メッセージ": f'{result.get("リクエスト数",0)}ページを確認しました'}
        except Exception as exc:
            with _JOBS_LOCK: _JOBS[key] = {"状態": "エラー", "完了日時": datetime.now().isoformat(timespec="seconds"), "メッセージ": str(exc)[:300]}
    threading.Thread(target=worker, name=f"jra-history-{key[:24]}", daemon=True).start()
    return history_job_status(race_info)


def fetch_historical_trends(race_info: dict, root: str = "data/history", interval_seconds: float = 2.0, force: bool = False, course_years: int = 3, named_years: int = 10, max_details: int = 80) -> dict:
    """Low-frequency JRA history collector. The first build can take several minutes."""
    cached = load_cached_history(race_info, root)
    if cached and not force:
        updated = datetime.fromisoformat(cached["更新日時"])
        if (datetime.now() - updated).days < 7: return {**cached, "キャッシュ利用": True}
    venue = str(race_info.get("競馬場", "")); surface = str(race_info.get("芝/ダート", ""))
    distance = int(float(race_info.get("距離", 0) or 0)); race_name = _normal_name(race_info.get("レース名", ""))
    if not venue or not surface or not distance: raise ValueError("競馬場・芝ダート・距離が必要です")
    target_date = str(race_info.get("日付", ""))
    date_match = re.search(r"(20\d{2})\D*(\d{1,2})", target_date)
    target_year, target_month = (int(date_match.group(1)), int(date_match.group(2))) if date_match else (date.today().year, date.today().month)
    request_count = 0
    def fetch(token: str) -> str:
        nonlocal request_count
        if request_count: time.sleep(max(1.0, interval_seconds))
        request_count += 1
        return _post_jra(ENDPOINT, token)

    document = fetch(PAST_START)
    available = _available_month_tokens(document)
    target_months = set()
    cursor = date(target_year, target_month, 1)
    for _ in range(max(1, course_years * 12)):
        target_months.add((cursor.year, cursor.month))
        cursor = date(cursor.year - (1 if cursor.month == 1 else 0), 12 if cursor.month == 1 else cursor.month - 1, 1)
    for year_back in range(named_years): target_months.add((target_year - year_back, target_month))
    month_documents = {}
    for month_key in sorted(target_months, reverse=True):
        token = available.get(month_key)
        if token: month_documents[month_key] = fetch(token)

    day_links = {}
    for month_doc in month_documents.values():
        for label, token in _venue_day_links(month_doc, venue): day_links[token] = label
    catalog = []
    for token, label in day_links.items():
        catalog.extend(_day_races(fetch(token), venue, label))
    same_name = [race for race in catalog if race_name and _normal_name(race["レース名"]) == race_name]
    course_cutoff = target_year - course_years
    same_course = [race for race in catalog if race["芝/ダート"] == surface and race["距離"] == distance and (not race["日付"] or int(race["日付"][:4]) >= course_cutoff)]
    detail_targets = []
    for race in [*same_name, *same_course]:
        if race.get("result_token") and race["result_token"] not in {x["result_token"] for x in detail_targets}: detail_targets.append(race)
    detail_targets = sorted(detail_targets, key=lambda item: item.get("日付", ""), reverse=True)[:max_details]
    details = {race["result_token"]: _result_detail(fetch(race["result_token"]), race) for race in detail_targets}
    named_details = [details[race["result_token"]] for race in same_name if race.get("result_token") in details]
    course_details = [details[race["result_token"]] for race in same_course if race.get("result_token") in details]
    result = {
        "更新日時": datetime.now().isoformat(timespec="seconds"), "取得元": "JRA公式", "リクエスト数": request_count,
        "同名レース": aggregate_history(named_details, "同名レース過去10年"),
        "同条件レース": aggregate_history(course_details, "同コース・距離過去3年"),
        "検索条件": {"レース名": race_info.get("レース名", ""), "競馬場": venue, "芝/ダート": surface, "距離": distance},
        "注意": "同名レースは開催月を中心に過去10年を検索。条件変更や大幅な開催時期移動がある場合は同条件傾向を優先します。",
        "キャッシュ利用": False,
    }
    key = history_key(race_info)
    path = data_path(root) / "aggregates" / f"{key}.json"; path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp"); temp.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"); temp.replace(path)
    return result
