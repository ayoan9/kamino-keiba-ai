from __future__ import annotations

import math
import re
import time
from datetime import datetime
from io import StringIO
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from lxml import html


BASE_URL = "https://www.jra.go.jp"
ODDS_TYPES = ["単勝・複勝", "枠連", "馬連", "ワイド", "馬単", "3連複", "3連単"]


def _post_jra(endpoint: str, cname: str, timeout: int = 45) -> str:
    body = urlencode({"cname": cname}).encode("ascii")
    request = Request(
        BASE_URL + endpoint,
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 Chrome/136 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Language": "ja,en;q=0.8",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("cp932", "replace")


def _anchor_actions(document: str, endpoint: str) -> list[tuple[str, str]]:
    tree = html.fromstring(document)
    actions = []
    for anchor in tree.xpath(f'//a[contains(@onclick,"{endpoint}")]'):
        onclick = anchor.get("onclick", "")
        token = re.search(r"doAction\([^,]+,\s*['\"]([^'\"]+)['\"]", onclick)
        if not token:
            continue
        text = " ".join("".join(anchor.itertext()).split())
        alt = " ".join(anchor.xpath(".//img/@alt"))
        actions.append((text + " " + alt, token.group(1)))
    return actions


def _race_identity(race_info: dict) -> tuple[str, int]:
    venue = str(race_info.get("競馬場", "")).strip()
    meeting = str(race_info.get("開催回", "")).strip()
    day = str(race_info.get("開催日", "")).strip()
    race_no = int(float(race_info.get("レース番号", 0) or 0))
    if not venue or not meeting or not day or not race_no:
        raise ValueError("JRA自動取得には競馬場・開催回・開催日・レース番号が必要です")
    return f"{int(meeting)}回{venue}{int(day)}日", race_no


def _discover_race_page(race_info: dict, endpoint: str, start_token: str) -> tuple[str, str]:
    day_label, race_no = _race_identity(race_info)
    start = _post_jra(endpoint, start_token)
    day_actions = _anchor_actions(start, endpoint)
    day_token = next((token for label, token in day_actions if day_label in label), "")
    if not day_token:
        raise ValueError(f"JRAで開催を見つけられませんでした: {day_label}")
    race_select = _post_jra(endpoint, day_token)
    actions = _anchor_actions(race_select, endpoint)
    exact = [token for label, token in actions if f"{race_no}レース" in label or re.search(rf"(?:^|\s)\D*{race_no}R(?:\s|$)", label)]
    if not exact:
        raise ValueError(f"JRAで{race_no}Rを見つけられませんでした")
    race_token = exact[0]
    return race_token, _post_jra(endpoint, race_token)


def _tables(document: str) -> list[pd.DataFrame]:
    try:
        tables = pd.read_html(StringIO(document), flavor="lxml")
    except ValueError:
        return []
    output = []
    for table in tables:
        if isinstance(table.columns, pd.MultiIndex):
            table.columns = [" ".join(str(x) for x in col if str(x) != "nan").strip() for col in table.columns]
        table = table.replace({float("nan"): ""})
        output.append(table)
    return output


def _records(table: pd.DataFrame) -> list[dict[str, Any]]:
    records = []
    for row in table.to_dict("records"):
        cleaned = {}
        for key, value in row.items():
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                value = ""
            cleaned[str(key)] = value.item() if hasattr(value, "item") else value
        records.append(cleaned)
    return records


def _single_odds(tables: list[pd.DataFrame]) -> dict[str, float]:
    result = {}
    table = next((item for item in tables if {"馬番", "単勝"}.issubset(set(item.columns))), None)
    if table is None:
        return result
    for _, row in table.iterrows():
        try:
            number = int(float(row["馬番"]))
            result[f"単勝 {number}"] = float(str(row["単勝"]).replace(",", ""))
            place = re.findall(r"\d+(?:\.\d+)?", str(row.get("複勝（3着払い）", "")))
            if place:
                result[f"複勝 {number}"] = float(place[0])
        except (TypeError, ValueError):
            continue
    return result


def fetch_jra_odds(race_info: dict, page_interval_seconds: float = 2.0) -> dict:
    """Fetch one low-frequency snapshot of JRA odds pages for the selected race."""
    race_token, first_page = _discover_race_page(race_info, "/JRADB/accessO.html", "pw15oli00/6D")
    pages = {"単勝・複勝": first_page}
    ticket_tokens = {}
    for label, token in _anchor_actions(first_page, "/JRADB/accessO.html"):
        compact = label.replace(" ", "")
        for ticket in ODDS_TYPES:
            if compact == ticket:
                ticket_tokens[ticket] = token
    for ticket in ODDS_TYPES[1:]:
        token = ticket_tokens.get(ticket)
        if not token:
            continue
        time.sleep(max(1.0, page_interval_seconds))
        pages[ticket] = _post_jra("/JRADB/accessO.html", token)
    tables = {ticket: _tables(document) for ticket, document in pages.items()}
    return {
        "取得時刻": datetime.now().isoformat(timespec="seconds"),
        "取得元": "JRA公式",
        "race_token": race_token,
        "odds": _single_odds(tables.get("単勝・複勝", [])),
        "券種テーブル": {ticket: [_records(table) for table in ticket_tables] for ticket, ticket_tables in tables.items()},
        "取得券種": list(pages),
    }


def fetch_jra_result(race_info: dict) -> dict:
    """Fetch the official result once it is published."""
    _, document = _discover_race_page(race_info, "/JRADB/accessS.html", "pw01sli00/AF")
    tables = _tables(document)
    result_table = next((table for table in tables if "着順" in table.columns and "馬番" in table.columns), None)
    if result_table is None:
        raise ValueError("レース結果はまだ確定していません")
    order = []
    for _, row in result_table.iterrows():
        try:
            finish = str(row["着順"])
            number = str(int(float(row["馬番"])))
            if finish.isdigit():
                order.append((int(finish), number))
        except (TypeError, ValueError):
            continue
    order.sort()
    if not order:
        raise ValueError("確定着順を取得できませんでした")
    return {
        "取得時刻": datetime.now().isoformat(timespec="seconds"),
        "取得元": "JRA公式",
        "確定着順": "\n".join(f"{place}着 {number}番" for place, number in order),
        "着順馬番": [number for _, number in order],
    }
