## Feature: `whisper` (Offline In-Container Speech-to-Text)

Provides `/usr/local/bin/whisper-cli`, dynamically linked against Fedora's `whisper-cpp` (`libwhisper.so.1` + OpenBLAS) and `libsndfile.so.1`, with the quantized multilingual model pre-staged at `/usr/local/share/whisper/ggml-base-q5_1.bin`. Everything runs 100% offline.

### Audio Input Requirement (16 kHz PCM)

`whisper-cli` reads WAV, FLAC, and Ogg files (or `-` stdin) via `libsndfile`, and **requires a 16000 Hz sample rate**. Always resample inputs to 16 kHz mono 16-bit WAV with `sox` (and `faad` for `.m4a`) before transcription:

```sh
# From WAV, MP3, FLAC, or OGG
sox input.mp3 -r 16000 -c 1 -b 16 /tmp/input_16k.wav
whisper-cli -l auto /tmp/input_16k.wav

# Direct pipe from M4A / AAC without intermediate file
faad -q -w memo.m4a | sox - -t wav -r 16000 -c 1 -b 16 - | whisper-cli -l fi -
```

### Output Formats and Flags

| Flag | Description | Example |
|---|---|---|
| *(default)* | Timestamped lines (`[HH:MM:SS.mmm --> HH:MM:SS.mmm]  text`) | `whisper-cli /tmp/input_16k.wav` |
| `-nt` / `--no-timestamps` | Plain text only on `stdout` | `whisper-cli -nt /tmp/input_16k.wav > transcript.txt` |
| `-osrt` | SubRip (`.srt`) subtitles on `stdout` | `whisper-cli -osrt /tmp/input_16k.wav > captions.srt` |
| `-ovtt` | WebVTT (`.vtt`) subtitles on `stdout` | `whisper-cli -ovtt /tmp/input_16k.wav > captions.vtt` |
| `-oj` | Structured JSON with segment start/end seconds on `stdout` | `whisper-cli -oj /tmp/input_16k.wav > result.json` |
| `-l <code>` | Spoken language (`en`, `fi`, `sv`, `de`, `auto`, etc.; default `en`) | `whisper-cli -l fi /tmp/input_16k.wav` |
| `--translate` | Translate non-English speech into English text | `whisper-cli -l fi --translate /tmp/input_16k.wav` |
| `-m <path>` | Override model file (or set `WHISPER_MODEL_PATH`) | `whisper-cli -m custom.bin /tmp/input_16k.wav` |
