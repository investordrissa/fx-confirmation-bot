# FX Confirmation Bot

Scans a broad list of forex pairs across Weekly → Daily → 4H timeframes,
following your 6-rule strategy, and sends Telegram alerts when a setup
confirms.

## Setup (GitHub)

1. Create a new **private** GitHub repo (private, since this contains your
   trading logic — not required to work, but recommended).
2. Upload all the files in this folder, keeping the folder structure
   (the `.github/workflows/run-bot.yml` file must stay in that exact path).
3. Go to your repo → **Settings → Secrets and variables → Actions** →
   **New repository secret**, and add three secrets:
   - `TWELVE_DATA_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Go to the **Actions** tab of your repo → you should see "FX Confirmation
   Bot" listed. Click it, then **Run workflow** to trigger it manually the
   first time and confirm it works (check for a Telegram message or at
   least a successful green run).
5. After that, it runs automatically every hour on its own — no further
   action needed.

## Adjusting how often it runs

Edit the `cron` line in `.github/workflows/run-bot.yml`. Right now it's
`0 * * * *` (every hour). Twelve Data's free tier gives 800 credits/day;
each pair costs 3 credits per run (weekly + daily + 4H), and this bot
checks 27 pairs, so one run costs about 81 credits. Running hourly (24
runs/day) would need ~1,944 credits/day — over the free limit. You have
two options:
  - Reduce the pair list in `main.py` (`PAIRS`), or
  - Run less often, e.g. every 4 hours: `0 */4 * * *` (27 pairs × 6
    runs/day ≈ 486 credits/day, safely under the 800 limit).

Given your strategy relies on 4H confirmation candles, checking every 4
hours (aligned with candle closes) is a reasonable and safe default —
I've left the file set to hourly so you can start there and dial back
easily if you hit the rate limit (you'll see errors in the Actions log).

## Important — please read

This script automates the *mechanical* parts of your rules (candle body
comparisons, wick sweeps, distance measurements, SL/TP math). But two of
your rules — order block identification and 4H market structure — are
genuinely difficult to encode perfectly in code, because they involve a
degree of visual/contextual judgment you apply when reading charts by
eye (e.g. "does this impulsive move look strong enough", "is this really
the relevant swing point").

The `find_weekly_key_levels` and `check_h4_confirmation` functions use
reasonable simplified approximations of your rules, but they will not
always match your own read of a chart. Treat every alert as a prompt to
**go and check the chart yourself** before acting on it — not as a
fully automated trading signal. This is meant to help you not miss
potential setups across many pairs, not to remove your own judgment
from the decision.

## Files

- `main.py` — the bot logic
- `requirements.txt` — Python dependencies
- `state.json` — tracks progress per pair between runs (auto-updated)
- `.github/workflows/run-bot.yml` — the schedule that runs it automatically
