"""Narration stage: one Amharic audio file per shot from Gemini TTS.

Cached by everything the audio depends on (model, voice, style instruction, language, text),
so editing one line in storyboard.json regenerates only that shot's audio. Writes
outputs/narration/manifest.json with each file and its measured duration and pace.
"""
from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

from pipeline.common import OUT, cache_key, cached_path, call_model, env, gemini_client, load_storyboard, log_call

RATE = 24000  # Gemini TTS returns 16-bit mono PCM at 24 kHz
# Each TTS model has its own free daily quota (10 requests/day when measured), so fall back in order.
DEFAULT_CHAIN = "gemini-3.8-flash-tts,gemini-3.8-flash-lite-tts,gemini-3.1-flash-tts-preview,gemini-2.5-flash-preview-tts,gemini-2.5-pro-preview-tts"


def tts_models() -> list[str]:
    first = env("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
    chain = (env("GEMINI_TTS_FALLBACKS", DEFAULT_CHAIN) or "").split(",")
    return [first] + [m.strip() for m in chain if m.strip() and m.strip() != first]


def syllables(text: str) -> int:
    """Ge'ez script is an abugida: each Ethiopic character (fidel) is about one syllable.
    For other scripts, fall back to about 1.5 syllables per word."""
    fidel = sum(1 for ch in text if "\u1200" <= ch <= "\u137f" and ch not in "\u1361\u1362\u1363\u1364")
    return fidel or round(len(text.split()) * 1.5)


def max_plausible_seconds(text: str) -> float:
    """Quality gate: even slow, warm narration is above ~2.5 syllables/s. Far longer audio means
    the model spoke something else (for example, it read the style instruction aloud)."""
    return syllables(text) / 2.5 + 1.5


def is_quota(exc: Exception) -> bool:
    return "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc)


def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def speak(text: str, voice: str, instruction: str, model: str, shot: str) -> bytes:
    from google.genai import types
    client = gemini_client()
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))))
    # Director style ("Say ...: <text>") is read as direction, not spoken; a separate paragraph was spoken aloud.
    prompt = f"{instruction.rstrip(' .:')}: {text}"
    reply = call_model("narration", shot, "gemini", model, {"voice": voice, "chars": len(text)},
                       lambda: client.models.generate_content(model=model, contents=prompt, config=config),
                       attempts=2)
    return reply.candidates[0].content.parts[0].inline_data.data


def spoken_text(text: str, pronunciation: dict[str, str]) -> str:
    """Apply the storyboard's pronunciation dictionary: what the voice model is sent."""
    for written, spoken in pronunciation.items():
        text = text.replace(written, spoken)
    return text


def say(text: str, voice: str | None = None) -> Path:
    """Speak one test phrase (for pronunciation trials); cached and logged like any other line."""
    board = load_storyboard()
    voice = voice or board["voice"]["name"]
    instruction, model = board["voice"]["style_instruction"], tts_models()[0]
    key = cache_key(stage="narration-test", model=model, voice=voice, instruction=instruction, text=text)
    folder = OUT / "narration" / "_tests"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"test-{key}.wav"
    if not path.exists():
        pcm = speak(text, voice, instruction, model, "test")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm)
    print(f"{path.relative_to(OUT.parent)}  <- {text}")
    return path


def run(board: dict[str, Any] | None = None) -> dict[str, Any]:
    board = board or load_storyboard()
    voice, instruction = board["voice"]["name"], board["voice"]["style_instruction"]
    chain, current = tts_models(), 0
    manifest: dict[str, Any] = {}
    for shot in board["shots"]:
        sid, written = shot["id"], shot["narration"].strip()
        if not written:
            manifest[sid] = None
            continue
        text = spoken_text(written, board.get("pronunciation", {}))  # the key follows what is SPOKEN
        inputs = dict(stage="narration", voice=voice, instruction=instruction, language=board["language"], text=text)
        if shot.get("take", 1) > 1:  # take 1 keeps the existing cache keys
            inputs["take"] = shot["take"]
        # reuse a cached take from any model in the chain (preferred model first)
        path = next((p for m in chain if (p := cached_path("narration", sid, cache_key(model=m, **inputs), "wav")).exists()), None)
        if path:
            log_call(stage="narration", shot=sid, status="cache_hit", output=path.name)
        while path is None and current < len(chain):
            model = chain[current]
            target = cached_path("narration", sid, cache_key(model=model, **inputs), "wav")
            try:
                pcm = speak(text, voice, instruction, model, sid)
            except Exception as exc:  # noqa: BLE001
                if not is_quota(exc):
                    raise
                print(f"  {model}: daily quota used up, switching to the next TTS model")
                current += 1
                continue
            words, seconds = len(text.split()), len(pcm) / (2 * RATE)
            if seconds > max_plausible_seconds(text):
                bad = target.with_suffix(".rejected.wav")
                with wave.open(str(bad), "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm)
                log_call(stage="narration", shot=sid, model=model, status="rejected",
                         reason=f"{seconds:.1f}s for {words} words", output=bad.name)
                print(f"  {sid}: REJECTED {seconds:.1f}s for {words} words (kept as {bad.name} to listen to)")
                break
            with wave.open(str(target), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm)
            path = target
        if path is None:
            manifest[sid] = None
            if current >= len(chain):
                print(f"  {sid}: no TTS quota left today on any model")
            continue
        seconds, words = wav_seconds(path), len(text.split())
        manifest[sid] = {"file": str(path.relative_to(OUT.parent)).replace("\\", "/"),
                         "seconds": round(seconds, 2), "words": words, "syllables": syllables(text),
                         "syllables_per_second": round(syllables(text) / seconds, 2) if seconds else None,
                         "words_per_second": round(words / seconds, 2) if seconds else None,
                         "fits_shot": seconds <= shot["duration"] - 0.5}
        flag = "" if manifest[sid]["fits_shot"] else f"  <-- longer than the {shot['duration']}s shot"
        print(f"  {sid}: {seconds:4.1f}s, {words} words, {manifest[sid]['syllables_per_second']} syllables/s{flag}")
    (OUT / "narration" / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    missing = [k for k, v in manifest.items() if v is None and any(s["id"] == k and s["narration"] for s in board["shots"])]
    if missing:
        print(f"  missing narration for {', '.join(missing)}: rerun later; finished lines are cached")
    return manifest
