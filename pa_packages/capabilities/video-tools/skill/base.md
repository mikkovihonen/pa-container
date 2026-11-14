---
name: video-tools
description: "Use when inspecting, transcoding, trimming, muxing, or extracting tracks/frames from video and multimedia containers (MP4, MKV, WebM, MOV) using Fedora's dynamically linked ffmpeg-free, ffprobe, mediainfo, and mkvtoolnix."
---

# Video Processing (`video-tools`)

## Tool Triage

| Task | Tool | Primary Command |
|---|---|---|
| Structured stream/codec JSON inspection | `ffprobe` | `ffprobe -v error -show_format -show_streams -of json input.mp4` |
| Human-readable container and tag report | `mediainfo` | `mediainfo input.mp4` |
| Transcode, scale, filter, or extract frames | `ffmpeg` | `ffmpeg -i input.mp4 -c:v libsvtav1 -crf 30 -c:a libopus output.mkv` |
| Lossless remux / MKV track assembly | `mkvmerge` | `mkvmerge -o output.mkv video.mp4 subtitles.srt` |
| Extract specific tracks (subs, audio, chapters) from MKV | `mkvextract` | `mkvextract input.mkv tracks 2:subtitles.srt` |
| Edit MKV metadata/track flags in place without remuxing | `mkvpropedit` | `mkvpropedit movie.mkv --edit track:a1 --set language=fin` |

## Fedora `ffmpeg-free` Codec Selection

This environment uses Fedora 45's dynamically linked `ffmpeg-free` (`libavcodec-free` 9.0.2). **Do not use `-c:v libx264` or `-c:v libx265`** (they are not in `ffmpeg-free`). Use the encoders in the table below:

| Target Format | Encoder Flag | Recommended Quality / Bitrate Flags | Notes |
|---|---|---|---|
| **H.264 (AVC)** | `-c:v libopenh264` | `-b:v 4M -maxrate 6M` | Cisco OpenH264; uses bitrate (`-b:v`), not `-crf` |
| **AV1 (replaces H.265/HEVC)** | `-c:v libsvtav1` | `-crf 30 -preset 6 -pix_fmt yuv420p10le` | Fast, high-efficiency encoder for MP4, MKV, and WebM |
| **VP9 (WebM / MKV)** | `-c:v libvpx-vp9` | `-crf 30 -b:v 0 -row-mt 1` | Widely compatible web video codec |
| **AAC Audio** | `-c:a libfdk_aac` or `-c:a aac` | `-b:a 192k` | Both `fdk-aac-free` and native AAC are available |
| **Opus Audio** | `-c:a libopus` | `-b:a 128k` | Preferred modern audio codec for MKV/WebM/MP4 |
| **MP3 Audio** | `-c:a libmp3lame` | `-q:a 2` | VBR high-quality MP3 |
| **Stream Copy (No Re-encode)** | `-c copy` | — | Works for all codecs including HEVC/H.265 |

*Note on decoding:* `ffmpeg-free` natively **decodes** H.264, HEVC (H.265), VVC (H.266), AV1 (`libdav1d`), VP8/VP9, ProRes, and MPEG-2/4.

## Common Recipes

### Transcode Any Video (Including HEVC) to Web-Compatible H.264 MP4

```sh
ffmpeg -y -i input.mov -c:v libopenh264 -b:v 3M -pix_fmt yuv420p -c:a libfdk_aac -b:a 160k -movflags +faststart output.mp4
```

### High-Efficiency Transcode to AV1 in MP4 or MKV

```sh
ffmpeg -y -i input.mp4 -c:v libsvtav1 -crf 30 -preset 6 -c:a libopus -b:a 128k output.mkv
```

### Fast Keyframe Cut Without Re-encoding

Place `-ss` before `-i` for instant keyframe seeking and use `-c copy`:

```sh
ffmpeg -y -ss 00:01:30 -to 00:02:45 -i input.mp4 -c copy clip.mp4
```

### Extract Single Frame or Thumbnail Contact Sheet

```sh
# Single frame at 15 seconds
ffmpeg -y -ss 00:00:15 -i input.mp4 -frames:v 1 frame.png

# 4x3 contact sheet sampling every 10 seconds
ffmpeg -y -i input.mp4 -vf "fps=1/10,scale=320:-1,tile=4x3" -frames:v 1 sheet.jpg
```

### Extract Audio Track Losslessly

```sh
ffmpeg -y -i input.mp4 -vn -c:a copy audio.m4a
```

## Caveats and Cross-References

- **`ffplay` is not installed:** The container is headless with no audio output device. Inspect video content by extracting frames (`-frames:v 1`) or contact sheets.
- **Audio-only processing & speech-to-text:** Route pure audio effects, spectrograms, loudness normalization, and offline Whisper transcription to `sound-tools`.
