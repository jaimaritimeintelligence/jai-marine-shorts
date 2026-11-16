# Jai Marine Shorts — automated daily shipping news for Instagram

Every day this repository builds and posts a 10-slide carousel:
**"Everything that happened in shipping industry in the last 24 hours"**.

| Time (IST) | What happens |
|---|---|
| ~4:55 PM | `1 - Prepare daily carousel`: collects news (trade-press RSS + Google News), Gemini picks 9 stories in the approved mix, finds real free-licence photos on Wikimedia Commons, checks each photo matches its story, renders the slides into `out/<date>/`, sends a preview to Telegram with **Approve / Reject** buttons. |
| 7:27 PM – 8:57 PM | `2 - Publish to Instagram`: posts the carousel once approved (checks every 30 min, last try ~9 PM). |

Daily story mix: slide 2 crude oil price · slides 3–8 accidents, Hormuz/Red Sea attacks, crew & labour (MLC), cyber/internet, at least one LNG story · slides 9–10 sale & purchase, newbuilds, other commercial news.
Every slide credits the news source and the photographer/licence.

## Secrets (Settings → Secrets and variables → Actions)
- `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `IG_ACCESS_TOKEN` — Instagram API with Instagram Login long-lived token (Step 4)

## Variables
- `AUTO_POST` = `true` to skip Telegram approval and post automatically.

## Manual runs
Actions tab → choose a workflow → **Run workflow**. `0 - Check setup` tests every connection and reports to Telegram.

Fonts: Anton and Oswald (SIL Open Font License, see `fonts/OFL-LICENSE.txt`).
