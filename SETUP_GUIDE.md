# Harrow Town CC — Automated Dashboard Setup Guide

## Overview

This system automatically fetches match scorecards from Play-Cricket every Monday, calculates POTM (Performance of the Match) points using the club's scoring system, and updates a dashboard showing weekly performances and season leaderboards.

**Club ID:** 3199  
**Play-Cricket Site:** harrowtown.play-cricket.com  
**Teams:** 1st XI, 2nd XI, 3rd XI, 4th XI  
**Leagues:** Middlesex County Cricket League

***

## What You Need

### 1. Play-Cricket API Key (Essential — Do This First)

Play-Cricket has a **free official API**. To get access:

1.  Email **play.cricket@ecb.co.uk** requesting API access
2.  You must be a **Play-Cricket admin** for the Harrow Town CC site
3.  They will ask you to agree to a **fair usage agreement**
4.  They will reply with:
    -   Your **API Key** (a long alphanumeric string)
    -   Confirmation of your **Site ID** (should be `3199`)

**Tip:** Mention that you're building an internal club stats dashboard. This is exactly the kind of use case the API was designed for. Turnaround is usually within a few working days.

### 2. A GitHub Account (Free)

The automation runs on GitHub Actions (free for public repos, 2000 mins/month for private). You'll store your code here and the Monday cron job runs automatically.

### 3. A Hosting Platform for the Dashboard (Free)

The frontend is a static HTML file. Host it for free on:

-   **Vercel** (recommended — auto-deploys from GitHub)
-   **Netlify** (similar to Vercel)
-   **GitHub Pages** (simplest, built into GitHub)

***

## Step-by-Step Setup

### Step 1: Create a GitHub Repository

```bash
# On your local machine
mkdir harrow-town-dashboard
cd harrow-town-dashboard
git init
```

Copy these files into the repo:

```
harrow-town-dashboard/
├── .github/
│   └── workflows/
│       └── weekly_update.yml     # Monday automation
├── data/                          # Generated data (auto-populated)
├── scraper.py                     # Main Python scraper
├── index.html                     # Dashboard frontend
└── README.md
```

### Step 2: Add Your API Key as a GitHub Secret

1.  Go to your repository on GitHub
2.  Click **Settings** → **Secrets and variables** → **Actions**
3.  Click **New repository secret**
4.  Add two secrets:
    -   Name: `PLAYCRICKET_API_KEY` → Value: your API key
    -   Name: `PLAYCRICKET_SITE_ID` → Value: `3199`

These secrets are encrypted and never exposed in logs.

### Step 3: Test Locally

Before relying on automation, test the scraper on your machine:

```bash
# Install dependencies
pip install requests python-dateutil

# Set environment variables
export PLAYCRICKET_API_KEY="your_api_key_here"
export PLAYCRICKET_SITE_ID="3199"

# Run for the latest week
python scraper.py

# Or rebuild the full season
python scraper.py --full-season
```

This will create JSON files in the `data/` folder.

### Step 4: Deploy the Dashboard Frontend

**Option A: Vercel (Recommended)**

1.  Go to vercel.com, sign in with GitHub
2.  Import your repository
3.  It auto-detects a static site and deploys
4.  Every push to `main` auto-redeploys
5.  You get a URL like `harrow-town-dashboard.vercel.app`

**Option B: GitHub Pages**

1.  In your repo settings, go to **Pages**
2.  Set source to `main` branch, `/` (root) folder
3.  Your dashboard is live at `https://yourusername.github.io/harrow-town-dashboard/`

### Step 5: Verify the Monday Automation

The GitHub Action runs every Monday at 7:00 AM UK time. To test it immediately:

1.  Go to your repo → **Actions** tab
2.  Click **Weekly Dashboard Update**
3.  Click **Run workflow** → **Run workflow**
4.  Watch the logs to confirm it runs successfully

***

## How the Points System Works

The POTM points are calculated per player per match, combining batting, bowling, and fielding contributions:

### Batting

| Action                  | Points |
|-------------------------|--------|
| Per run scored          | +1     |
| Per four                | +1     |
| Per six                 | +2     |
| Reaching 25             | +5     |
| Reaching 50             | +10    |
| Reaching 100            | +25    |
| Not out                 | +5     |
| Duck                    | -3     |
| SR ≥ 150 (min 10 balls) | +10    |
| SR ≥ 100 (min 10 balls) | +5     |
| SR \< 50 (min 10 balls) | -5     |

### Bowling

| Action                     | Points |
|----------------------------|--------|
| Per wicket                 | +20    |
| 3-wicket haul bonus        | +5     |
| 5-wicket haul bonus        | +20    |
| Per maiden                 | +3     |
| Economy \< 4 (min 4 overs) | +15    |
| Economy \< 5 (min 4 overs) | +10    |
| Economy \< 6 (min 4 overs) | +5     |
| Economy ≥ 10 (min 4 overs) | -5     |

### Fielding

| Action   | Points |
|----------|--------|
| Catch    | +10    |
| Run out  | +10    |
| Stumping | +12    |

All thresholds are configurable at the top of `scraper.py` in the `POINTS` dict.

***

## Customisation

### Changing the match day

If matches are on Sundays instead of Saturdays, edit the date calculation in `run_weekly()` in `scraper.py`.

### Adding more teams

Add team names to the `SENIOR_TEAMS` list in `scraper.py`.

### Adjusting point values

Edit the `POINTS` dictionary at the top of `scraper.py`.

### Custom branding

Edit `index.html` to change colours, logo, and club details.

***

## Troubleshooting

| Problem                | Solution                                                                      |
|------------------------|-------------------------------------------------------------------------------|
| "No teams found"       | Check your SITE_ID matches the Harrow Town site                               |
| "API key not set"      | Make sure the GitHub secret is named exactly `PLAYCRICKET_API_KEY`            |
| "No matches found"     | Scorecards may not be uploaded yet — they sometimes take until Sunday/Monday  |
| Wrong team matched     | Check the exact team names in Play-Cricket match `SENIOR_TEAMS` in config     |
| Fielding stats missing | Play-Cricket only records fielders if the scorer enters them in the dismissal |

***

## Architecture

```
Every Monday at 7am:

  GitHub Actions (cron)
        │
        ▼
  scraper.py runs
        │
        ├── Calls Play-Cricket API v2
        │   ├── /teams.json          → Find team IDs
        │   ├── /result_summary.json → Find latest match IDs
        │   └── /match_detail.json   → Get full scorecards
        │
        ├── Calculates POTM points per player
        ├── Updates season cumulative stats
        ├── Generates leaderboards
        │
        └── Commits data/ to GitHub
              │
              ▼
        Vercel/GitHub Pages auto-deploys
              │
              ▼
        Dashboard is live with new data
```

***

## Useful Links

-   Play-Cricket API docs: https://play-cricket.ecb.co.uk/hc/en-us/sections/360000978518
-   pyplaycricket library: https://github.com/ewanharris12/pyplaycricket
-   Play-Cricket MCP server: https://github.com/c-m-hunt/play-cricket
-   Harrow Town CC Play-Cricket: https://harrowtown.play-cricket.com
-   Middlesex CCL: https://middlesexccl.play-cricket.com
