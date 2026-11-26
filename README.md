# The Roots We Carry · ሥርህን ይዘህ ትሄዳለህ

A 90-second Amharic film about Ethiopian heritage, rebuilt from one file (`storyboard.json`) with one command.

A father in Addis Ababa answers his son abroad, who asked what Ethiopia is, by showing him what his own father once showed him: the highlands, a church carved from rock, the elders under the warka tree, the coffee ceremony, and the new generation.

- **Film:** <!-- link: YouTube (unlisted) or Drive -->
- **Website:** <!-- link: Vercel --> (watch with a live Amharic/English transcript, see the AI judge versus the human review, play the score instrument by instrument)

## What is special about it
- **Amharic voice with a Ge'ez quality gate.** Each line is checked against its syllable count (each fidel ≈ one syllable). Takes that are too long, for example when the model read the English instruction aloud, are rejected and re-recorded automatically.
- **An AI judge, and an Ethiopian eye over it.** Every shot has several image candidates scored for prompt match, character consistency, Ethiopian appearance and cultural accuracy. Where the judge accepted something an Ethiopian viewer would reject, the human review overruled it (`review.json`).
- **A tizita score composed in code.** No music model had free quota, so `pipeline/score.py` writes an original score in the tizita scale, timed to the film's cues.
- **Bilingual on screen.** Amharic in Ge'ez script above English subtitles, chapter marks in Ge'ez numerals (፩ ፪ ፫ ፬ ፭), the title written fidel by fidel, a tibeb border.
- **Honest engineering.** Content-hash caching, fallback chains, a call log, 18 documented failures, 11 experiments.

## Quick start
```bash
git clone https://github.com/gecher/heritage-short && cd heritage-short
python -m pip install -r requirements.txt
cp .env.example .env          # add your own keys (never commit .env)
python -m pipeline smoke      # one call per provider, logged to runs.jsonl
python -m pipeline film       # the whole film, twice: outputs/film/the_roots_we_carry_9x16.mp4 (phones) and _16x9.mp4 (laptops, YouTube)
python -m pipeline site       # the website's data and assets -> web/
python -m pipeline report     # COSTS.md from runs.jsonl
```
Needs Python 3.11+, FFmpeg (set `FFMPEG_BIN` in `.env` if it is not on PATH), a Gemini API key and a Cloudflare Workers AI token. On Windows the Amharic text uses the Ebrima font; elsewhere set `FONT_FILE` to a font with Ethiopic letters.

## All commands
| Command | What it does |
|---|---|
| `validate` | check `storyboard.json` against the schema and the film rules |
| `narration` | Amharic narration, one cached file per shot |
| `say "..."` | speak one test phrase (pronunciation trials) |
| `radio` | audio-only cut on black, to test the story before any picture |
| `reference` | candidate portraits of the father; pick one into the storyboard |
| `keyframes` | image candidates per shot, judged, best one chosen, contact sheet |
| `music` | the score: Lyria if available, otherwise composed in code |
| `film` | everything in order, then the final MP4s: 9:16 and 16:9 (`film 16x9` for one) |
| `site` | the website in `web/` |
| `report` | COSTS.md |

## Documents
- [DESIGN.md](DESIGN.md): audience, intent, story, user tests
- [ARCHITECTURE.md](ARCHITECTURE.md): stages, the contract, caching, failure handling
- [FAILURES.md](FAILURES.md): what broke and how it was fixed
- [EXPERIMENTS.md](EXPERIMENTS.md): one change at a time, with evidence
- [COSTS.md](COSTS.md): every call, measured ($0: free tiers)
- [ETHICS.md](ETHICS.md): consent, licences, labelling, cultural care
- [review.json](review.json): the human review of the AI judge

## Known limits and next steps
- Shots s03, s07 and s10 still have cultural weaknesses; better prompts are written (FAILURES F15) for when the free image quota resets.
- Image-to-video motion (Wan on a Kaggle GPU) for one or two hero shots; any clip placed at `outputs/shots/<id>-i2v.mp4` replaces the camera move.
- "Write your own letter home" on the website: a visitor types a message and hears it in Amharic (needs a small server for the API key).
- The three rounds of the coffee ceremony (abol, tona, bereka) as the structure of a second film.

*Made with AI (FLUX.1 schnell, Gemini TTS, Gemini flash-lite). All characters are fictional. Amharic written and checked by a native speaker.*
