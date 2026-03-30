"""
Harrow Town CC — Automated Dashboard Scraper
=============================================
Connects to the Play-Cricket API v2, fetches scorecards for all 4 senior XIs,
calculates POTM points using the club's scoring system, and outputs JSON data
for the dashboard frontend.

Club ID: 3199
Site: harrowtown.play-cricket.com

Usage:
    python scraper.py                    # Process latest week
    python scraper.py --full-season      # Rebuild entire season data
    python scraper.py --match-id 12345   # Process a specific match

Requires:
    pip install requests python-dateutil

Environment variables:
    PLAYCRICKET_API_KEY  — Your Play-Cricket API token
    PLAYCRICKET_SITE_ID  — Your site ID (default: 3199 for Harrow Town)
"""

import os
import sys
import json
import math
import logging
import argparse
from datetime import datetime, timedelta
from dateutil import parser as dateparser
import requests

# ─── Configuration ───────────────────────────────────────────────────────────

API_BASE = "https://play-cricket.com/api/v2"
SITE_ID = os.environ.get("PLAYCRICKET_SITE_ID", "3199")
API_KEY = os.environ.get("PLAYCRICKET_API_KEY", "")

SEASON = datetime.now().year

# Team names to look for in the API (adjust if Play-Cricket uses different labels)
SENIOR_TEAMS = ["1st XI", "2nd XI", "3rd XI", "4th XI"]

# Output paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
WEEKLY_FILE = os.path.join(DATA_DIR, "weekly_potw.json")
SEASON_FILE = os.path.join(DATA_DIR, "season_cumulative.json")
DASHBOARD_FILE = os.path.join(DATA_DIR, "dashboard.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("htcc_scraper")


# ─── POTM Points System ─────────────────────────────────────────────────────
# All thresholds are configurable here (mirrors calc_awards.py)

POINTS = {
    # Batting
    "per_run": 1,
    "per_four": 1,
    "per_six": 2,
    "milestone_25": 5,
    "milestone_50": 10,
    "milestone_100": 25,
    "not_out": 5,
    "duck": -3,
    "sr_150_bonus": 10,       # SR >= 150, min 10 balls
    "sr_100_bonus": 5,        # SR >= 100, min 10 balls
    "sr_50_penalty": -5,      # SR < 50,  min 10 balls
    "sr_min_balls": 10,

    # Bowling
    "per_wicket": 20,
    "haul_3w": 5,
    "haul_5w": 20,
    "per_maiden": 3,
    "economy_lt4": 15,        # Economy < 4, min 4 overs
    "economy_lt5": 10,        # Economy < 5, min 4 overs
    "economy_lt6": 5,         # Economy < 6, min 4 overs
    "economy_gte10": -5,      # Economy >= 10, min 4 overs
    "econ_min_overs": 4,

    # Fielding
    "catch": 10,
    "run_out": 10,
    "stumping": 12,
}


# ─── API Helpers ─────────────────────────────────────────────────────────────

def api_get(endpoint, params=None):
    """Make an authenticated GET request to the Play-Cricket API."""
    if not API_KEY:
        logger.error("PLAYCRICKET_API_KEY not set. Please set the environment variable.")
        sys.exit(1)

    url = f"{API_BASE}/{endpoint}"
    all_params = {"api_token": API_KEY}
    if params:
        all_params.update(params)

    logger.info(f"API call: {endpoint} | params: {params}")
    resp = requests.get(url, params=all_params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_teams():
    """Fetch all teams for the site and return a dict mapping team name -> team_id."""
    data = api_get("teams.json", {"site_id": SITE_ID})
    teams = {}
    for team in data.get("teams", []):
        name = team.get("team_name", "")
        for senior in SENIOR_TEAMS:
            if senior.lower() in name.lower():
                teams[senior] = str(team["id"])
                logger.info(f"Found team: {name} -> ID {team['id']}")
    return teams


def get_matches(season=None, team_id=None, from_date=None, end_date=None):
    """Fetch match summaries. Returns list of match dicts."""
    params = {"site_id": SITE_ID, "season": season or SEASON}
    if team_id:
        params["team_id"] = team_id
    if from_date:
        params["from_match_date"] = from_date
    if end_date:
        params["end_match_date"] = end_date
    data = api_get("result_summary.json", params)
    return data.get("result_summary", [])


def get_match_detail(match_id):
    """Fetch full scorecard for a single match."""
    data = api_get("match_detail.json", {"match_id": match_id})
    return data.get("match_details", [{}])[0] if data.get("match_details") else {}


# ─── Scorecard Parsing ───────────────────────────────────────────────────────

def parse_overs_to_float(overs_str):
    """Convert overs like '7.3' to a float for calculations.
    In cricket, '7.3' means 7 overs and 3 balls (not 7.3 overs).
    Returns actual overs as a float (7 + 3/6 = 7.5).
    """
    try:
        parts = str(overs_str).split(".")
        full_overs = int(parts[0])
        balls = int(parts[1]) if len(parts) > 1 else 0
        return full_overs + balls / 6.0
    except (ValueError, IndexError):
        return 0.0


def extract_fielding_from_dismissals(innings_data, our_team_players):
    """
    Parse dismissal descriptions to extract catches, run-outs, and stumpings.
    Play-Cricket formats:
        'ct FirstName LastName' -> catch
        'ct & bwld' -> caught and bowled (credit fielder = bowler)
        'run out (FirstName LastName)' or 'run out FirstName LastName'
        'st FirstName LastName' -> stumping
    Returns dict: {player_name: {"catches": n, "run_outs": n, "stumpings": n}}
    """
    fielding = {}

    for batting_entry in innings_data:
        how_out = str(batting_entry.get("how_out", "")).strip().lower()
        fielder_name = str(batting_entry.get("fielder_name", "")).strip()

        if not how_out or how_out in ("not out", "dnb", "did not bat", "absent", "retired"):
            continue

        # Determine fielding action
        if "ct" in how_out or "caught" in how_out:
            if fielder_name:
                fielding.setdefault(fielder_name, {"catches": 0, "run_outs": 0, "stumpings": 0})
                fielding[fielder_name]["catches"] += 1

        elif "run out" in how_out:
            if fielder_name:
                fielding.setdefault(fielder_name, {"catches": 0, "run_outs": 0, "stumpings": 0})
                fielding[fielder_name]["run_outs"] += 1

        elif "st " in how_out or "stumped" in how_out:
            if fielder_name:
                fielding.setdefault(fielder_name, {"catches": 0, "run_outs": 0, "stumpings": 0})
                fielding[fielder_name]["stumpings"] += 1

    return fielding


def calc_batting_points(batting):
    """Calculate POTM batting points for a single batting entry."""
    runs = int(batting.get("runs", 0) or 0)
    fours = int(batting.get("fours", 0) or 0)
    sixes = int(batting.get("sixes", 0) or 0)
    balls = int(batting.get("balls", 0) or 0)
    how_out = str(batting.get("how_out", "")).strip().lower()
    is_not_out = how_out in ("not out", "retired not out", "retired hurt")
    is_duck = runs == 0 and not is_not_out and how_out not in ("dnb", "did not bat", "absent", "")

    pts = 0
    pts += runs * POINTS["per_run"]
    pts += fours * POINTS["per_four"]
    pts += sixes * POINTS["per_six"]

    # Milestone bonuses (cumulative: 100 includes 50 and 25 bonuses)
    if runs >= 100:
        pts += POINTS["milestone_100"] + POINTS["milestone_50"] + POINTS["milestone_25"]
    elif runs >= 50:
        pts += POINTS["milestone_50"] + POINTS["milestone_25"]
    elif runs >= 25:
        pts += POINTS["milestone_25"]

    if is_not_out:
        pts += POINTS["not_out"]
    if is_duck:
        pts += POINTS["duck"]

    # Strike rate bonuses (min 10 balls faced)
    if balls >= POINTS["sr_min_balls"]:
        sr = (runs / balls) * 100
        if sr >= 150:
            pts += POINTS["sr_150_bonus"]
        elif sr >= 100:
            pts += POINTS["sr_100_bonus"]
        elif sr < 50:
            pts += POINTS["sr_50_penalty"]

    return pts


def calc_bowling_points(bowling):
    """Calculate POTM bowling points for a single bowling entry."""
    wickets = int(bowling.get("wickets", 0) or 0)
    maidens = int(bowling.get("maidens", 0) or 0)
    runs = int(bowling.get("runs", 0) or 0)
    overs_str = str(bowling.get("overs", "0") or "0")
    overs_float = parse_overs_to_float(overs_str)

    pts = 0
    pts += wickets * POINTS["per_wicket"]

    # Haul bonuses
    if wickets >= 5:
        pts += POINTS["haul_5w"] + POINTS["haul_3w"]
    elif wickets >= 3:
        pts += POINTS["haul_3w"]

    pts += maidens * POINTS["per_maiden"]

    # Economy bonuses (min 4 overs)
    if overs_float >= POINTS["econ_min_overs"]:
        economy = runs / overs_float if overs_float > 0 else 99
        if economy < 4:
            pts += POINTS["economy_lt4"]
        elif economy < 5:
            pts += POINTS["economy_lt5"]
        elif economy < 6:
            pts += POINTS["economy_lt6"]
        elif economy >= 10:
            pts += POINTS["economy_gte10"]

    return pts


def calc_fielding_points(fielding_stats):
    """Calculate POTM fielding points from a fielding dict."""
    pts = 0
    pts += fielding_stats.get("catches", 0) * POINTS["catch"]
    pts += fielding_stats.get("run_outs", 0) * POINTS["run_out"]
    pts += fielding_stats.get("stumpings", 0) * POINTS["stumping"]
    return pts


# ─── Match Processing ────────────────────────────────────────────────────────

def identify_our_innings(match_detail, team_name):
    """
    Given a match detail JSON, figure out which innings belong to our team.
    Returns (our_batting_innings, our_bowling_innings, opponent_name, result).
    
    The Play-Cricket match_detail contains innings arrays. Each innings has
    a 'team_batting_name' or similar field. We match against our team name.
    """
    innings = match_detail.get("innings", [])
    home_team = match_detail.get("home_team_name", "")
    away_team = match_detail.get("away_team_name", "")
    result = match_detail.get("result_description", "")

    # Determine if we are home or away
    is_home = "harrow town" in home_team.lower()
    our_team_label = home_team if is_home else away_team
    opponent = away_team if is_home else home_team

    our_batting = []
    our_bowling = []

    for inn in innings:
        team_batting = inn.get("team_batting_name", "")
        if "harrow town" in team_batting.lower():
            our_batting.append(inn)
        else:
            # If the other team is batting, we are bowling
            our_bowling.append(inn)

    return our_batting, our_bowling, opponent, result


def process_match(match_detail, team_label):
    """
    Process a single match scorecard and return per-player POTM data.
    Returns dict: {
        "team": "1st XI",
        "opponent": "Ealing CC",
        "result": "Won by 5 wickets",
        "date": "2026-06-28",
        "players": {
            "Player Name": {
                "batting_pts": int,
                "bowling_pts": int,
                "fielding_pts": int,
                "total_pts": int,
                "batting": {runs, balls, fours, sixes, how_out, ...},
                "bowling": {overs, maidens, runs, wickets, ...},
                "fielding": {catches, run_outs, stumpings},
            }
        },
        "potm_winner": {"name": str, "total_pts": int, "summary": str},
        "best_batter": {...},
        "best_bowler": {...},
        "best_fielder": {...},
    }
    """
    our_batting_innings, our_bowling_innings, opponent, result = identify_our_innings(match_detail, team_label)

    players = {}

    # ── Process our batting ──
    for inn in our_batting_innings:
        for entry in inn.get("bat", []):
            name = entry.get("batsman_name", "").strip()
            if not name:
                continue
            how_out = str(entry.get("how_out", "")).strip()
            if how_out.lower() in ("dnb", "did not bat", ""):
                continue

            bat_pts = calc_batting_points(entry)
            players.setdefault(name, {
                "batting_pts": 0, "bowling_pts": 0, "fielding_pts": 0, "total_pts": 0,
                "batting": {}, "bowling": {}, "fielding": {"catches": 0, "run_outs": 0, "stumpings": 0}
            })
            players[name]["batting_pts"] += bat_pts
            players[name]["batting"] = {
                "runs": int(entry.get("runs", 0) or 0),
                "balls": int(entry.get("balls", 0) or 0),
                "fours": int(entry.get("fours", 0) or 0),
                "sixes": int(entry.get("sixes", 0) or 0),
                "how_out": entry.get("how_out", ""),
                "position": entry.get("position", ""),
            }

    # ── Process our bowling ──
    for inn in our_bowling_innings:
        for entry in inn.get("bowl", []):
            name = entry.get("bowler_name", "").strip()
            if not name:
                continue
            bowl_pts = calc_bowling_points(entry)
            players.setdefault(name, {
                "batting_pts": 0, "bowling_pts": 0, "fielding_pts": 0, "total_pts": 0,
                "batting": {}, "bowling": {}, "fielding": {"catches": 0, "run_outs": 0, "stumpings": 0}
            })
            players[name]["bowling_pts"] += bowl_pts
            players[name]["bowling"] = {
                "overs": entry.get("overs", "0"),
                "maidens": int(entry.get("maidens", 0) or 0),
                "runs": int(entry.get("runs", 0) or 0),
                "wickets": int(entry.get("wickets", 0) or 0),
                "wides": int(entry.get("wides", 0) or 0),
                "no_balls": int(entry.get("no_balls", 0) or 0),
            }

    # ── Process fielding from opposition batting (our fielding) ──
    for inn in our_bowling_innings:
        fielding_data = extract_fielding_from_dismissals(inn.get("bat", []), players.keys())
        for name, stats in fielding_data.items():
            players.setdefault(name, {
                "batting_pts": 0, "bowling_pts": 0, "fielding_pts": 0, "total_pts": 0,
                "batting": {}, "bowling": {}, "fielding": {"catches": 0, "run_outs": 0, "stumpings": 0}
            })
            players[name]["fielding"]["catches"] += stats["catches"]
            players[name]["fielding"]["run_outs"] += stats["run_outs"]
            players[name]["fielding"]["stumpings"] += stats["stumpings"]

    # ── Calculate fielding points and totals ──
    for name, data in players.items():
        data["fielding_pts"] = calc_fielding_points(data["fielding"])
        data["total_pts"] = data["batting_pts"] + data["bowling_pts"] + data["fielding_pts"]

    # ── Determine best performers ──
    def best_by(key):
        if not players:
            return {"name": "N/A", "pts": 0}
        top = max(players.items(), key=lambda x: x[1][key])
        return {"name": top[0], "pts": top[1][key], **top[1]}

    potm = best_by("total_pts")
    best_bat = best_by("batting_pts")
    best_bowl = best_by("bowling_pts")
    best_field = best_by("fielding_pts")

    match_date = match_detail.get("match_date", "")

    # Determine if won or lost
    result_lower = result.lower()
    won = "harrow town" in result_lower and "won" in result_lower
    if not won:
        # Check if the result says the OTHER team won
        won = False  # Default to lost/drawn

    return {
        "team": team_label,
        "opponent": opponent,
        "result": result,
        "won": won,
        "date": match_date,
        "players": players,
        "potm_winner": {"name": potm["name"], "total_pts": potm.get("total_pts", 0)},
        "best_batter": {"name": best_bat["name"], "pts": best_bat.get("batting_pts", 0)},
        "best_bowler": {"name": best_bowl["name"], "pts": best_bowl.get("bowling_pts", 0)},
        "best_fielder": {"name": best_field["name"], "pts": best_field.get("fielding_pts", 0)},
    }


# ─── Season Aggregation ─────────────────────────────────────────────────────

def update_season_cumulative(season_data, match_result):
    """
    Update cumulative season stats with data from a single match.
    season_data: dict of {player_name: {team, innings, runs, ...cumulative stats}}
    """
    team = match_result["team"]
    for name, data in match_result["players"].items():
        if name not in season_data:
            season_data[name] = {
                "team": team,
                "innings": 0,
                "runs": 0, "balls_faced": 0, "fours": 0, "sixes": 0,
                "not_outs": 0, "highest_score": "0", "fifties": 0, "hundreds": 0,
                "batting_pts": 0,
                "overs_bowled": 0.0, "maidens": 0, "runs_conceded": 0,
                "wickets": 0, "best_figures": "0-0",
                "bowling_pts": 0,
                "catches": 0, "run_outs": 0, "stumpings": 0,
                "fielding_pts": 0,
                "total_pts": 0,
                "matches": 0,
            }

        p = season_data[name]
        p["matches"] += 1

        # Batting
        bat = data.get("batting", {})
        if bat and bat.get("runs") is not None:
            p["innings"] += 1
            p["runs"] += bat.get("runs", 0)
            p["balls_faced"] += bat.get("balls", 0)
            p["fours"] += bat.get("fours", 0)
            p["sixes"] += bat.get("sixes", 0)
            if "not out" in str(bat.get("how_out", "")).lower():
                p["not_outs"] += 1
            runs = bat.get("runs", 0)
            # Track highest score
            hs_str = p["highest_score"]
            hs_val = int(hs_str.replace("*", ""))
            if runs > hs_val:
                suffix = "*" if "not out" in str(bat.get("how_out", "")).lower() else ""
                p["highest_score"] = f"{runs}{suffix}"
            if runs >= 100:
                p["hundreds"] += 1
            elif runs >= 50:
                p["fifties"] += 1

        # Bowling
        bowl = data.get("bowling", {})
        if bowl and bowl.get("wickets") is not None:
            overs = parse_overs_to_float(bowl.get("overs", "0"))
            p["overs_bowled"] += overs
            p["maidens"] += bowl.get("maidens", 0)
            p["runs_conceded"] += bowl.get("runs", 0)
            p["wickets"] += bowl.get("wickets", 0)
            # Track best figures
            w = bowl.get("wickets", 0)
            r = bowl.get("runs", 0)
            best_w, best_r = p["best_figures"].split("-")
            if int(w) > int(best_w) or (int(w) == int(best_w) and int(r) < int(best_r)):
                p["best_figures"] = f"{w}-{r}"

        # Fielding
        f = data.get("fielding", {})
        p["catches"] += f.get("catches", 0)
        p["run_outs"] += f.get("run_outs", 0)
        p["stumpings"] += f.get("stumpings", 0)

        # Points
        p["batting_pts"] += data["batting_pts"]
        p["bowling_pts"] += data["bowling_pts"]
        p["fielding_pts"] += data["fielding_pts"]
        p["total_pts"] += data["total_pts"]

    return season_data


def generate_leaderboards(season_data, top_n=10):
    """Generate top-N leaderboards from cumulative season data."""
    players = list(season_data.items())

    def batting_avg(p):
        inn = p["innings"]
        no = p["not_outs"]
        dismissals = inn - no
        return p["runs"] / dismissals if dismissals > 0 else float(p["runs"])

    def bowling_avg(p):
        return p["runs_conceded"] / p["wickets"] if p["wickets"] > 0 else 999

    def bowling_economy(p):
        return p["runs_conceded"] / p["overs_bowled"] if p["overs_bowled"] > 0 else 99

    # Top batters by batting_pts
    top_batting = sorted(players, key=lambda x: x[1]["batting_pts"], reverse=True)[:top_n]
    batting_board = []
    for name, p in top_batting:
        batting_board.append({
            "name": name, "team": p["team"],
            "innings": p["innings"], "runs": p["runs"],
            "avg": round(batting_avg(p), 1),
            "hs": p["highest_score"],
            "fifties": p["fifties"], "hundreds": p["hundreds"],
            "pts": p["batting_pts"],
        })

    # Top bowlers by bowling_pts
    top_bowling = sorted(players, key=lambda x: x[1]["bowling_pts"], reverse=True)[:top_n]
    bowling_board = []
    for name, p in top_bowling:
        if p["wickets"] == 0 and p["overs_bowled"] == 0:
            continue
        bowling_board.append({
            "name": name, "team": p["team"],
            "overs": round(p["overs_bowled"], 1), "wickets": p["wickets"],
            "avg": round(bowling_avg(p), 1),
            "economy": round(bowling_economy(p), 2),
            "best": p["best_figures"],
            "pts": p["bowling_pts"],
        })

    # Top fielders by fielding_pts
    top_fielding = sorted(players, key=lambda x: x[1]["fielding_pts"], reverse=True)[:top_n]
    fielding_board = []
    for name, p in top_fielding:
        total_dismissals = p["catches"] + p["run_outs"] + p["stumpings"]
        if total_dismissals == 0:
            continue
        fielding_board.append({
            "name": name, "team": p["team"],
            "catches": p["catches"], "run_outs": p["run_outs"],
            "stumpings": p["stumpings"], "total": total_dismissals,
            "pts": p["fielding_pts"],
        })

    # Overall POTM by total_pts
    top_overall = sorted(players, key=lambda x: x[1]["total_pts"], reverse=True)[:top_n]
    overall_board = []
    for name, p in top_overall:
        overall_board.append({
            "name": name, "team": p["team"],
            "batting_pts": p["batting_pts"],
            "bowling_pts": p["bowling_pts"],
            "fielding_pts": p["fielding_pts"],
            "total_pts": p["total_pts"],
        })

    return {
        "batting": batting_board,
        "bowling": bowling_board,
        "fielding": fielding_board,
        "overall": overall_board,
    }


# ─── Main Pipeline ───────────────────────────────────────────────────────────

def run_weekly():
    """
    Main weekly pipeline:
    1. Find the most recent Saturday's matches for each team
    2. Fetch detailed scorecards
    3. Calculate POTM points
    4. Update season cumulative data
    5. Generate dashboard JSON
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    # Load existing season data
    season_data = {}
    if os.path.exists(SEASON_FILE):
        with open(SEASON_FILE, "r") as f:
            season_data = json.load(f)

    # Find teams
    teams = get_teams()
    if not teams:
        logger.error("No senior teams found! Check SITE_ID and team names.")
        sys.exit(1)

    logger.info(f"Found teams: {teams}")

    # Calculate last Saturday's date (most recent match day)
    today = datetime.now()
    days_since_saturday = (today.weekday() + 2) % 7  # Monday=0, Saturday=5
    last_saturday = today - timedelta(days=days_since_saturday)
    match_date = last_saturday.strftime("%d/%m/%Y")

    logger.info(f"Looking for matches on: {match_date}")

    weekly_results = []

    for team_label, team_id in teams.items():
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing {team_label} (ID: {team_id})")

        # Get matches for this team around last Saturday
        matches = get_matches(
            season=SEASON,
            team_id=team_id,
            from_date=match_date,
            end_date=match_date,
        )

        if not matches:
            # Try a wider window (Fri-Sun) in case of rescheduling
            fri = (last_saturday - timedelta(days=1)).strftime("%d/%m/%Y")
            sun = (last_saturday + timedelta(days=1)).strftime("%d/%m/%Y")
            matches = get_matches(season=SEASON, team_id=team_id, from_date=fri, end_date=sun)

        if not matches:
            logger.warning(f"No matches found for {team_label} on {match_date}")
            continue

        # Take the most recent match
        match_summary = matches[0]
        match_id = match_summary.get("id")

        if not match_id:
            logger.warning(f"No match ID for {team_label}")
            continue

        # Fetch full scorecard
        match_detail = get_match_detail(match_id)
        if not match_detail:
            logger.warning(f"Could not fetch scorecard for match {match_id}")
            continue

        # Process and calculate POTM
        result = process_match(match_detail, team_label)
        weekly_results.append(result)

        # Update season cumulative
        season_data = update_season_cumulative(season_data, result)

        logger.info(f"  POTM: {result['potm_winner']['name']} ({result['potm_winner']['total_pts']} pts)")
        logger.info(f"  Result: {result['result']}")

    # Generate leaderboards
    leaderboards = generate_leaderboards(season_data)

    # Calculate matchweek number
    matchweek = len([f for f in os.listdir(DATA_DIR) if f.startswith("week_")]) + 1

    # Build dashboard JSON
    dashboard = {
        "updated": datetime.now().isoformat(),
        "season": SEASON,
        "matchweek": matchweek,
        "matchweek_date": match_date,
        "weekly_performances": weekly_results,
        "leaderboards": leaderboards,
        "points_system": POINTS,
    }

    # Save outputs
    with open(WEEKLY_FILE, "w") as f:
        json.dump(weekly_results, f, indent=2, default=str)
    logger.info(f"Saved weekly data to {WEEKLY_FILE}")

    # Archive this week
    archive_file = os.path.join(DATA_DIR, f"week_{matchweek}_{match_date.replace('/', '-')}.json")
    with open(archive_file, "w") as f:
        json.dump(weekly_results, f, indent=2, default=str)

    with open(SEASON_FILE, "w") as f:
        json.dump(season_data, f, indent=2, default=str)
    logger.info(f"Saved season data to {SEASON_FILE}")

    with open(DASHBOARD_FILE, "w") as f:
        json.dump(dashboard, f, indent=2, default=str)
    logger.info(f"Saved dashboard data to {DASHBOARD_FILE}")

    return dashboard


def run_full_season():
    """Rebuild all season data by processing every match."""
    os.makedirs(DATA_DIR, exist_ok=True)
    season_data = {}

    teams = get_teams()
    if not teams:
        logger.error("No teams found!")
        sys.exit(1)

    all_weekly = []
    processed_match_ids = set()

    for team_label, team_id in teams.items():
        logger.info(f"\nProcessing full season for {team_label}")
        matches = get_matches(season=SEASON, team_id=team_id)

        for match_summary in matches:
            match_id = match_summary.get("id")
            if not match_id or match_id in processed_match_ids:
                continue
            processed_match_ids.add(match_id)

            status = match_summary.get("status", "").lower()
            if status not in ("result", "completed"):
                continue

            match_detail = get_match_detail(match_id)
            if not match_detail:
                continue

            result = process_match(match_detail, team_label)
            all_weekly.append(result)
            season_data = update_season_cumulative(season_data, result)

            logger.info(f"  {team_label} vs {result['opponent']}: POTM {result['potm_winner']['name']}")

    leaderboards = generate_leaderboards(season_data)

    dashboard = {
        "updated": datetime.now().isoformat(),
        "season": SEASON,
        "matchweek": len(all_weekly) // len(teams),
        "all_results": all_weekly,
        "leaderboards": leaderboards,
        "points_system": POINTS,
    }

    with open(SEASON_FILE, "w") as f:
        json.dump(season_data, f, indent=2, default=str)
    with open(DASHBOARD_FILE, "w") as f:
        json.dump(dashboard, f, indent=2, default=str)

    logger.info(f"\nFull season rebuild complete. {len(processed_match_ids)} matches processed.")
    return dashboard


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Harrow Town CC Dashboard Scraper")
    parser.add_argument("--full-season", action="store_true", help="Rebuild all season data")
    parser.add_argument("--match-id", type=str, help="Process a specific match by ID")
    args = parser.parse_args()

    if args.full_season:
        run_full_season()
    elif args.match_id:
        detail = get_match_detail(args.match_id)
        result = process_match(detail, "Manual")
        print(json.dumps(result, indent=2, default=str))
    else:
        run_weekly()
