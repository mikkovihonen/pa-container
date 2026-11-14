---
name: sound-tools
description: "Use when inspecting, converting, trimming, filtering, normalizing, or splitting audio files (WAV, FLAC, Opus, Ogg Vorbis, MP3, AAC/M4A), generating audio spectrogram images, or transcribing speech to text."
---

# Audio Processing (`sound-tools`)

## Tool Triage

| Task | Tool | Primary Command |
|---|---|---|
| Inspect sample rate, channels, duration, encoding | `soxi` | `soxi input.wav` |
| Resample, trim, concat, apply effects, convert WAV/FLAC/MP3/OGG | `sox` | `sox input.mp3 -r 16000 -c 1 -b 16 output.wav` |
| Render audio spectrogram to PNG | `sox` (`spectrogram` effect) | `sox input.wav -n spectrogram -o spectrogram.png` |
| Decode AAC / M4A to WAV or stdout pipe | `faad` (`faad2`) | `faad -o output.wav input.m4a` |
| Encode / decode / tag lossless FLAC | `flac` / `metaflac` | `flac --best input.wav -o output.flac` |
| Encode / decode Opus (preferred lossy codec) | `opusenc` / `opusdec` | `opusenc --bitrate 96 input.wav output.opus` |
| Encode / decode Ogg Vorbis | `oggenc` / `oggdec` | `oggenc -q 6 input.wav -o output.ogg` |
| Encode MP3 / MP2 | `lame` / `twolame` | `lame -V 2 input.wav output.mp3` |
| Split lossless audio by CUE sheet or time intervals | `shnsplit` (`shntool`) | `shnsplit -f album.cue -t "%n-%t" -o flac album.flac` |
| Batch peak/RMS waveform normalization | `normalize-audio` | `normalize-audio -b *.wav` |
| Lossless ReplayGain tag adjustment (Vorbis / MP3) | `vorbisgain` / `mp3gain` | `mp3gain -r -k track.mp3` |

## Common Recipes

### Decode M4A / AAC Audio Without `ffmpeg`

`sox` does not read `.m4a` natively; decode with `faad` to a file or pipe directly into `sox` / `opusenc`:

```sh
# Decode M4A to WAV
faad -o output.wav recording.m4a

# Pipe M4A through SoX to resample to 16 kHz mono WAV
faad -q -w recording.m4a | sox - -r 16000 -c 1 -b 16 normalized_16k.wav
```

### Generate a High-Resolution Audio Spectrogram PNG

`sox` renders spectrograms natively without needing `video-tools`:

```sh
sox input.wav -n spectrogram -x 1200 -y 513 -z 90 -t "Audio Spectrogram" -o spec.png
```

### Trim, Fade, and Normalize Voice Audio

```sh
sox input.wav cleaned.wav highpass 80 norm -1 trim 0 60 fade 0.5 0 1.0
```

### Split Audio on Silence into Numbered Chunks

```sh
sox recording.wav chunk_%03d.wav silence 1 0.3 1% 1 0.8 1% : newfile : restart
```

## Caveats

- **No hardware audio devices:** `rec` and `play` cannot access soundcards in the container. Always read and write files or pipes.
- **`normalize` binary name:** Fedora installs the `normalize` package binary as `normalize-audio` to avoid naming conflicts.
