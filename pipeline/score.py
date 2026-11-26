"""A film score composed in code, in the Ethiopian tizita mode. Used when no music model answers.

Why: Lyria (the Gemini API's music model) has no free quota on this key, and the placeholder
drone was not music. This module writes an original, licence-free score from the storyboard's
music block and the film's real cue times:

  tizita (minor) on D: D E F A Bb, the pentatonic mode of Ethiopian longing and memory
  strings  a soft pad (additive, detuned voices) carrying the harmony: the "classical" layer
  masinko  a bowed one-string fiddle melody with slides and vibrato, from the first shot
  krar     plucked lyre arpeggios, entering at the coffee cue
  kebero   a low, soft drum, entering at the city cue, leaving when the theme returns
Everything is numpy: no samples, no downloads, so every run produces the same file.
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

import numpy as np

SR = 48000
VERSION = 1
TIZITA = [0, 2, 3, 7, 8]          # semitones above the root: D E F A Bb
D3 = 146.83


def hz(degree: int, octave: int = 0) -> float:
    """degree 0-4 in the tizita scale (may go beyond 4 or below 0), octave relative to D3."""
    o, d = divmod(degree, 5)
    return D3 * 2 ** ((TIZITA[d] + 12 * (o + octave)) / 12)


def env(n: int, attack: float, release: float) -> np.ndarray:
    a, r = max(1, int(attack * SR)), max(1, int(release * SR))
    e = np.ones(n)
    e[:min(a, n)] = np.linspace(0, 1, min(a, n))
    e[-min(r, n):] *= np.linspace(1, 0, min(r, n))
    return e


def lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(spec / (1 + (f / cutoff) ** 4), len(x))


def strings(total: float, chords: list[tuple[float, float, list[float]]], level) -> np.ndarray:
    out = np.zeros(int(total * SR))
    for start, length, freqs in chords:
        n = int(length * SR)
        t = np.arange(n) / SR
        e = env(n, 1.8, 2.0)
        for f in freqs:
            for detune in (-0.004, 0.0, 0.0045):
                vib = 1 + 0.003 * np.sin(2 * np.pi * 4.7 * t + 7 * f)
                phase = 2 * np.pi * f * (1 + detune) * np.cumsum(vib) / SR
                tone = sum(np.sin(k * phase) / k * np.exp(-0.28 * k) for k in range(1, 8))
                i = int(start * SR)
                out[i:i + n] += (tone * e)[: len(out) - i]
    out *= level(np.arange(len(out)) / SR)
    return lowpass(out, 2400)


def masinko(total: float, phrase: list[tuple[float, float, float]], level) -> np.ndarray:
    """phrase: (start, length, frequency). Slides between notes like a bowed one-string fiddle."""
    n = int(total * SR)
    freq = np.full(n, phrase[0][2])
    amp = np.zeros(n)
    for start, length, f in phrase:
        i, m = int(start * SR), int(length * SR)
        freq[i:] = f
        amp[i:i + m] = np.maximum(amp[i:i + m], env(m, 0.35, 0.6)[: max(0, min(m, n - i))])
    k = int(0.09 * SR)                                   # portamento: smooth the pitch steps
    freq = np.convolve(freq, np.ones(k) / k, mode="same")
    t = np.arange(n) / SR
    vib = 1 + 0.007 * np.sin(2 * np.pi * 5.4 * t) * np.clip(t % 4 / 1.5, 0, 1)
    phase = 2 * np.pi * np.cumsum(freq * vib) / SR
    tone = np.sin(phase) + 0.6 * np.sin(2 * phase) + 0.45 * np.sin(3 * phase) + 0.2 * np.sin(4 * phase)
    return lowpass(tone * amp * level(t), 3500)


def krar(total: float, notes: list[tuple[float, float]], level) -> np.ndarray:
    out = np.zeros(int(total * SR))
    for start, f in notes:
        n = int(1.8 * SR)
        t = np.arange(n) / SR
        pluck = sum(np.sin(2 * np.pi * k * f * t) * np.exp(-t * (2.2 + 1.6 * k)) / k for k in range(1, 7))
        pluck[: int(0.004 * SR)] *= np.linspace(0, 1, int(0.004 * SR))
        i = int(start * SR)
        out[i:i + n] += pluck[: len(out) - i]
    return out * level(np.arange(len(out)) / SR)


def kebero(total: float, hits: list[tuple[float, float]]) -> np.ndarray:
    out = np.zeros(int(total * SR))
    rng = np.random.default_rng(1931)
    for start, vel in hits:
        n = int(0.7 * SR)
        t = np.arange(n) / SR
        body = np.sin(2 * np.pi * np.cumsum(55 + 45 * np.exp(-t * 18)) / SR) * np.exp(-t * 6)
        slap = lowpass(rng.standard_normal(n) * np.exp(-t * 60), 900) * 0.3
        i = int(start * SR)
        out[i:i + n] += ((body + slap) * vel)[: len(out) - i]
    return out


def reverb(x: np.ndarray, seconds: float = 2.4, wet: float = 0.28, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    ir = rng.standard_normal(len(t)) * np.exp(-t / 0.55)
    ir = lowpass(ir, 5000)
    ir /= np.sqrt((ir ** 2).sum())
    size = 1 << int(np.ceil(np.log2(len(x) + len(ir))))
    tail = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
    return (1 - wet) * x + wet * tail


def compose(total: float, cues: list[float], out: Path, stems_dir: Path | None = None) -> Path:
    """total: film length in seconds; cues: start times of [mountains, coffee, city, return]."""
    beat = 60 / 72
    bar = 4 * beat
    _, coffee, city, back = cues

    def level(t):                                        # the arc of the film
        lv = np.interp(t, [0, coffee, city, back, total - 3, total], [0.55, 0.75, 0.95, 0.65, 0.5, 0.0])
        return lv

    # Harmony: two-bar chords moving within the mode (Dm, Bb, Dm, F/A, Bb, A-sus)
    progression = [[hz(0, -1), hz(3, -1), hz(2)], [hz(4, -2), hz(2, -1), hz(0)], [hz(0, -1), hz(3, -1), hz(2)],
                   [hz(2, -1), hz(3, -1), hz(0, 1)], [hz(4, -2), hz(2, -1), hz(0)], [hz(3, -2), hz(1, -1), hz(3, -1)]]
    chords, t, i = [], 0.0, 0
    while t < total:
        chords.append((t, min(2 * bar + 1.5, total - t), progression[i % len(progression)]))
        t += 2 * bar
        i += 1
    chords[-1] = (chords[-1][0], total - chords[-1][0], [hz(0, -1), hz(3, -1), hz(0)])   # resolve to D

    # Masinko: a slow tizita melody, phrases of 2 bars with rests, the opening theme returning at the end
    theme = [(5, 2), (4, 1), (3, 1), (2, 2), (None, 2), (3, 1), (2, 1), (1, 1), (0, 1), (2, 2), (None, 2),
             (5, 1), (6, 1), (5, 1), (4, 1), (3, 3), (None, 1), (2, 1), (1, 1), (0, 4), (None, 4)]
    phrase, t = [], 1.5 * beat
    while t < total - 6:
        for degree, beats in theme:
            if degree is not None and t + beats * beat < total - 3:
                phrase.append((t, beats * beat * 1.05, hz(degree, 1)))
            t += beats * beat
    # Krar: broken chords in eighths from the coffee cue to the end card
    pattern = [0, 2, 3, 2, 5, 3, 2, 1]
    plucks, t, k = [], coffee, 0
    while t < total - 4:
        plucks.append((t, hz(pattern[k % len(pattern)], 0)))
        t += beat / 2
        k += 1
    # Kebero: soft beats 1 and 3, a ghost on the "and" of 4, from the city cue until the theme returns
    hits, t = [], city
    while t < back:
        hits += [(t, 0.9), (t + 2 * beat, 0.6), (t + 3.5 * beat, 0.3)]
        t += bar

    s = strings(total, chords, level)
    m = masinko(total, phrase, level)
    k_ = krar(total, plucks, level)
    d = kebero(total, hits)
    parts = {  # (left, right) per instrument: strings wide, masinko left, krar right, kebero centre
        "strings": (0.30 * s, 0.30 * np.roll(s, int(0.011 * SR))),
        "masinko": (0.24 * m, 0.15 * m),
        "krar": (0.10 * k_, 0.17 * k_),
        "kebero": (0.30 * d, 0.30 * d),
    }
    left = sum(p[0] for p in parts.values())
    right = sum(p[1] for p in parts.values())
    fade = env(len(left), 3.0, 6.0)[:, None]
    mix = np.stack([reverb(left, seed=7), reverb(right, seed=8)], axis=1) * fade
    scale = 10 ** (-3 / 20) / np.max(np.abs(mix))       # peak at -3 dBFS
    write_wav(out, mix * scale)
    if stems_dir is not None:                            # each instrument alone, same balance, for the website mixer
        for name, (l, r) in parts.items():
            stem = np.stack([reverb(l, seed=7), reverb(r, seed=8)], axis=1) * fade * scale
            write_wav(stems_dir / f"{name}.wav", stem)
    return out


def write_wav(path: Path, x: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def compose_for(board: dict[str, Any], lengths: dict[str, float], end_card: float, out: Path,
                stems_dir: Path | None = None) -> Path:
    starts, t = {}, 0.0
    for shot in board["shots"]:
        starts[shot["id"]] = t
        t += lengths[shot["id"]]
    cues = [starts[c["at_shot"]] for c in board["music"]["cues"]]
    if len(cues) != 4:
        cues = [0.0, t * 0.45, t * 0.62, t * 0.85]
    return compose(t + end_card, cues, out, stems_dir)
