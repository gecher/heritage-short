# Architecture

One file describes the film (`storyboard.json`). One command builds it (`python -m pipeline film`).
Every stage reads the storyboard, caches its outputs by content hash, and logs every call to `runs.jsonl`.

```
storyboard.json ──validate──▶ narration ──────────────┐   (Gemini TTS, Amharic, quality gate)
  (schema/storyboard.         keyframes ──▶ shots ─────┤   (FLUX on Cloudflare + Gemini judge; FFmpeg camera moves)
   schema.json)               end card ────────────────┤   (FFmpeg drawtext, Ethiopic font)
                              music (tizita score) ────┤
                                                       ▼
                                  film: picture + voice + ducked music + burned-in subtitles
                                  → outputs/film/the_roots_we_carry_9x16.mp4
```

## Stages and the contract
| Stage | Command | Input | Output | Provider |
|---|---|---|---|---|
| validate | `validate` | storyboard.json | errors or "valid" | local (JSON Schema + film rules) |
| narration | `narration` | each shot's `narration`, the voice block | `outputs/narration/<shot>-<key>.wav`, `manifest.json` | Gemini TTS (fallback chain) |
| reference | `reference` | the character description | 4 portraits; I chose one into `style.character.reference_image` | FLUX schnell |
| keyframes | `keyframes` | `image_prompt` + character + `style_block` | candidates, judge scores, chosen frame, `contact_sheet.jpg` | FLUX schnell + Gemini vision judge |
| shots | (in `film`) | chosen keyframe, shot length | `outputs/shots/<shot>-<key>.mp4` | FFmpeg (Ken Burns) |
| music | `music` | the storyboard's music block, real shot lengths | `outputs/music/score.wav` | Lyria if available, else `score.py` (tizita, composed in code) |
| film | `film` | all of the above | final MP4: bilingual subtitles, Ge'ez chapters, typewriter title, tibeb border, memory dissolves | FFmpeg |
| site | `site` | film, frames, judge verdicts, `review.json`, `runs.jsonl` | `web/` (static page + data.json) | local; hosted on Vercel |

**The contract** (`schema/storyboard.schema.json`) says what every shot must have: id, duration
(3–12 s), why the shot exists, shot size, image prompt, camera motion, Amharic narration and its
English subtitle. `validate` adds rules a schema cannot express: unique ids, a 60–90 s total, music
cues that point to real shots, and narration short enough for its shot.

**Timing:** a shot lasts its `duration`, or longer if its narration needs more room
(`radio.shot_lengths`). The voice track, the subtitles and the picture all use this one function,
so they cannot drift apart.

## Caching
Every output's file name contains a hash of **everything it depends on**: stage, model, every
parameter, the prompt text, the `take` number and the bytes of any input file (`common.cache_key`).
- Change one shot's prompt → only that shot's image and clip are rebuilt.
- Re-run with nothing changed → zero API calls; `runs.jsonl` shows `cache hit` lines.
- FLUX takes no seed (FAILURES F09) and TTS has no seed, so the cache, not a seed, is what makes
  re-runs identical. `"take": 2` deliberately asks for a fresh version of one shot.

## Failure handling
- **Retries with backoff** in `common.call_model`: short waits for overload (503), longer for rate
  limits (429), and **no** waiting for daily quotas, which do not recover in seconds.
- **Fallback chains** for text, TTS and the judge, configured in `.env`. The judge learns during a run:
  the model that answered last is tried first (FAILURES F12).
- **Quality gates:** narration longer than its Ge'ez syllable count allows is rejected and retried
  (F04); keyframe candidates are scored by the judge and the best one wins.
- **Graceful degradation:** if the judge is unavailable, the first candidate is used and the
  manifest says `"judged": false`; if there is no music file, a quiet placeholder drone is used.
- **Atomic writes:** every output is written as `.partial` and renamed when complete, so the cache never trusts a half-written file (FAILURES F18).
- **Every attempt is logged** (`runs.jsonl`): time, stage, shot, provider, model, parameters,
  latency, attempt number, status and the error text.

## Files
```
pipeline/common.py      paths, storyboard validation, Gemini client, cache keys, call_model + log
pipeline/narration.py   Amharic TTS, syllable quality gate, takes, pronunciation map
pipeline/radio.py       shot lengths, voice track, subtitles, the audio-only "radio cut"
pipeline/keyframes.py   reference portraits, FLUX candidates, Gemini judge, contact sheet
pipeline/shots.py       Ken Burns camera moves per shot (i2v clip used instead if present)
pipeline/film.py        subtitles (Amharic + English), chapters, title, end card, final assembly
pipeline/music.py       Lyria score, or the fallback below
pipeline/score.py       the tizita score composed in code (and its instrument stems)
pipeline/site.py        the website's data and assets
pipeline/report.py      COSTS.md from runs.jsonl
web/index.html          the static website
pipeline/smoke.py       one call per provider, to check keys and quotas
```
