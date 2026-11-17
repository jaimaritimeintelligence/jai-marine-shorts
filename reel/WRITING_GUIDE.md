# Case-file Reels — writing guide

The **Jai Marine Shorts** case-file series retells real marine accidents as short thrillers (60–110 s per part) that teach a lesson. The Chief records the narration in his own voice. Each part is one `reel/episodes/<case>-pN/episode.json`. Pushing it starts `reel.yml`, which sends the Chief the script on Telegram (one script at a time). His recording is picked up hourly. The Reel is rendered, previewed on Telegram and posted at 7:30 AM IST unless he taps Reject.

## Choosing a case
- Use **closed** investigations only, with a published final report: NTSB (US), MAIB (UK), ATSB (Australia), TAIC (New Zealand), TSB (Canada), DMAIB (Denmark), BSU (Germany), JTSB (Japan) and others.
- Read the report itself; WebFetch the PDF. Use news only for context.
- Prefer a story with tension: a clock, a chain of small mistakes, a surprising cause. Tankers, gas carriers, engine-room fires, blackouts, enclosed spaces, groundings, collisions and mooring accidents all work. Mix ship types and countries.
- **Never** pick a vessel managed by OSM Thome or Thome (the Chief's employer), or any case still under investigation or in court.
- Skip anything already listed in `reel/cases_done.json`.

## Facts and respect
- Every number, time and event must come from the report. No invented dialogue. Use short quotes only where the report quotes them.
- Use roles, not names ("the pilot", "the Second Engineer"). Treat fatal cases soberly. No ridicule, no blame beyond the report's findings.
- Hooks are clickbait but true. "Did the watchkeeper fall asleep?" is allowed only if fatigue or sleep is in the findings. Use questions the story actually answers.
- The caption ends with: `Source: <board> report <number> (public report). Animated illustration, not a reconstruction.` followed by 10–15 hashtags.

## Story shape
- **Part 1:** `hook` (cinematic cover, 1 sentence) → cold open at the worst moment (`alarm`) → rewind and set-up (ship, conditions) → the chain of events with clocks → the first crisis → a cliffhanger plus "Part 2 tomorrow. Follow so you don't miss it."
- **Part 2 (and 3):** `hook` → "Previously…" `card` → the rest of the chain → the moment (`impact`) → the damage or cost → "What the <board> found" `card` → "Lessons" `card` (numbered) → `cta` ("What would you have done?").
- Write narration for speaking aloud by an Indian marine engineer: short sentences, present tense, times as words ("Twenty-two thirteen"), numbers as words. Target **150–220 words per part**, at most 12 scenes.

## episode.json
```json
{"id": "<case>-p1", "voice": "human", "queue": true, "music": "lightless-dawn",
 "kicker": "SHIP NAME · PLACE · D MON YYYY",
 "caption": "...",
 "scenes": [ {"type": "...", "headline": "...", "sub": "...", "clock": "22:13", "alarm": false, "p": {...}, "narration": "..."} ]}
```
- In `headline`, wrap 1–3 key words in `[brackets]`; they print in gold. Keep it under about 40 characters. `sub` is a short grey line.
- `clock` is "HH:MM", or a pair ["22:05","22:09"] for a ticking clock. `alarm: true` makes the screen pulse red.

## Scene types and `p` parameters
| type | use | p |
|---|---|---|
| hook | first scene, the thumbnail (no top bar) | lines: [3–4 short lines, `[gold]`], sizes: [104,92,…], max: 12, badge: "WHY? WATCH TILL THE END", circle: true, hitAt: 2.2, y: 300 |
| alarm | cold open | lines: ["BIG LINE", "small line"], shakeAt |
| title | big title card | lines, tag, size |
| ship_profile | side view of the ship | draft (0–1, laden ≈ 0.6, ballast ≈ 0.35), freeboard / draftLabel text, wind text + windAt, current text + currentAt, chips + chipsAt |
| river | schematic map, ship moves along a path | path: [[x,y]…] in a 1000×820 box, from / to (0–1), width, bridges: [[x1,y1,x2,y2,lx,ly,"NAME"]], labels: [[x,y,"TEXT",colour\|null,size]], markers: [{x,y,label,at,col,dx,dy,anchor,pulse}] |
| turn | bend close-up, the ship drifts wide | cx, cy, R, a0, a1, shipTo, drift, dock, dockAng, dockDx, dockDy, curLabel |
| gauges | 1–3 dials | items: [{label,from,value,min,max,unit,dec,red}], note |
| impact | flash, shake, stamp | stamp, pier (y), pierLabel, sx, sy, ang, ix, iy, chips |
| phone | someone on a call | who, caller, chips |
| quote | short line or quote | text (`[gold]`), by, size |
| card | boxed list (findings, lessons, damage) | items, numbered, hl (index shown red), y, step (seconds between items), max |
| cta | end card | lines |

Check the layout before pushing: `python reel/montage.py reel/episodes/<id>/episode.json /tmp/m.jpg` renders the end of every scene into one image. Look at it and fix overlaps or overflowing text.
