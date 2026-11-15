---
name: sound-tools
description: "Use when inspecting, converting, trimming, filtering, normalizing, or splitting audio files (WAV, FLAC, Opus, Ogg Vorbis, MP3, AAC/M4A), generating audio spectrogram images, or transcribing speech to text with whisper-cpp."
---

# Audio Processing (`sound-tools`)

Provides audio manipulation and analysis utilities via SoX, FAAD2, FLAC/Opus encoders, and offline speech-to-text with `whisper-cli` from `whisper-cpp`.

## Tool Overview

| Task | Tool | Primary Command |
|---|---|---|
| Inspect sample rate, channels, duration, encoding | `soxi` | `soxi input.wav` |
| Resample, trim, concat, apply effects, convert audio | `sox` | `sox input.mp3 -r 16000 -c 1 -b 16 output.wav` |
| Render audio spectrogram to PNG | `sox` (`spectrogram`) | `sox input.wav -n spectrogram -o spectrogram.png` |
| Decode AAC / M4A to WAV or stdout pipe | `faad` (`faad2`) | `faad -o output.wav input.m4a` |
| Encode / decode lossless FLAC | `flac` / `metaflac` | `flac --best input.wav -o output.flac` |
| Encode / decode Opus audio | `opusenc` / `opusdec` | `opusenc --bitrate 96 input.wav output.opus` |
| Transcribe speech to text with Whisper | `whisper-cli` | `whisper-cli -m model.bin -f input_16k.wav` |

## Common Recipes

### Decode M4A / AAC Audio

```sh
# Decode M4A to WAV
faad -o output.wav recording.m4a

# Pipe M4A through SoX to resample to 16 kHz mono WAV
faad -q -w recording.m4a | sox - -r 16000 -c 1 -b 16 normalized_16k.wav
```

### High-Resolution Audio Spectrogram PNG

```sh
sox input.wav -n spectrogram -x 1200 -y 513 -z 90 -t "Audio Spectrogram" -o spec.png
```

### Offline Speech Transcription with `whisper-cli`

`whisper-cli` requires 16000 Hz 16-bit mono WAV input:

```sh
# 1. Resample input audio to 16 kHz mono WAV
sox input.mp3 -r 16000 -c 1 -b 16 /tmp/input_16k.wav

# 2. Transcribe using whisper-cli
whisper-cli -m /usr/local/share/whisper/ggml-base.bin -f /tmp/input_16k.wav --output-txt
```

### Trim, Fade, and Normalize Voice Audio

```sh
sox input.wav cleaned.wav highpass 80 norm -1 trim 0 60 fade 0.5 0 1.0
```

## Guidelines
- **Headless execution**: Audio hardware playback (`play`, `rec`) is not available in headless microVMs. Always read and write audio to files or stdout pipes.
- **Output paths**: Write intermediate audio files to `/tmp/pa-media`.
