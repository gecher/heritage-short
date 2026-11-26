# Failures

What broke while building the film, what I tried, and what fixed it. Every error is also a line in
`runs.jsonl` (171 lines by 26 Nov: 49 overloaded-server errors, 13 daily-quota errors, 6 bad requests).

## F01: Free tier "unavailable" on my first Google account
- **What broke:** AI Studio showed the free tier as unavailable for my existing project, so every call needed billing.
- **What I tried:** a new API key in the same project (same result).
- **What fixed it:** a new Google account with a fresh project (`heritage-short`), which got the free tier.
- **Evidence:** AI Studio screenshots; first successful call in `runs.jsonl` on 24 Nov.

## F02: Models "not found" and TTS settings "unknown"
- **What broke:** `gemini-flash-latest` returned 404, and the TTS `speechConfig` field was rejected.
- **What I tried:** other model names; same errors.
- **What fixed it:** both only exist on the **v1beta** API. `gemini_client()` now always uses v1beta. Listing models on v1beta showed 65 models (saved in `outputs/models.txt`).
- **Evidence:** `ClientError: 404 NOT_FOUND` lines for gemini-flash-latest and gemini-2.5-flash.

## F03: "503 This model is currently experiencing high demand"
- **What broke:** the newest flash models were overloaded most of the time (49 errors in the log).
- **What fixed it:** a fallback chain in `.env` (`GEMINI_TEXT_FALLBACKS`): if one model is overloaded, the next one answers. The smoke test shows it: `gemini-3.5-flash` answered after three others failed.
- **Lesson:** on the free tier, "the best model" is the one that answers today. Design for that.

## F04: The voice read my English instruction out loud
- **What broke:** the first narration run put the style instruction ("Say in Amharic, slowly and warmly…") into the audio. Lines that should be ~6 s were 18–22 s.
- **What I tried:** listening found it; the files are kept in `outputs/narration/_old_run1_instruction_spoken/`.
- **What fixed it:** a director-style prompt, `"<instruction>: <text>"`, and a **quality gate**: Amharic is written in Ge'ez syllables (each letter ≈ one syllable), so a line cannot honestly take longer than `syllables / 2.5 + 1.5` seconds. Longer audio is rejected and retried automatically.
- **Evidence:** 9 `rejected` lines in `runs.jsonl`; rejected takes in `outputs/narration/_rejected/`.

## F05: Daily quotas (429 RESOURCE_EXHAUSTED)
- **What broke:** TTS models allow about 10 requests a day each; `gemini-4-hydrogen` allows 20. Waiting and retrying wasted time.
- **What fixed it:** a TTS fallback chain (`GEMINI_TTS_FALLBACKS`), and `call_model()` fails fast on "per day" errors instead of waiting, because a daily limit never recovers in seconds. The cache means a finished line is never requested again.

## F06: "ኢትዮጵያ" (Ethiopia) mispronounced in shot s01
- **What broke:** in one take, the word Ethiopia sounded wrong. I am a native speaker and heard it immediately.
- **What I tried:** four spellings with `python -m pipeline say "..."`. All four were pronounced correctly.
- **What fixed it:** it was random variation, not the spelling. TTS has no seed, so I added a `take` field to each shot: `"take": 2` makes a new cache key and a new recording of only that line.
- **Evidence:** test files in `outputs/narration/_tests/`; s01 has `"take": 2` in `storyboard.json`.

## F07: The radio cut was 70.1 s instead of 75 s
- **What broke:** FFmpeg's `-shortest` stopped the video at the last subtitle.
- **What fixed it:** set the length explicitly with `-t <total>`.

## F08: API keys pasted into the wrong file (twice)
- **What broke:** I pasted my Gemini key, and later my Cloudflare keys, into `.env.example`, the template that is committed to GitHub, instead of `.env`.
- **What fixed it:** moved the values into `.env` (which `.gitignore` excludes) and blanked the template. Nothing was committed or pushed: `git status` was checked both times.
- **Lesson:** check `git status` and `git diff` before every commit. The two files sit next to each other in the editor.

## F09: Cloudflare FLUX rejects `seed`
- **What broke:** `400 Bad Request` with no detail.
- **What I tried:** printing Cloudflare's own error body instead of only the status code. It said: `Additional or unevaluated properties '/seed' not allowed` (code 5006).
- **What fixed it:** removed `seed`. Images are therefore not reproducible from a seed; the content-hash cache is what makes re-runs identical.
- **Lesson:** always print the provider's error message. "400 Bad Request" hid a one-line answer.

## F10: The image model does not know a jebena
- **What broke:** the smoke test prompt "a clay coffee pot (jebena)" produced a Middle-Eastern pot with a lid and a cup with a handle. Any Ethiopian viewer would notice.
- **What fixed it:** describe the object instead of naming it ("round-bellied black clay coffee pot with a long narrow neck, a side spout and a woven grass stopper… small white handleless cups"), and an automatic judge that flags cultural mistakes (see EXPERIMENTS.md).
- **Evidence:** `outputs/keyframes/smoke.jpg`.

## F11: Part of the character description was dropped
- **What broke:** all 4 reference portraits of the father show a plain shirt; none shows the white gabi from the description.
- **Workaround:** accepted for close-ups; the gabi is visible in other shots' prompts. Lesson: long prompts lose details at the end, so put the most important detail first.

## F12: The judge was slow
- **What broke:** for every image, the judge tried 4 overloaded models before reaching the one that worked: about 90 s wasted per image.
- **What fixed it:** a "sticky" model order: the model that last answered is tried first, and a model that just failed goes to the back.
- **Evidence:** `judge` lines in `runs.jsonl` before and after 10:55 on 26 Nov.

## F13: FFmpeg not found
- **What broke:** FFmpeg was installed with winget but not on PATH in the open terminal.
- **What fixed it:** `FFMPEG_BIN` in `.env` with the full path; `ffmpeg()` uses it first.

## F14: "Cannot send a request, as the client has been closed"
- **What broke:** the new Gemini image fallback failed on every model with this message.
- **Cause:** my code created the client and used it in one expression (`gemini_client().models.generate_content(...)`); Python closed the temporary client before the request was sent.
- **What fixed it:** keep the client in a variable for the whole call.

## F15: Out of free images for the day (a decision, not a fix)
- **What broke:** after ~45 images (4 reference portraits, 2 rounds of candidates, a stricter re-run), Cloudflare returned `429 … used up your daily free allocation of 10,000 neurons` (code 4006). The Gemini image models had no free daily quota either (`retryDelay 84490s`).
- **Options:** pay $5 for Cloudflare Workers Paid, or keep the best images already made.
- **Decision:** I kept the images I had (free). Shots s03 (grandfather's clothes are not clearly Ethiopian), s07 (the pot still looks like a teapot) and s10 (a Western cup) are known weaknesses. The better prompts I wrote for them after my own review are kept below, ready for the next run when the quota resets.
- **Lesson:** budget the free image quota before experimenting: ~45 images a day on Cloudflare's free tier. Spend it on final candidates, not on repeated trial runs.

<details><summary>Improved prompts for the next run (written after my review as an Ethiopian viewer)</summary>

- **s03:** seen from the side, a Habesha Ethiopian grandfather and his eight-year-old grandson walking hand in hand on a highland path at sunrise. The grandfather: deep brown skin, white beard, white handwoven gabi with a thin coloured tibeb border, long white cotton shirt, white jodhpur-style trousers, wooden walking stick. The boy is the young Abba: deep brown skin, short tightly curled black hair, kind eyes, small white shirt and shawl, looking up at his grandfather.
- **s06:** traditional coffee ceremony: dark brown beans roasting in a flat long-handled iron pan (menkeskesh) over a small clay charcoal stove, a clay incense burner with frankincense smoke, fresh ketema grass on the floor.
- **s07:** a Habesha woman's hand pouring coffee from the spout of a round-bellied black clay jebena (long narrow neck, woven grass stopper) into small white handleless sini cups on a low wooden rekebot, popcorn in a woven mesob nearby, warm lamp light.
- **s10:** a young Habesha man in his twenties, seen from the side, deep brown skin, short curly black hair and kind eyes like his father, at a window in a snowy foreign city at night, holding a small white handleless coffee cup, a phone glowing in his other hand.
</details>

## F16: The film played with no sound
- **What broke:** the video was silent in Windows' player, though the audio track was there and at normal loudness (measured: mean ‑23.6 dB).
- **Cause:** FFmpeg's loudness filter works at 192 kHz, so the AAC track came out at 96 kHz, which many players play as silence.
- **What fixed it:** convert the mix back to 48 kHz stereo before encoding. Lesson: a file can be correct and still not play everywhere; check the format, not only the content.

## F17: No free music model
- **What broke:** `lyria-3-pro-preview`, `lyria-3.5` and `lyria-3-clip-preview` all returned 429 on the free tier.
- **What fixed it:** a score composed in code in the tizita mode (EXPERIMENTS E10).

## F18: A half-written file was trusted by the cache
- **What broke:** a test run stopped while writing one shot's clip. The next run found a file with the right name, trusted it, and the film lost 18 seconds of picture (picture 69 s, sound 88 s).
- **What fixed it:** every stage now writes to a `.partial` file and renames it only when it is complete, so a cached name always means a complete file.
- **Lesson:** a cache is only as good as its rule for "done".
