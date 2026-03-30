# Harrow Town CC — Automated Performance Dashboard

Live stats dashboard for Harrow Town Cricket Club's four senior men's teams (1st–4th XI), automatically updated every Monday from Play-Cricket scorecards.

**Club ID:** 3199 | **League:** Middlesex County Cricket League | **Ground:** Harrow Town Sports Club, Rayners Lane

## Features

- **Performance of the Week** — POTM points calculated from batting, bowling & fielding for each XI
- **Season Leaderboards** — Top 10 batsmen, bowlers, fielders & overall across all teams
- **Fully automated** — GitHub Actions fetches data from Play-Cricket API every Monday at 7am

## Quick Start

1. Get a Play-Cricket API key (email `play.cricket@ecb.co.uk`)
2. Add `PLAYCRICKET_API_KEY` and `PLAYCRICKET_SITE_ID` as GitHub Secrets
3. Deploy to Vercel or GitHub Pages
4. See [SETUP_GUIDE.md](SETUP_GUIDE.md) for detailed instructions

## Project Structure

```
├── index.html              # Dashboard frontend (static, reads data/dashboard.json)
├── scraper.py              # Python scraper & POTM calculator
├── requirements.txt        # Python dependencies
├── SETUP_GUIDE.md          # Full setup walkthrough
├── data/                   # Auto-generated JSON (committed by GitHub Actions)
│   ├── dashboard.json      # Current dashboard state
│   ├── season_cumulative.json
│   └── weekly_potw.json
└── .github/workflows/
    └── weekly_update.yml   # Monday cron automation
```

## Points System

| Batting | Pts | Bowling | Pts | Fielding | Pts |
|---------|-----|---------|-----|----------|-----|
| Per run | +1 | Per wicket | +20 | Catch | +10 |
| Per four | +1 | 3w haul | +5 | Run out | +10 |
| Per six | +2 | 5w haul | +20 | Stumping | +12 |
| 25 milestone | +5 | Per maiden | +3 | | |
| 50 milestone | +10 | Econ <4 | +15 | | |
| 100 milestone | +25 | Econ <5 | +10 | | |
| Not out | +5 | Econ <6 | +5 | | |
| Duck | -3 | Econ ≥10 | -5 | | |
