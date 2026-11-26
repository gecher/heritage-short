# Experiments

One change at a time, with the evidence in `runs.jsonl`, the output folders or the judge files.

## E01: Where the style instruction goes in a TTS prompt
- **Hypothesis:** sending the style instruction and the Amharic text as one plain prompt is enough.
- **Change:** run 1 used `"<instruction>\n<text>"`; run 2 used a director-style prompt `"<instruction>: <text>"`.
- **Result:** run 1 read the English instruction aloud: 18–22 s for lines that need ~6 s (`outputs/narration/_old_run1_instruction_spoken/`). Run 2 spoke only the Amharic.
- **Decision:** keep the director-style prompt, and add a gate that catches it if it ever happens again (E02).

## E02: A quality gate from the Ge'ez script
- **Hypothesis:** Amharic is written in syllables (each fidel ≈ one syllable), so the expected length of a line can be predicted from its letters, without any speech recognition.
- **Change:** reject any take longer than `syllables / 2.5 + 1.5` seconds.
- **Result:** 9 takes rejected automatically (`status: rejected` in `runs.jsonl`, files in `outputs/narration/_rejected/`). Accepted lines run at 2.96–5.15 syllables/s (`outputs/narration/manifest.json`).
- **Decision:** keep. A check that only works because of how Ge'ez is written.

## E03: Which TTS model
- **Change:** the same lines on three models.
- **Result (median latency, `runs.jsonl`):** gemini-3.8-flash-lite-tts 4.4 s but more rejected takes and a thinner voice; gemini-3.1-flash-tts-preview 7.9 s; gemini-3.8-flash-tts 8.3 s.
- **Decision:** gemini-3.1-flash-tts-preview first (warmest voice for Abba, native-speaker judgement), the others as quota fallbacks.

## E04: Fixing one mispronounced word
- **Hypothesis:** "ኢትዮጵያ" (Ethiopia) in s01 was mispronounced because of the spelling.
- **Change:** four spellings tested with `python -m pipeline say` (`outputs/narration/_tests/`).
- **Result:** all four were pronounced correctly, so the spelling was not the cause: it was random variation between takes.
- **Decision:** add a `take` number to each shot; `"take": 2` re-records only that line. Fixed s01.

## E05: Name an object, or describe it?
- **Change:** "a clay coffee pot (jebena)" versus a description of its shape: round belly, long narrow neck, side spout, grass stopper, handleless cups.
- **Result:** the name alone produced a Middle-Eastern pot with a lid (`outputs/keyframes/smoke.jpg`). The description produced a round black clay pot, still imperfect (`review.json`, s07).
- **Decision:** describe cultural objects by shape and material; name only famous landmarks (E07).

## E06: Several candidates and an automatic judge
- **Change:** 2 candidates per shot (3–4 for the father), each scored by a Gemini vision model for prompt match, same person as the reference portrait, cultural issues and artifacts.
- **Result:** the judge caught real problems: a Petra-like church (s04, "the architecture resembles Petra"), green unroasted beans (s06), handled cups (s07), garbled sign text (s08). Judgements are cached in `outputs/keyframes/judge/`.
- **Decision:** keep, with E08.

## E07: Naming a landmark
- **Change:** s04 from "a cross-shaped church carved down into red rock" to "the Church of Saint George (Bete Giyorgis) in Lalibela… flat roof carved with nested crosses".
- **Result:** round 1 gave a European-style church in a canyon (and the judge scored it 10/10). Round 2 gave a cross-shaped church seen from above in a rock pit.
- **Decision:** for famous places, the name carries more than any description.

## E08: The judge versus the Ethiopian eye
- **Change:** judge v1 (generic) versus v2 ("a strict Ethiopian reviewer", plus a score for "do the people look Habesha?" that costs points below 10).
- **Result:** v1 accepted a father who looked South Asian (s02: same person 8/10, no issues) and elders in Middle-Eastern head cloths (s05). My review rejected both. With the rewritten prompts and v2, s02's chosen frame scored looks-Habesha 10/10 and was confirmed by my review; v2 also flagged the s03 clothing as "kurta/thobe rather than gabi".
- **Decision:** the judge is a first filter, not the final word. Every overruled frame is recorded in `review.json` and shown on the website.

## E09: Sticky model order for the judge
- **Problem:** with the newest models overloaded (503), every image first waited on four failing models (~90 s per image).
- **Change:** try the model that answered last first; move a model that just failed to the back.
- **Result:** ~5 s per judgement after the first success (`judge` lines before and after 10:55 on 26 Nov). When flash-lite failed once, the run switched to gemini-3.1-flash-lite on its own.
- **Decision:** keep; the same idea would help every fallback chain.

## E10: A score when no music model is available
- **Problem:** all three Lyria models returned 429 on the free tier.
- **Change:** compose the score in code (`pipeline/score.py`): the tizita scale on D (D E F A B♭), strings, a bowed masinko line, krar plucks from the coffee cue, a soft kebero from the city cue, timed to the film's real shot lengths.
- **Result:** an 87.9 s score whose loudness follows the story (‑20.8 dB at the start, ‑15.6 dB at the city, fading under the end card). Licence-free and reproducible; each instrument is exported separately for the website mixer.
- **Decision:** keep as the fallback; a Lyria score can replace it later without changing the film stage.

## E11: Transitions that show time
- **Change:** soft 0.4 s dips through black between the memory shots; hard cuts from the city shot onward; a dip back to the father at the end.
- **Result:** past and present feel different without a word of narration.
