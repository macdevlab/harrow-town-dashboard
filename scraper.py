"""
HTCC Diagnostic v3 — checks correct team IDs and fetches Saturday scorecard data
"""
import os, sys, json, requests
from datetime import datetime, timedelta

API_BASE = "https://www.play-cricket.com/api/v2"
API_KEY = os.environ.get("PLAYCRICKET_API_KEY", "")
SITE_ID = "3199"

# Correct team IDs from v2 diagnostic
TEAMS = {
    "1st XI": "140947",  # NOT 213914 (Sunday 1st XI)
    "2nd XI": "140948",
    "3rd XI": "29087",
    "4th XI": "162815",
}

if not API_KEY:
    print("ERROR: Set PLAYCRICKET_API_KEY first")
    sys.exit(1)

print(f"Checking Saturday 9 May 2026 matches...\n")

for label, tid in TEAMS.items():
    print(f"{'='*60}")
    print(f"{label} (ID: {tid})")
    print(f"{'='*60}")

    # Get matches for this team on 9 May weekend
    try:
        r = requests.get(f"{API_BASE}/result_summary.json", params={
            "api_token": API_KEY, "site_id": SITE_ID,
            "season": 2026, "team_id": tid,
            "from_match_date": "08/05/2026", "end_match_date": "11/05/2026"
        }, timeout=30)
        rs = r.json().get("result_summary", [])
        print(f"  result_summary: {len(rs)} match(es)")
        for m in rs:
            print(f"    ID:{m.get('id')} | {m.get('match_date')} | Status:{m.get('status')}")
            print(f"    {m.get('home_team_name','?')} vs {m.get('away_team_name','?')}")
            print(f"    Result: {m.get('result_description','?')}")
    except Exception as e:
        print(f"  result_summary FAILED: {e}")

    # Also check matches endpoint
    try:
        r2 = requests.get(f"{API_BASE}/matches.json", params={
            "api_token": API_KEY, "site_id": SITE_ID,
            "season": 2026, "team_id": tid
        }, timeout=30)
        ms = r2.json().get("matches", [])
        # Filter to 9 May weekend
        weekend = [m for m in ms if m.get("match_date","") in ["09/05/2026","10/05/2026","11/05/2026"]]
        print(f"  matches.json (9-11 May): {len(weekend)} match(es)")
        for m in weekend:
            mid = m.get("id")
            print(f"    ID:{mid} | {m.get('match_date')} | Status:{m.get('status')}")

            # Fetch scorecard detail
            print(f"    Fetching scorecard...")
            r3 = requests.get(f"{API_BASE}/match_detail.json", params={
                "api_token": API_KEY, "match_id": mid
            }, timeout=30)
            detail = r3.json().get("match_details", [{}])
            if detail:
                d = detail[0]
                print(f"    Home: {d.get('home_team_name','?')}")
                print(f"    Away: {d.get('away_team_name','?')}")
                print(f"    Result: {d.get('result_description','N/A')}")
                innings = d.get("innings", [])
                print(f"    Innings count: {len(innings)}")
                if innings:
                    for i, inn in enumerate(innings):
                        bat = inn.get("bat", [])
                        bowl = inn.get("bowl", [])
                        team_bat = inn.get("team_batting_name", "?")
                        print(f"      Inn {i+1}: {team_bat} - {len(bat)} batters, {len(bowl)} bowlers")
                        if bat:
                            print(f"        First batter: {bat[0].get('batsman_name','?')} - {bat[0].get('runs','?')} runs")
                else:
                    print(f"    >>> NO INNINGS DATA - scorecard not submitted yet")
            else:
                print(f"    >>> NO MATCH DETAIL returned")
    except Exception as e:
        print(f"  matches.json FAILED: {e}")

    print()

print("DONE")
