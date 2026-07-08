from horse_ai.core import BASE_WEIGHTS, HORSE_COLUMNS, SCORE_KEYS, _evaluation_prompt, _prepare_visual_inputs, add_betting_journal_entries, add_betting_journal_entry, analyze_race_trends, archive_prediction, betting_journal_entries, calculate_scores, compare_odds, delete_local_api_key, fetch_netkeiba_popular_odds, generate_marks, heuristic_evaluations, infer_running_style, learn_from_race_result, learn_from_result_history, learn_odds_calibration, learn_prediction_adjustments, list_predictions, load_layout_profiles, load_prediction_profile, merge_web_history, optimize_bets, parse_betting_history_text, parse_finish_order, parse_odds, parse_popular_odds_snapshot, parse_single_odds_text, prediction_policy_prompt, propose_bet_plans, save_layout_profile, save_local_api_key, save_prediction_profile, update_betting_journal_entry
from horse_ai.historical import _available_month_tokens, _day_races, _result_detail, aggregate_history
from horse_ai.jra_fetcher import _anchor_actions, _race_identity, _single_odds, _tables


def sample():
    horses = [{"馬番": i, "馬名": f"馬{i}", "人気": i, "単勝オッズ": 2+i} for i in range(1, 9)]
    scores = {str(i): {"近走評価": 6-i//2, "距離・コース適性": 4, "馬場適性": 3, "展開利": 4, "本命適性": 6-i//2, "妙味": 2+i//2, "騎手評価": 4, "厩舎・ローテ評価": 3} for i in range(1, 9)}
    return horses, scores


def test_score_marks_and_budget():
    horses, scores = sample(); rows = calculate_scores(horses, scores, {k: 1 for k in next(iter(scores.values()))}); marks = generate_marks(rows)
    bets, _ = optimize_bets(rows, marks, 2300, 100, ["単勝", "ワイド"], "標準", 5, 1.1)
    assert sum(b["推奨購入金額"] for b in bets) <= 2300
    assert "◎" in marks.values() and "☆" in marks.values()
    assert all(20 <= row["レース内指数"] <= 95 for row in rows)
    assert rows == sorted(rows, key=lambda row: row["レース内指数"], reverse=True)


def test_pedigree_is_folded_into_course_and_track_without_separate_score():
    assert len(SCORE_KEYS) == 8
    assert "血統評価" not in SCORE_KEYS
    assert all("血統評価" not in weights for weights in BASE_WEIGHTS.values())
    assert all(abs(sum(weights.values()) - 1.0) < 1e-9 for weights in BASE_WEIGHTS.values())
    assert "距離・コース適性と馬場適性" in _evaluation_prompt([], {}, "")


def test_ai_bet_plans_choose_points_and_ticket_types_without_user_limit():
    horses, scores = sample()
    rows = calculate_scores(horses, scores, {key: 1 for key in SCORE_KEYS})
    plans = propose_bet_plans(rows, generate_marks(rows), 5000, 100, 1.1)
    assert set(plans) == {"軸セット", "的中30%型", "回収重視", "高回収狙い"}
    assert sum(bool(plan.get("recommended")) for plan in plans.values()) == 1
    for plan in plans.values():
        assert sum(bet["推奨購入金額"] for bet in plan["bets"]) <= 5000
        assert all(bet["推奨購入金額"] % 100 == 0 for bet in plan["bets"])
        assert all("的中期待度" in bet and "回収期待指数" in bet for bet in plan["bets"])
    assert {"単勝", "馬連", "ワイド"} & {bet["券種"] for bet in plans["軸セット"]["bets"]}
    assert len(plans["的中30%型"]["bets"]) <= 5
    assert any(bet["券種"] in {"3連複", "3連単"} for bet in plans["高回収狙い"]["bets"])


def test_ai_bet_plans_add_personal_results_viewpoint():
    horses, scores = sample()
    rows = calculate_scores(horses, scores, {key: 1 for key in SCORE_KEYS})
    profile = {
        "betting_journal": {
            "entries": [
                {"券種": "ワイド", "購入額": 1000, "払戻額": 3200},
                {"券種": "ワイド", "購入額": 800, "払戻額": 0},
                {"券種": "馬連", "購入額": 1000, "払戻額": 2800},
                {"券種": "馬連", "購入額": 1000, "払戻額": 0},
            ]
        }
    }
    plans = propose_bet_plans(rows, generate_marks(rows), 5000, 100, 1.1, prediction_profile=profile)
    assert "実績反映" in plans
    assert "ワイド" in plans["実績反映"]["summary"]["実績券種"]
    assert all(bet["券種"] in {"ワイド", "馬連"} for bet in plans["実績反映"]["bets"])


def test_race_index_breaks_equal_manual_scores_without_more_input():
    horses = [
        {"馬番": 1, "馬名": "A", "人気": 1, "単勝オッズ": 3.0, "過去走テキスト": "芝1800 1 左A"},
        {"馬番": 2, "馬名": "B", "人気": 8, "単勝オッズ": 30.0, "過去走テキスト": "芝1800 12 左A"},
    ]
    same_scores = {str(h["馬番"]): {key: 3 for key in SCORE_KEYS} for h in horses}
    rows = calculate_scores(horses, same_scores, {key: 1 for key in SCORE_KEYS})
    assert rows[0]["総合スコア"] == rows[1]["総合スコア"] == 3
    assert rows[0]["レース内指数"] != rows[1]["レース内指数"]


def test_odds_parsing_and_alerts():
    current = parse_odds("1 2.0\n2 5.5", "単勝")
    rows, alerts = compare_odds({"単勝 1": 3.0}, current, 1.5)
    assert current["単勝 1"] == 2.0
    assert any("低下" in a for a in alerts)


def test_parse_popular_odds_snapshot_from_compact_tables():
    text = """
    単勝・複勝
    1 3 5 イガッチ 5.9 2.2 - 2.5
    2 3 4 マジックサンズ 6.4 2.5 - 3.0
    馬連・ワイド
    1 5 - 8 15.3 9.6 - 10.1
    2 5 - 14 16.4 10.2 - 10.8
    馬単
    1 5 > 8 28.3
    3連複
    1 5 - 12 - 14 46.6
    3連単
    1 11 > 12 > 4 73.1
    """
    odds = parse_popular_odds_snapshot(text)
    assert odds["単勝 5"] == 5.9
    assert odds["複勝 5"] == 2.35
    assert odds["馬連 5-8"] == 15.3
    assert odds["ワイド 5-8"] == 10.1
    assert odds["馬単 5-8"] == 28.3
    assert odds["3連複 5-12-14"] == 46.6
    assert odds["3連単 11-12-4"] == 73.1


def test_fetch_netkeiba_popular_odds_from_html_tables(monkeypatch):
    html = """
    <html><body>
    <section><h2>単勝・複勝</h2>
      <table>
        <tr><th>人気</th><th>枠</th><th>馬番</th><th>馬名</th><th>単勝オッズ</th><th>複勝オッズ</th></tr>
        <tr><td>1</td><td>3</td><td>5</td><td>イガッチ</td><td>5.9</td><td>2.2 - 2.5</td></tr>
      </table>
    </section>
    <section><h2>馬連・ワイド</h2>
      <table>
        <tr><th>人気</th><th>組み合わせ</th><th>オッズ</th><th>ワイド・オッズ</th></tr>
        <tr><td>1</td><td>5 - 8</td><td>15.3</td><td>9.6 - 10.1</td></tr>
      </table>
    </section>
    <section><h2>馬単</h2>
      <table>
        <tr><th>人気</th><th>組み合わせ</th><th>オッズ</th></tr>
        <tr><td>1</td><td>5 > 8</td><td>28.3</td></tr>
      </table>
    </section>
    <section><h2>3連複</h2>
      <table>
        <tr><th>人気</th><th>組み合わせ</th><th>オッズ</th></tr>
        <tr><td>1</td><td>5 - 12 - 14</td><td>46.6</td></tr>
      </table>
    </section>
    <section><h2>3連単</h2>
      <table>
        <tr><th>人気</th><th>組み合わせ</th><th>オッズ</th></tr>
        <tr><td>1</td><td>11 > 12 > 4</td><td>73.1</td></tr>
      </table>
    </section>
    </body></html>
    """

    class DummyResponse:
        text = html
        def raise_for_status(self): return None

    import requests
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: DummyResponse())
    odds, transcript = fetch_netkeiba_popular_odds("https://race.netkeiba.com/odds/index.html?race_id=202606280211")
    assert odds["単勝 5"] == 5.9
    assert odds["複勝 5"] == 2.35
    assert odds["馬連 5-8"] == 15.3
    assert odds["ワイド 5-8"] == 10.1
    assert odds["馬単 5-8"] == 28.3
    assert odds["3連複 5-12-14"] == 46.6
    assert odds["3連単 11-12-4"] == 73.1
    assert "単勝" in transcript and "3連単" in transcript


def test_prediction_archive(tmp_path):
    state = {"race_info": {"日付": "2026-06-20", "競馬場": "東京", "レース番号": "11", "レース名": "テストS"}}
    path = archive_prediction(state, "テスト予想", str(tmp_path))
    saved = list_predictions(str(tmp_path))
    assert path.exists()
    assert saved[0]["title"] == "テスト予想"


def test_pdf_preprocessing_renders_and_extracts_text():
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Tokyo 11R Sample Stakes 16 horses")
    pdf_bytes = doc.tobytes()
    doc.close()
    visuals, text, notes = _prepare_visual_inputs([("race.pdf", "application/pdf", pdf_bytes)])
    assert visuals and visuals[0][1] == "image/jpeg"
    assert "Tokyo 11R" in text
    assert not notes


def test_fixed_layout_profile_crops_named_regions(tmp_path):
    import fitz
    profile_path = tmp_path / "profiles.json"
    profile = save_layout_profile("固定画面", [0, 0, 1, .2], [0, .2, 1, 1], str(profile_path))
    assert load_layout_profiles(str(profile_path))["固定画面"] == profile
    doc = fitz.open(); page = doc.new_page(); page.insert_text((72, 72), "Race header"); pdf_bytes = doc.tobytes(); doc.close()
    visuals, _, notes = _prepare_visual_inputs([("fixed.pdf", "application/pdf", pdf_bytes)], profile)
    names = [item[0] for item in visuals]
    assert any("race_header" in name for name in names)
    assert any("horse_table" in name for name in names)
    assert any("固定画面" in note for note in notes)


def test_local_api_key_file_is_private_and_deletable(tmp_path):
    path = tmp_path / "secrets.toml"
    assert save_local_api_key('sk-test"quoted', str(path))
    assert 'OPENAI_API_KEY' in path.read_text(encoding="utf-8")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert delete_local_api_key(str(path)) and not path.exists()


def test_running_style_inference_from_corner_positions():
    assert infer_running_style([[1, 1, 1], [2, 2, 1], [1, 1]])[0] == "逃げ"
    assert infer_running_style([[4, 3, 2], [5, 4, 3]])[0] == "先行"
    assert infer_running_style([[8, 7, 5], [10, 8, 6]])[0] == "差し"
    assert infer_running_style([[14, 12, 8], [12, 10, 7]])[0] == "追込"


def test_past_lap_trend_analysis_finds_matching_runner_types():
    horses = [
        {"馬番": 1, "馬名": "逃げA", "脚質": "逃げ", "人気": 2, "単勝オッズ": 5.0, "過去走テキスト": "東01/01 2勝 芝1800 5 左A 良 16頭 1:46.0 1 1 1 1 35.0 H 36.2"},
        {"馬番": 2, "馬名": "逃げB", "脚質": "逃げ", "人気": 4, "単勝オッズ": 9.0, "過去走テキスト": "東02/01 2勝 芝1800 8 左A 良 16頭 1:47.0 1 1 2 2 34.9 H 37.0"},
        {"馬番": 3, "馬名": "差しC", "脚質": "差し", "人気": 3, "単勝オッズ": 7.0, "過去走テキスト": "東03/01 2勝 芝1800 1 左A 良 16頭 1:45.2 10 9 8 3 35.1 H 33.5 / 東04/01 3勝 芝2000 2 左B 良 15頭 1:58.8 9 8 7 2 36.0 M 33.7"},
    ]
    trend = analyze_race_trends(horses, {"芝/ダート": "芝", "距離": "1800", "馬場": "良"})
    assert trend["想定ペース"] == "ハイ" and trend["有利脚質"] == "差し・追込"
    assert trend["過去走サンプル数"] == 4 and trend["ペース内訳"]["H"] == 3
    assert trend["適合馬"][0]["馬番"] == 3 and trend["適合馬"][0]["判定"] == "合いそう"
    scores, comments, _ = heuristic_evaluations(horses, trend_analysis=trend)
    assert scores["3"]["展開利"] > scores["1"]["展開利"]
    assert "傾向適合指数" in comments["3"]


def test_jra_historical_pages_are_parsed_and_blended_without_network():
    month_tokens = _available_month_tokens('<script>objParam["2606"]="EA";</script>')
    assert month_tokens[(2026, 6)] == "pw01skl10202606/EA"
    day_html = """
    <table><tr><th>レース名</th><th>距離</th><th>馬場</th><th>出走頭数</th></tr>
    <tr><td>テストステークス</td><td>1,800メートル</td><td>芝</td><td>16頭</td></tr></table>
    <script>var a='pw01sde1005202503061120250621/AA';</script>
    """
    races = _day_races(day_html, "東京", "3回東京6日")
    assert races[0]["日付"] == "2025-06-21" and races[0]["距離"] == 1800 and races[0]["芝/ダート"] == "芝"
    result_html = """
    <div>芝 良 タイム ハロンタイム 12.5 - 11.0 - 11.5 - 12.0 - 11.8 - 11.4 - 11.2 - 11.6 - 12.0 上り 4F 46.2 - 3F 34.8</div>
    <table><tr><th>着順</th><th>馬番</th><th>単勝 人気</th></tr><tr><td>1</td><td>7</td><td>3</td></tr></table>
    """
    detail = _result_detail(result_html, races[0])
    aggregate = aggregate_history([detail], "テスト")
    assert detail["前半3F"] == 35.0 and detail["上がり3F"] == 34.8 and aggregate["サンプル数"] == 1
    local = {"適合馬": [{"馬番": 1, "脚質": "差し", "適合指数": 60, "判定": "条件付き", "根拠": "ローカル"}]}
    web = {"同名レース": {"サンプル数": 2, "ペース内訳": {"S": 0, "M": 0, "H": 2}}, "同条件レース": {"サンプル数": 8, "ペース内訳": {"S": 1, "M": 2, "H": 5}}}
    blended = merge_web_history(local, web)
    assert blended["適合馬"][0]["適合指数"] == 67 and blended["Web傾向"]["想定ペース"] == "ハイ"


def test_horse_analysis_columns_include_pedigree_trio():
    pedigree = HORSE_COLUMNS[HORSE_COLUMNS.index("父"):HORSE_COLUMNS.index("母父") + 1]
    assert pedigree == ["父", "母", "母父"]


def test_local_evaluation_can_continue_without_api():
    horses, _ = sample()
    scores, comments, risks = heuristic_evaluations(horses)
    assert len(scores) == len(horses)
    assert set(scores["1"]) == set(SCORE_KEYS)
    assert all(1 <= value <= 5 for horse_scores in scores.values() for value in horse_scores.values())
    assert comments["1"] and risks["1"]


def test_prediction_policy_is_saved_locally_and_added_to_ai_prompt(tmp_path):
    path = tmp_path / "prediction_profile.json"
    save_prediction_profile("着順よりもレース内容を重視", str(path))
    profile = load_prediction_profile(str(path))
    assert profile["policy"] == "着順よりもレース内容を重視"
    assert profile["policy"] in _evaluation_prompt([], {}, profile["policy"])


def test_manual_score_corrections_become_prediction_tendencies(tmp_path):
    path = tmp_path / "prediction_profile.json"
    original = {"1": {key: 3 for key in SCORE_KEYS}}
    corrected = {"1": {**original["1"], "妙味": 5, "騎手評価": 2}}
    profile = learn_prediction_adjustments(original, corrected, str(path))
    prompt = prediction_policy_prompt(profile)
    assert profile["learning_samples"] == 1
    assert profile["adjustments"]["妙味"] == 2
    assert "妙味:+2.00点" in prompt and "騎手評価:-1.00点" in prompt
    local_scores, _, _ = heuristic_evaluations([{"馬番": 1, "人気": 8, "単勝オッズ": 3}], profile)
    assert local_scores["1"]["妙味"] == 5


def test_race_result_feedback_is_parsed_and_counted_once(tmp_path):
    assert parse_finish_order("1着 7番\n2着 8番\n3着 6番") == ["7", "8", "6"]
    assert parse_finish_order("7-8-6") == ["7", "8", "6"]
    path = tmp_path / "prediction_profile.json"
    horses, scores = sample()
    state = {
        "race_info": {"日付": "2026-06-21", "競馬場": "東京", "レース番号": "11", "レース名": "テストS"},
        "final_scores": scores,
        "score_results": calculate_scores(horses, scores, {key: 1 for key in SCORE_KEYS}),
    }
    feedback = {"確定着順": "1着 2番\n2着 1番\n3着 3番", "外れた見解": "逃げ馬を軽視", "次回への学び": "展開利を再確認", "実購入額": 3000, "実払戻額": 5400}
    first = learn_from_race_result(state, feedback, str(path))
    second = learn_from_race_result(state, feedback, str(path))
    assert first["result_learning"]["reviews"] == second["result_learning"]["reviews"] == 1
    assert first["result_learning"]["stake_total"] == second["result_learning"]["stake_total"] == 3000
    assert first["result_learning"]["return_total"] == second["result_learning"]["return_total"] == 5400
    assert first["result_learning"]["profit_total"] == second["result_learning"]["profit_total"] == 2400
    assert first["result_learning"]["hit_count"] == second["result_learning"]["hit_count"] == 1
    assert any("展開利" in lesson for lesson in first["result_learning"]["lessons"])


def test_external_betting_journal_is_added_to_ai_prompt(tmp_path):
    path = tmp_path / "prediction_profile.json"
    profile = add_betting_journal_entry({
        "レース": "福島11R",
        "情報源": "netkeiba",
        "券種": "ワイド",
        "買い目": "5-8 1000円",
        "購入額": 1000,
        "払戻額": 3200,
        "買った理由": "本命信頼も単勝妙味が薄く相手穴へ流した",
        "振り返り": "相手穴の拾い方は良かった",
        "次回への学び": "小回り重馬場は位置取りを重視",
    }, str(path))
    journal = profile["betting_journal"]
    assert journal["count"] == 1
    assert journal["stake_total"] == 1000
    assert journal["return_total"] == 3200
    assert journal["profit_total"] == 2200
    prompt = prediction_policy_prompt(profile)
    assert "外部買い目ノート1件" in prompt
    assert "小回り重馬場は位置取りを重視" in prompt


def test_betting_journal_learns_odds_calibration(tmp_path):
    path = tmp_path / "prediction_profile.json"
    profile = add_betting_journal_entry({
        "レース": "京都11R",
        "券種": "馬連",
        "買い目": "馬連 1-3 1000円",
        "購入額": 1000,
        "払戻額": 0,
        "単勝オッズメモ": "1 2.4\n3 7.8",
        "実オッズメモ": "馬連 1-3 28.0",
        "振り返り": "実際の馬連は単勝支持率からの推定より高かった",
    }, str(path))
    calibration = profile["odds_calibration"]
    assert calibration["samples"] == 1
    assert calibration["ticket_multipliers"]["馬連"]["multiplier"] > 1.0
    assert "馬連" in prediction_policy_prompt(profile)


def test_parse_single_odds_text_accepts_simple_lines():
    assert parse_single_odds_text("1番 ランスオブカオス 2.4\n3 キープカルム 7.8") == {"1": 2.4, "3": 7.8}


def test_betting_journal_keeps_horses_and_infers_ticket_type(tmp_path):
    path = tmp_path / "prediction_profile.json"
    profile = add_betting_journal_entry({
        "レース": "函館11R",
        "出走馬": "5 ファイアンクランツ\n8 センツブラッド",
        "買い目": "ワイド 5-8 1000円",
        "購入額": 1000,
        "払戻額": 0,
        "結果": "不的中",
        "振り返り": "軸は良かったが相手を広げすぎた",
    }, str(path))
    entry = profile["betting_journal"]["entries"][-1]
    assert entry["出走馬"].startswith("5 ファイアンクランツ")
    assert entry["券種"] == "ワイド"
    assert "出走馬:" in profile["betting_journal"]["patterns"][-1]


def test_betting_journal_entry_can_be_updated_without_incrementing_count(tmp_path):
    path = tmp_path / "prediction_profile.json"
    add_betting_journal_entry({
        "レース": "京都11R",
        "券種": "馬連",
        "買い目": "馬連 1-3 1000円",
        "購入額": 1000,
        "払戻額": 0,
        "単勝オッズメモ": "1 2.4\n3 7.8",
        "振り返り": "結果待ち",
    }, str(path))
    profile = update_betting_journal_entry(0, {
        "払戻額": 28000,
        "結果": "的中",
        "実オッズメモ": "馬連 1-3 28.0",
        "振り返り": "払戻を追記",
    }, str(path))
    journal = profile["betting_journal"]
    assert journal["count"] == 1
    assert journal["return_total"] == 28000
    assert journal["profit_total"] == 27000
    assert journal["hit_count"] == 1
    assert journal["entries"][0]["収支"] == 27000
    assert profile["odds_calibration"]["samples"] == 1


def test_external_betting_journal_bulk_import_and_listing(tmp_path):
    path = tmp_path / "prediction_profile.json"
    profile, report = add_betting_journal_entries([
        {"レース": "A", "券種": "馬連", "買い目": "1-2", "購入額": 500, "払戻額": 0, "振り返り": "相手抜け"},
        {"レース": "B", "券種": "3連複", "買い目": "1-2-3", "購入額": "1,000", "払戻額": "4,500", "次回への学び": "軸は良かった"},
        {},
    ], str(path))
    assert report["取込"] == 2 and report["スキップ"] == 1
    assert profile["betting_journal"]["count"] == 2
    assert profile["betting_journal"]["stake_total"] == 1500
    assert profile["betting_journal"]["return_total"] == 4500
    entries = betting_journal_entries(str(path))
    assert [entry["レース"] for entry in entries] == ["B", "A"]


def test_parse_betting_history_text_from_pasted_rows():
    text = """
    2026/06/28 函館 11R 函館記念
    ワイド 5-8 購入 1,000円 払戻 3,200円
    馬連 5-14 金額 500円 払戻金 0円
    3連複 5-8-14 投票 300円
    """
    rows, notes = parse_betting_history_text(text, "JRA/IPAT")
    assert len(rows) == 3
    assert rows[0]["レース"].startswith("2026/06/28 函館 11R")
    assert rows[0]["券種"] == "ワイド"
    assert rows[0]["買い目"] == "ワイド 5-8"
    assert rows[0]["購入額"] == 1000
    assert rows[0]["払戻額"] == 3200
    assert rows[2]["券種"] == "3連複"
    assert rows[2]["買い目"] == "3連複 5-8-14"
    assert isinstance(notes, list)


def test_parse_betting_history_text_from_html_table():
    html = """
    <table>
      <tr><th>日付</th><th>レース</th><th>券種</th><th>買い目</th><th>購入額</th><th>払戻額</th></tr>
      <tr><td>2026/06/28</td><td>福島11R ラジオNIKKEI賞</td><td>馬単</td><td>5&gt;8</td><td>1,000円</td><td>4,500円</td></tr>
    </table>
    """
    rows, _ = parse_betting_history_text(html, "netkeiba My収支")
    assert len(rows) == 1
    assert rows[0]["情報源"] == "netkeiba My収支"
    assert rows[0]["券種"] == "馬単"
    assert rows[0]["買い目"] == "馬単 5>8"
    assert rows[0]["購入額"] == 1000
    assert rows[0]["払戻額"] == 4500


def test_result_history_import_skips_incomplete_and_deduplicates(tmp_path):
    path = tmp_path / "prediction_profile.json"
    horses, scores = sample()
    completed = {
        "race_info": {"日付": "2026-06-21", "競馬場": "東京", "レース番号": "11", "レース名": "履歴テスト"},
        "final_scores": scores,
        "score_results": calculate_scores(horses, scores, {key: 1 for key in SCORE_KEYS}),
        "result_feedback": {"確定着順": "1着 2番\n2着 1番\n3着 3番"},
    }
    profile, report = learn_from_result_history([completed, completed, {"race_info": {}}], str(path))
    assert profile["result_learning"]["reviews"] == 1
    assert report["新規反映"] == 1 and report["重複"] == 1 and report["結果不足"] == 1


def test_jra_html_odds_parsing_without_api_key():
    document = """
    <a onclick="return doAction('/JRADB/accessO.html','race-token/AA');"><img alt="11レース"></a>
    <table><thead><tr><th>馬番</th><th>馬名</th><th>単勝</th><th>複勝（3着払い）</th></tr></thead>
    <tbody><tr><td>1</td><td>テスト馬</td><td>4.2</td><td>1.5-2.1</td></tr></tbody></table>
    """
    actions = _anchor_actions(document, "/JRADB/accessO.html")
    assert actions == [(" 11レース", "race-token/AA")]
    odds = _single_odds(_tables(document))
    assert odds == {"単勝 1": 4.2, "複勝 1": 1.5}
    assert _race_identity({"競馬場": "東京", "開催回": "3", "開催日": "6", "レース番号": "11"}) == ("3回東京6日", 11)
