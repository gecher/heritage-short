"""Call every provider once, log each call to runs.jsonl, and say what works.

Run it first, and again whenever something breaks: free tiers and model ids change weekly.
"""
from __future__ import annotations

import base64
import wave

import requests

from pipeline.common import OUT, call_model, env, gemini_client, log_call, text_models


def gemini_text() -> str:
    client = gemini_client()
    models = list(client.models.list())
    lines = [f"{m.name}\t{','.join(m.supported_actions or [])}" for m in models]
    (OUT / "models.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"  {len(models)} models (saved to outputs/models.txt):")
    for line in lines:
        print("    " + line.replace("models/", ""))
    failed = []
    for model in text_models():  # fall back when a model is overloaded
        try:
            reply = call_model("smoke", "-", "gemini", model, {"prompt": "hello"},
                               lambda: client.models.generate_content(
                                   model=model, contents="Say 'hello, family' in Amharic, one line only."),
                               attempts=2)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{model} ({type(exc).__name__})")
            continue
        note = f" (after {', '.join(failed)} failed)" if failed else ""
        return f"{model}: {reply.text.strip()}{note}"
    raise RuntimeError("no text model answered: " + "; ".join(failed))


TTS_CANDIDATES = [  # unlisted TTS ids are often still callable; try the likely ones in order
    "gemini-3.8-flash-tts", "gemini-3.8-flash-preview-tts", "gemini-3.8-flash",
    "gemini-2.5-flash-preview-tts", "gemini-2.5-flash-tts", "gemini-omni-flash-preview",
]


def gemini_tts() -> str:
    from google.genai import types
    client = gemini_client()
    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore"))))
    candidates = [env("GEMINI_TTS_MODEL")] if env("GEMINI_TTS_MODEL") else TTS_CANDIDATES
    tried = []
    for model in candidates:
        try:
            reply = call_model("smoke", "-", "gemini", model, {"voice": "Kore", "probe": True},
                               lambda: client.models.generate_content(
                                   model=model, contents="Say warmly: Selam, this is a test.", config=config),
                               attempts=1)
            pcm = reply.candidates[0].content.parts[0].inline_data.data
        except Exception as exc:  # noqa: BLE001 - try the next candidate
            tried.append(f"{model} ({type(exc).__name__})")
            continue
        path = OUT / "narration" / "smoke.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
        note = f" after trying {', '.join(tried)}" if tried else ""
        return f"{model} works -> wrote {path.relative_to(OUT.parent)} ({len(pcm) / 48000:.1f}s){note}. Put GEMINI_TTS_MODEL={model} in .env"
    raise RuntimeError("no TTS model answered: " + "; ".join(tried))


def cloudflare_image() -> str:
    account, token = env("CLOUDFLARE_ACCOUNT_ID"), env("CLOUDFLARE_API_TOKEN")
    model = env("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
    params = {"prompt": "a clay coffee pot (jebena) on a woven tray, warm morning light", "steps": 4}  # flux-1-schnell rejects "seed" (Cloudflare error 5006)

    def go() -> bytes:
        r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=params, timeout=120)
        if not r.ok:  # show Cloudflare's own error message, not just the status code
            raise RuntimeError(f"{r.status_code}: {r.text[:400]}")
        return base64.b64decode(r.json()["result"]["image"])
    img = call_model("smoke", "-", "cloudflare", model, params, go)
    path = OUT / "keyframes" / "smoke.jpg"
    path.write_bytes(img)
    return f"wrote {path.relative_to(OUT.parent)} ({len(img) // 1024} KB)"


def kaggle() -> str:
    user, key = env("KAGGLE_USERNAME"), env("KAGGLE_KEY")

    def go() -> int:
        r = requests.get("https://www.kaggle.com/api/v1/kernels/list", params={"user": user, "pageSize": 1},
                         auth=(user, key), timeout=60)
        r.raise_for_status()
        return r.status_code
    call_model("smoke", "-", "kaggle", "api", {}, go)
    return "credentials accepted (GPU quota: check kaggle.com > Settings)"


CHECKS = {
    "gemini text": (gemini_text, ["GEMINI_API_KEY"]),
    "gemini tts": (gemini_tts, ["GEMINI_API_KEY"]),
    "cloudflare image": (cloudflare_image, ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"]),
    "kaggle": (kaggle, ["KAGGLE_USERNAME", "KAGGLE_KEY"]),
}


def main() -> None:
    for name, (check, needs) in CHECKS.items():
        missing = [n for n in needs if not env(n)]
        if missing:
            print(f"[skip] {name}: set {', '.join(missing)} in .env")
            log_call(stage="smoke", shot="-", provider=name, status="skipped", missing=missing)
            continue
        try:
            print(f"[ ok ] {name}: {check()}")
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {name}: {type(exc).__name__}: {str(exc)[:200]}")
