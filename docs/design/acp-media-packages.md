# Plan: Media Agent Capability Packages (image-tools, video-tools, sound-tools, 3d-tools, ocr-tools)

Status: **Implemented (v3).** This document specifies five new ACPs for media
processing. All Fedora package names, versions, shipped binaries, and codec links below were
verified against the Fedora 45 release repository (`fedora-minimal:45` is the agent base
image). All five packages rely on Fedora 45's dynamically linked shared libraries and distro
packages. Speech-to-text (`whisper` feature in `sound-tools`) runs offline inside the agent
container using a lightweight CLI compiled dynamically against Fedora's `whisper-cpp`
(`libwhisper.so`) and `libsndfile` (`libsndfile.so`) libraries, paired with a build-time
SHA-256-pinned GGML model.

## 1. Summary

Add five opt-in Agent Capability Packages under `pa_packages/`:

| Package | Category | Core payload | Features |
|---|---|---|---|
| `image-tools` | `media` | ImageMagick, ExifTool, exiv2, librsvg2-tools (`rsvg-convert`), webp/jpeg/tiff/png utilities, optipng, pngquant, pngcheck, potrace | `vips`, `jxl-heif`, `gmic` |
| `video-tools` | `media` | Fedora dynamically linked `ffmpeg-free` 9.0.2 (`libopenh264`, `libsvtav1`, `libvpx`, `fdk-aac-free`), mediainfo, mkvtoolnix | — (none) |
| `sound-tools` | `media` | SoX, faad2, flac, opus-tools, vorbis-tools, lame, twolame, shntool, normalize, vorbisgain, mp3gain | `whisper` (offline in-container STT dynamically linked against Fedora `whisper-cpp` + build-time pinned `ggml` model) |
| `3d-tools` | `media` | assimp, admesh, draco, openvdb | `trimesh` (default on), `blender`, `meshlab`, `openscad` |
| `ocr-tools` | `media` | tesseract with English and orientation data | `ocrmypdf`, 25 `lang-*` language features |

Payloads are Fedora distro packages — installed into the target image via
`collect_distro_packages` and dynamically linked against the distribution's shared libraries.
The only build-stage artifact is in `sound-tools`'s optional `whisper` feature, which compiles
a minimal `whisper-cli` entrypoint dynamically linked against Fedora's `whisper-cpp-devel`
(`libwhisper.so.1`) and `libsndfile-devel` (`libsndfile.so.1`) and stages a SHA-256-pinned
GGML model file (`ggml-base.en-q5_1.bin`). No MCP servers, no runtime network egress, and no
static binary duplication. The only runtime privilege change is `none`.

## 2. Design principles

1. **Five focused packages, not one `media-tools`.** Workspaces enable only what they
   need. Media payloads differ in size by an order of magnitude (`sound-tools` ≈ 40 MB vs
   the `blender` feature ≈ +400 MB). Skills stay focused per domain, following the
   `code-intelligence` triage-skill pattern.
2. **Distro-first, dynamically linked payloads everywhere.** Fedora 45 ships the runtime
   libraries for every tool in this plan. Using dynamically linked distro packages means:
    - CVE and bugfix updates arrive automatically via `microdnf`.
    - Shared libraries (`libavcodec-free`, `libopenblas`, `libgomp`, `libsndfile`, `libgs`,
      Qt6) are deduplicated across packages when multiple capabilities are enabled (e.g.
      `video-tools` and `3d-tools`/`blender` share the same `libav*` closure).
    - `video-tools` uses Fedora's native dynamically linked `ffmpeg-free` (~100 MB shared
      closure) instead of a 252 MB statically linked third-party binary tarball.
    - `sound-tools`'s `whisper` feature dynamically links against Fedora's `whisper-cpp`
      (`libwhisper.so.1`, `libggml*.so`) and `openblas` packages rather than compiling a
      monolithic static binary or pulling a multi-gigabyte PyTorch/pip stack.
3. **Lean core, heavy features.** Core payloads stay small. Heavy or specialized tools go
   behind features (`default: false`), following the `document-tools`/`docling` precedent.
   Exception: `ffmpeg-free` stays in `video-tools` core — it is the package's identity.
4. **One ffmpeg, owned by `video-tools`; self-sufficient audio decoding in `sound-tools`.**
   `video-tools` core installs `ffmpeg-free`. `sound-tools` declares no `ffmpeg` dependency;
   instead, it includes `faad2` (~0.5 MB) in core for AAC/M4A decoding and uses `sox`
   natively for spectrograms (`sox ... spectrogram`).
5. **No hard GUI dependencies, explicit headless environment flags.** Blender, MeshLab,
   and OpenSCAD run headless (`blender -b`, `QT_QPA_PLATFORM=offscreen meshlab`,
   `openscad -o out.stl`). Unlike `browser`/`chromium` (where GUI use is the point), none
   of these features declare `runtime.dependencies: [virtual-desktop]`. Skills teach the
   required headless flags and mention `virtual-desktop` as an optional companion.
6. **No runtime egress anywhere (`--network=none`).** No package or feature declares
   `egress.allow_hosts`. All tools, including `whisper` speech-to-text and `tesseract` OCR,
   execute 100% offline inside the container. Verification runs with `--network=none`.
7. **Skills are the payload that matters.** Agents already know the tools generically. The
   skills contribute environment-specific truth: Fedora `ffmpeg-free` codec selection
   (`libopenh264`, `libsvtav1`, `libfdk_aac`), ImageMagick security policy limits, headless
   Qt/OpenGL flags, `whisper-cli` pipelines, and format triage tables.
8. **Task-based boundaries with size isolation.** OCR extracts text, so it is document
   work, not image work — but it ships as its own `ocr-tools` package so OCR-only
   workspaces skip the Pandoc payload and languages get first-class features (section 9).

## 3. Verified Fedora 45 inventory

All rows verified against the F45 Everything repository metadata (aarch64). "Installed" is
the package's own installed size, excluding shared dependencies.

### 3.1 image-tools

| Fedora package | Version | Ships | Installed |
|---|---|---|---|
| `ImageMagick` | 7.1.2.32 | `magick`, `convert`, `identify`, `mogrify`, `montage`, `compare`, `composite`, `import`, `stream` | ~140 KB (+ `ImageMagick-libs` ~14.5 MB, pulled as dep) |
| `perl-Image-ExifTool` | 13.50 | `exiftool` | ~21 MB (+ `perl-interpreter` / `perl-libs` ~55 MB on minimal base) |
| `exiv2` | 0.28.9 | `exiv2` | ~12.5 MB |
| `librsvg2-tools` | 2.61.0 | `rsvg-convert` (headless SVG to PNG/PDF/PS rasterizer) | ~0.3 MB (+ `librsvg2` dep) |
| `libwebp-tools` | 1.6.0 | `cwebp`, `dwebp`, `webpmux`, `webpinfo`, `anim_*` | ~0.5 MB |
| `libjpeg-turbo-utils` | 3.1.4.1 | `cjpeg`, `djpeg`, `jpegtran` | ~0.5 MB |
| `libtiff-tools` | 4.7.2 | `tiffinfo`, `tiffcp`, `tiffset`, … | ~1.4 MB |
| `optipng` | 7.9.1 | `optipng` | ~0.2 MB |
| `pngquant` | 2.18.0 | `pngquant` | ~0.1 MB |
| `pngcheck` | 4.0.1 | `pngcheck` | ~0.2 MB |
| `potrace` | 1.16 | `potrace`, `mkbitmap` | ~0.3 MB |
| `vips` (feature) | 8.18.3 | `vips` (+ `vips-heif`) | ~3.7 MB |
| `libjxl-utils` (feature) | 0.11.2 | `cjxl`, `djxl`, `jxlinfo` | ~0.8 MB |
| `libheif-tools` (feature) | 1.23.5 | `heif-enc`, `heif-convert`, `heif-info` (+ `ImageMagick-heic`) | ~0.7 MB |
| `gmic` (feature) | 4.0.3 | `gmic` | ~24 MB |

Notes:

- Fedora ImageMagick 7 ships both the `magick` entrypoint and legacy `convert`/`mogrify`
  names. The skill teaches `magick <subcommand>` as primary.
- `librsvg2-tools` (`rsvg-convert`) complements `potrace`: `potrace` traces bitmap to SVG,
  while `rsvg-convert` renders SVG to PNG/PDF with full CSS and text support.
- Fedora's IM security policy (`/etc/ImageMagick/policy.xml`) blocks PS/EPS/PDF/XPS. The
  skill routes PDF rasterization to `pdftoppm` from `document-tools`.

### 3.2 video-tools

| Fedora package | Version | Ships | Installed |
|---|---|---|---|
| `ffmpeg-free` | 9.0.2 | `ffmpeg`, `ffprobe` (dynamically linked against `libav*-free`) | ~2.5 MB (+ ~95 MB shared `libav*-free` and codec libs) |
| `mediainfo` | 26.05 | `mediainfo` (CLI; GUIs are separate `mediainfo-qt`/`mediainfo-gui`) | ~0.2 MB |
| `mkvtoolnix` | 102.0 | `mkvmerge`, `mkvextract`, `mkvinfo`, `mkvpropedit` | ~32 MB |

Notes:

- **Dynamically linked Fedora `ffmpeg-free`:** Using `ffmpeg-free` directly from Fedora 45
  avoids the 252 MB static binary duplication (`ffmpeg` + `ffprobe`) and shares `libavcodec`,
  `libavformat`, `libavfilter`, and `libswscale` dynamically with other packages (`blender`,
  `vips`, `ImageMagick`).
- **Codec inventory in F45 `libavcodec-free` 9.0.2:**
    - **Video encoders:** `libopenh264` (H.264), `libsvtav1` / `libaom-av1` / `librav1e`
      (AV1), `libvpx` / `libvpx-vp9` (VP8/VP9), `libtheora`, `libxvid`, `libwebp`.
    - **Video decoders:** H.264, HEVC (H.265), VVC (H.266), AV1 (`libdav1d`), VP8/VP9,
      MPEG-2/4, ProRes, DNxHD.
    - **Audio encoders & decoders:** `libfdk_aac` (via `fdk-aac-free`) and native `aac`,
      `libopus`, `libvorbis`, `libmp3lame`, `libtwolame`, `flac`, PCM.
- **Skill guidance for Fedora codecs:** Because agents trained on generic internet corpora
  default to `-c:v libx264` and `-c:v libx265` (which are absent from `ffmpeg-free`), the
  `video-tools` skill explicitly teaches:
    - H.264 encode → `-c:v libopenh264` (note: uses `-b:v` bitrate control rather than `-crf`)
    - Modern high-efficiency encode (replaces `libx265`) → `-c:v libsvtav1 -crf 30 -preset 6`
      (MP4/MKV/WebM) or `-c:v libvpx-vp9 -crf 30 -b:v 0`
    - AAC encode → `-c:a libfdk_aac` or `-c:a aac`
    - Lossless container remuxing (`-c copy`) works for all streams including HEVC.
- **Note on `libavfilter-free` & `whisper-cpp`:** In Fedora 45, `libavfilter-free` already
  pulls in `whisper-cpp` (`libwhisper.so.1`) as a shared dependency for FFmpeg 9.0's
  `whisper` audio filter (`-af whisper=model=...`).

### 3.3 sound-tools

| Fedora package / Component | Version | Ships | Installed |
|---|---|---|---|
| `sox` | 14.4.2.0 | `sox`, `soxi`, `rec`/`play` (includes native `spectrogram` PNG generator) | ~2 MB (+ codec libs) |
| `faad2` | 2.11.1 | `faad` (CLI AAC/M4A decoder to WAV or stdout) | ~0.5 MB |
| `flac` | 1.5.0 | `flac`, `metaflac` | ~0.4 MB |
| `opus-tools` | 0.2 | `opusenc`, `opusdec`, `opusinfo` | ~0.2 MB |
| `vorbis-tools` | 1.4.3 | `oggenc`, `oggdec`, `ogginfo`, `ogg123` | ~1.7 MB |
| `lame` | 4.0 | `lame` | ~0.6 MB |
| `twolame` | 0.4.0 | `twolame` | ~0.2 MB |
| `shntool` | 3.0.10 | `shnsplit`, `shninfo`, `shnlen`, … | ~0.4 MB |
| `normalize` | 0.7.7 | `normalize-audio` | ~0.2 MB |
| `vorbisgain` | 0.37 | `vorbisgain` | ~0.1 MB |
| `mp3gain` | 1.6.2 | `mp3gain` | ~0.1 MB |
| `whisper-cpp` (feature runtime dep) | 1.8.x (F45) | `/usr/lib64/libwhisper.so.1`, `/usr/lib64/libggml*.so*` (dynamically linked to Fedora `openblas` & `libgomp`) | ~1.5 MB (+ `openblas` ~35 MB) |
| `libsndfile` (feature runtime dep) | 1.2.2 | `/usr/lib64/libsndfile.so.1` (already pulled by `sox`) | ~0.6 MB |
| `whisper-cli` + `ggml-base.en-q5_1.bin` (feature build payload) | 1.8.x / q5_1 | `/usr/local/bin/whisper-cli` (~25 KB ELF dynamically linked to `libwhisper.so.1` & `libsndfile.so.1`) + `/usr/local/share/whisper/ggml-base.en-q5_1.bin` | ~60 MB |

Notes:

- `sox` covers WAV/MP3/FLAC/Ogg/Opus pipelines and **native spectrogram rendering**
  (`sox in.wav -n spectrogram -o spec.png`).
- `faad2` (`faad`) decodes AAC and M4A containers directly in `sound-tools` core (~0.5 MB),
  so audio-only workspaces do not need `video-tools` for M4A files.
- **In-container Whisper (`whisper` feature) using distro dynamic libraries:**
    - Fedora 45 packages `whisper-cpp` (shared libraries `libwhisper.so.1` and `libggml*.so`,
      dynamically linked against Fedora's `openblas` and `libgomp`) and `whisper-cpp-devel`
      (`/usr/include/whisper.h`, `/usr/lib64/libwhisper.so`), but omits the CLI binary from
      the RPM.
    - Instead of compiling `whisper.cpp` from source or pulling static binaries,
      `features/whisper/build.sh` installs `whisper-cpp-devel` and `libsndfile-devel` in the
      builder stage and compiles a minimal C driver (`features/whisper/whisper-cli.c`, ~90
      lines) with `gcc -O2 whisper-cli.c -lwhisper -lsndfile -o whisper-cli`.
    - The resulting `/usr/local/bin/whisper-cli` binary is ~25 KB and links dynamically
      against Fedora's `libwhisper.so.1` and `libsndfile.so.1` in the target image (installed
      via `packages: ["whisper-cpp", "libsndfile"]`).
    - `features/whisper/build.sh` also downloads the quantized multilingual or English base
      model (`ggml-base.en-q5_1.bin` ≈ 60 MB, or `ggml-base-q5_1.bin` ≈ 60 MB for
      multilingual support) at build time, verifies its SHA-256 digest, and installs it to
      `/usr/local/share/whisper/ggml-base.bin`.
    - Supports plain text, SRT, VTT, and JSON timestamp outputs (`-otxt`, `-osrt`, `-ovtt`,
      `-oj`, `-l <lang>`, `-m <model_path>`).
- TTS remains out of scope.

### 3.4 3d-tools

| Fedora package | Version | Ships | Installed |
|---|---|---|---|
| `assimp` | 6.0.5 | `assimp` CLI (`version`, `info`, `export`, `extract`, `cmpdiff`) + libs | ~6.8 MB |
| `admesh` | 0.98.5 | `admesh` (STL check/repair/fill) | ~0.1 MB |
| `draco` | 1.5.7 | `draco_encoder`, `draco_decoder` | ~1.7 MB |
| `openvdb` | 13.1.0 | `vdb_print` (grid inspection; this build ships no `vdb_render`) | ~3.2 MB |
| `python3-trimesh` + deps (feature) | 5.1.0 | `python3-trimesh`, `python3-scipy`, `python3-networkx`, `python3-lxml` | ~5.3 MB (+ numpy/scipy/networkx/lxml) |
| `blender` (feature) | 5.2.2 | `blender` (headless `-b` first-class; `blender-thumbnailer`) | ~229 MB (+ ~200 MB deps, shares `libav*-free` with `video-tools`) |
| `meshlab` (feature) | 2025.07 | `meshlab` (2023.12+ merged `meshlabserver` into the main binary; CLI via `-i/-o` filters) | ~29 MB (+ Qt6 stack) |
| `openscad` (feature) | 2021.01 | `openscad` headless geometry export (`-o out.stl`) | ~7.7 MB (+ Qt/OpenGL deps) |

Notes:

- **Complete distro dependencies for `trimesh`:** Installing Fedora's `python3-scipy`,
  `python3-networkx`, and `python3-lxml` alongside `python3-trimesh` ensures hole repair
  (`fill_holes`), connected-component splitting, convex hulls, and `3MF`/`DAE` XML formats
  work out of the box using system Python 3.15 packages.
- **Headless `meshlab` requires `QT_QPA_PLATFORM=offscreen`:** MeshLab initializes
  `QApplication` on startup even for `--help` or `-i/-o` filter runs. Setting
  `QT_QPA_PLATFORM=offscreen` avoids X11 display crashes in headless containers.
- **Headless `openscad` scope:** Exports 3D/2D geometry (`STL`, `OFF`, `3MF`, `DXF`, `SVG`,
  `CSG`) on CPU without X11; `.png` preview rendering requires an X11/OpenGL context
  (`virtual-desktop`).

### 3.5 ocr-tools

| Fedora package | Version | Ships | Installed |
|---|---|---|---|
| `tesseract` | 5.5.3 | `tesseract` CLI; ships no language data itself | ~0.1 MB |
| `tesseract-libs` | 5.5.3 | libtesseract (pulled as dep) | ~3.0 MB |
| `leptonica` | 1.87.0 | libleptonica raster I/O for tesseract (pulled as dep) | ~3.2 MB |
| `tesseract-common` | 5.5.3 | owns `/usr/share/tesseract/tessdata/` and engine configs (pulled as dep) | ~0.02 MB |
| `tesseract-langpack-eng` | 4.1.0 | `eng.traineddata` (`tessdata_fast` LSTM model) | ~4.0 MB |
| `tesseract-osd` | 4.1.0 | `osd.traineddata` — orientation and script detection | ~10.3 MB |
| `ocrmypdf` (feature) | 16.13.0 | `ocrmypdf` (noarch); requires `tesseract`, `ghostscript`, pikepdf, img2pdf, pdfminer-six | ~1.3 MB + ~45 MB deps (`libgs` ~24.6 MB dominates) |

Notes:

- Fedora's `tesseract-langpack-*` packages ship `tessdata_fast` LSTM models (`--oem 1` /
  default `--oem 3`). Legacy `--oem 0` is unsupported and documented as a caveat in the skill.

## 4. Package manifests (implementation-ready skeletons)

YAML indentation follows the 4-space manifest style. Verification commands run with
`--network=none` via `/bin/sh -c`, stderr merged into stdout, exit code 0 required.
Pipelines avoid `| head -n` truncation so commands never fail with `SIGPIPE` (exit 141)
under `pipefail` shells.

### 4.1 `pa_packages/image-tools/package.yaml`

```yaml
schema_version: "0.7.0"
name: "image-tools"
version: "1.0.0"
description: "Image processing capability: ImageMagick conversion and effects, ExifTool/exiv2 metadata, WebP/JPEG/TIFF/PNG codec utilities, optimizers, rsvg-convert SVG rasterization, and potrace vectorization"
category: "media"
license: "GPL-2.0-or-later"

payload:
    type: distro_package
    packages:
        - "ImageMagick"
        - "perl-Image-ExifTool"
        - "exiv2"
        - "librsvg2-tools"
        - "libwebp-tools"
        - "libjpeg-turbo-utils"
        - "libtiff-tools"
        - "optipng"
        - "pngquant"
        - "pngcheck"
        - "potrace"

skill:
    enabled: true
    source: "skill/base.md"
    target_agents: ["all"]

features:
    vips:
        description: "libvips streaming image processing (vips CLI) with HEIF support, efficient for very large images"
        default: false
        payload:
            type: distro_package
            packages:
                - "vips"
                - "vips-heif"
        skill_fragment: "features/vips/skill/SKILL.md"
        verification:
            command: "vips --version"
            expected_output_contains: "vips"
    jxl-heif:
        description: "Modern still-image codecs: JPEG XL (cjxl/djxl) and HEIF/AVIF encode and decode (heif-enc/heif-convert, ImageMagick HEIC delegate)"
        default: false
        payload:
            type: distro_package
            packages:
                - "libjxl-utils"
                - "libheif-tools"
                - "ImageMagick-heic"
        skill_fragment: "features/jxl-heif/skill/SKILL.md"
        verification:
            command: "cjxl --version && heif-enc --version"
            expected_output_contains: "cjxl"
    gmic:
        description: "G'MIC image processing framework CLI with hundreds of filters and batch pipelines"
        default: false
        payload:
            type: distro_package
            packages:
                - "gmic"
        skill_fragment: "features/gmic/skill/SKILL.md"
        verification:
            command: "gmic -version"
            expected_output_contains: "gmic"

verification:
    command: "magick -version && exiftool -ver && rsvg-convert --version && cwebp -version && optipng -v"
    expected_output_contains: "ImageMagick"
```

### 4.2 `pa_packages/video-tools/package.yaml`

```yaml
schema_version: "0.7.0"
name: "video-tools"
version: "1.0.0"
description: "Video processing capability: Fedora dynamically linked ffmpeg-free (OpenH264, SVT-AV1, VP9, fdk-aac-free, and Whisper audio filter), MediaInfo metadata, and MKVToolNix muxing and track extraction"
category: "media"
license: "GPL-2.0-or-later AND LGPL-2.1-or-later"

payload:
    type: distro_package
    packages:
        - "ffmpeg-free"
        - "libavcodec-free"
        - "mediainfo"
        - "mkvtoolnix"

skill:
    enabled: true
    source: "skill/base.md"
    target_agents: ["all"]

verification:
    command: "ffmpeg -version && ffprobe -version && mediainfo --Version && mkvmerge --version"
    expected_output_contains: "ffmpeg"
```

### 4.3 `pa_packages/sound-tools/package.yaml`

```yaml
schema_version: "0.7.0"
name: "sound-tools"
version: "1.0.0"
description: "Audio processing capability: SoX effects, spectrograms, and analysis, FAAD2 AAC/M4A decode, FLAC/Ogg/Opus codecs, LAME/twolame MP3, shntool splitting, gain normalization, and optional offline Whisper speech-to-text"
category: "media"
license: "GPL-2.0-or-later AND BSD-2-Clause AND BSD-3-Clause AND MIT"

payload:
    type: distro_package
    packages:
        - "sox"
        - "faad2"
        - "flac"
        - "opus-tools"
        - "vorbis-tools"
        - "lame"
        - "twolame"
        - "shntool"
        - "normalize"
        - "vorbisgain"
        - "mp3gain"

skill:
    enabled: true
    source: "skill/base.md"
    target_agents: ["all"]

features:
    whisper:
        description: "Offline speech-to-text transcription using Fedora's dynamically linked whisper-cpp library (libwhisper.so + OpenBLAS) and a pre-staged ggml-base-q5_1 model"
        default: false
        payload:
            type: build
            script: "features/whisper/build.sh"
            packages:
                - "whisper-cpp"
                - "libsndfile"
        skill_fragment: "features/whisper/skill/SKILL.md"
        verification:
            command: "sox -n -r 16000 -c 1 -b 16 /tmp/stt-check.wav synth 0.5 sine 440 gain -5 && whisper-cli /tmp/stt-check.wav && rm -f /tmp/stt-check.wav"
            expected_output_contains: "whisper"

verification:
    command: "sox --version && faad -h 2>&1 && flac --version && opusenc --version"
    expected_output_contains: "sox"
```

#### `pa_packages/sound-tools/features/whisper/build.sh` & `whisper-cli.c` design

Because `pa_core` supports combining `type: build` (`script: ...`) with `packages: [...]`
(which `collect_distro_packages` installs in the final runtime stage), `features/whisper/build.sh`
performs two lightweight build-stage actions:

1. Installs `gcc`, `whisper-cpp-devel`, and `libsndfile-devel` in the builder stage and
   compiles `features/whisper/whisper-cli.c`:
   ```sh
   gcc -O2 -Wall "$(dirname "$0")/whisper-cli.c" \
       -lwhisper -lsndfile \
       -o "${STAGE_DIR}/usr/local/bin/whisper-cli"
   ```
    - `whisper-cli.c` uses `sf_open` (`libsndfile.so.1`) to read 16 kHz WAV/FLAC/OGG audio
     into float32 PCM samples, initializes `whisper_init_from_file_with_params`
     (`libwhisper.so.1`) defaulting to `/usr/local/share/whisper/ggml-base-q5_1.bin`
     (overridable via `-m <path>`), runs `whisper_full` using available CPU threads, and
     outputs timestamped (`[MM:SS.mmm --> MM:SS.mmm] text`), plain-text (`-nt`), SRT
     (`-osrt`), or JSON (`-oj`) transcripts.
    - `ldd /usr/local/bin/whisper-cli` resolves strictly to Fedora 45's shared libraries
     (`libwhisper.so.1`, `libggml.so`, `libsndfile.so.1`, `libopenblas.so.0`, `libgomp.so.1`).
2. Downloads the pinned `ggml-base-q5_1.bin` (~59.7 MB, multilingual including English and
   Finnish) from `huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base-q5_1.bin` at
   image **build time**, verifies its SHA-256 checksum (`42ddbe9f...` — pin exact digest in
   `build.sh`), and places it at
   `${STAGE_DIR}/usr/local/share/whisper/ggml-base-q5_1.bin`.

### 4.4 `pa_packages/3d-tools/package.yaml`

```yaml
schema_version: "0.7.0"
name: "3d-tools"
version: "1.0.0"
description: "3D model processing capability: assimp format conversion, admesh STL repair, Draco mesh compression, OpenVDB volume inspection, and optional trimesh scripting, Blender, MeshLab, and OpenSCAD"
category: "media"
license: "MPL-2.0 AND Apache-2.0 AND MIT AND GPL-2.0-or-later"

payload:
    type: distro_package
    packages:
        - "assimp"
        - "admesh"
        - "draco"
        - "openvdb"

skill:
    enabled: true
    source: "skill/base.md"
    target_agents: ["all"]

features:
    trimesh:
        description: "trimesh Python mesh toolkit with scipy, networkx, and lxml for load/convert/repair/analyze workflows (STL, OBJ, PLY, GLB/TF, 3MF)"
        default: true
        payload:
            type: distro_package
            packages:
                - "python3-trimesh"
                - "python3-scipy"
                - "python3-networkx"
                - "python3-lxml"
        skill_fragment: "features/trimesh/skill/SKILL.md"
        verification:
            command: "python3 -c 'import trimesh, numpy, scipy, networkx, lxml; print(\"trimesh\", trimesh.__version__)'"
            expected_output_contains: "trimesh"
    blender:
        description: "Blender headless scripting and rendering (bpy via 'blender -b --python', Cycles CPU); interactive use pairs with the virtual-desktop package"
        default: false
        payload:
            type: distro_package
            packages:
                - "blender"
        skill_fragment: "features/blender/skill/SKILL.md"
        verification:
            command: "blender -v"
            expected_output_contains: "Blender"
    meshlab:
        description: "MeshLab headless mesh processing, cleaning, and format conversion CLI ('QT_QPA_PLATFORM=offscreen meshlab -i in -o out')"
        default: false
        payload:
            type: distro_package
            packages:
                - "meshlab"
        skill_fragment: "features/meshlab/skill/SKILL.md"
        verification:
            command: "QT_QPA_PLATFORM=offscreen meshlab --help 2>&1"
            expected_output_contains: "meshlab"
    openscad:
        description: "OpenSCAD parametric solid modeling with headless STL/3MF/DXF/SVG export (2021.01 release)"
        default: false
        payload:
            type: distro_package
            packages:
                - "openscad"
        skill_fragment: "features/openscad/skill/SKILL.md"
        verification:
            command: "openscad -v 2>&1"
            expected_output_contains: "OpenSCAD"

verification:
    command: "assimp version && admesh --version && vdb_print -version"
    expected_output_contains: "assimp"
```

### 4.5 `pa_packages/ocr-tools/package.yaml`

```yaml
schema_version: "0.7.0"
name: "ocr-tools"
version: "1.0.0"
description: "OCR capability: tesseract text extraction from images and scanned pages, English baseline data with per-language feature packs, and optional ocrmypdf searchable-PDF layering"
category: "media"
license: "Apache-2.0 AND MPL-2.0 AND AGPL-3.0-or-later"

payload:
    type: distro_package
    packages:
        - "tesseract"
        - "tesseract-langpack-eng"
        - "tesseract-osd"

skill:
    enabled: true
    source: "skill/base.md"
    target_agents: ["all"]

features:
    ocrmypdf:
        description: "Adds searchable text layers to scanned PDFs: ocrmypdf with its ghostscript and pikepdf stack"
        default: false
        payload:
            type: distro_package
            packages:
                - "ocrmypdf"
        skill_fragment: "features/ocrmypdf/skill/SKILL.md"
        verification:
            command: "ocrmypdf --version"
            expected_output_contains: "ocrmypdf"
    lang-ara:
        description: "Arabic OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-ara"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "ara"
    lang-ces:
        description: "Czech OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-ces"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "ces"
    lang-chi-sim:
        description: "Chinese (Simplified) OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-chi_sim"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "chi_sim"
    lang-chi-tra:
        description: "Chinese (Traditional) OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-chi_tra"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "chi_tra"
    lang-dan:
        description: "Danish OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-dan"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "dan"
    lang-deu:
        description: "German OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-deu"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "deu"
    lang-ell:
        description: "Greek OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-ell"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "ell"
    lang-fin:
        description: "Finnish OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-fin"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "fin"
    lang-fra:
        description: "French OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-fra"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "fra"
    lang-heb:
        description: "Hebrew OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-heb"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "heb"
    lang-hin:
        description: "Hindi OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-hin"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "hin"
    lang-hun:
        description: "Hungarian OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-hun"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "hun"
    lang-ita:
        description: "Italian OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-ita"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "ita"
    lang-jpn:
        description: "Japanese OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-jpn"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "jpn"
    lang-kor:
        description: "Korean OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-kor"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "kor"
    lang-nld:
        description: "Dutch OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-nld"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "nld"
    lang-nor:
        description: "Norwegian OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-nor"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "nor"
    lang-pol:
        description: "Polish OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-pol"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "pol"
    lang-por:
        description: "Portuguese OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-por"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "por"
    lang-rus:
        description: "Russian OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-rus"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "rus"
    lang-spa:
        description: "Spanish OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-spa"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "spa"
    lang-swe:
        description: "Swedish OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-swe"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "swe"
    lang-tur:
        description: "Turkish OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-tur"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "tur"
    lang-ukr:
        description: "Ukrainian OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-ukr"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "ukr"
    lang-vie:
        description: "Vietnamese OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-vie"
        verification:
            command: "tesseract --list-langs"
            expected_output_contains: "vie"

verification:
    command: "tesseract --version && tesseract --list-langs"
    expected_output_contains: "eng"
```

## 5. File trees

```text
pa_packages/image-tools/
    package.yaml
    skill/base.md
    features/vips/skill/SKILL.md
    features/jxl-heif/skill/SKILL.md
    features/gmic/skill/SKILL.md

pa_packages/video-tools/
    package.yaml
    skill/base.md

pa_packages/sound-tools/
    package.yaml
    skill/base.md
    features/whisper/build.sh
    features/whisper/whisper-cli.c
    features/whisper/skill/SKILL.md

pa_packages/3d-tools/
    package.yaml
    skill/base.md
    features/trimesh/skill/SKILL.md
    features/blender/skill/SKILL.md
    features/meshlab/skill/SKILL.md
    features/openscad/skill/SKILL.md

pa_packages/ocr-tools/
    package.yaml
    skill/base.md
    features/ocrmypdf/skill/SKILL.md
```

## 6. Skill content plan

All five skills follow the `code-intelligence` triage pattern: a decision table first,
recipes second, caveats last. Frontmatter `description` states the trigger conditions.

### 6.1 image-tools skill

- Frontmatter: use for image conversion, resizing, cropping, optimization, metadata
  extraction, SVG rasterization, or bitmap vectorization.
- Triage table: convert/resize/batch → `magick`; SVG→PNG/PDF → `rsvg-convert`;
  raster→SVG → `potrace` (with `mkbitmap` preprocessing); metadata read/write →
  `exiftool` or `exiv2`; lossless JPEG ops → `jpegtran`; WebP → `cwebp/dwebp`; PNG
  optimization → `optipng` then `pngquant`; PNG integrity → `pngcheck`; TIFF inspection →
  `tiffinfo`.
- Caveats: Fedora IM policy blocks PS/EPS/PDF (route PDFs to `pdftoppm` from
  `document-tools`); prefer `magick` over legacy verbs.

### 6.2 video-tools skill

- Triage: codec/container questions → `ffprobe` first; transcode → `ffmpeg`; remux without
  re-encode → `mkvmerge` or `ffmpeg -c copy`; per-track extraction → `mkvextract`;
  metadata report → `mediainfo`.
- **Fedora `ffmpeg-free` codec guidance table:**
    - H.264 encode → `-c:v libopenh264 -b:v 4M` (`libx264` is not in Fedora `ffmpeg-free`)
    - High-efficiency encode (use instead of `libx265`) → `-c:v libsvtav1 -crf 30 -preset 6`
      (AV1) or `-c:v libvpx-vp9 -crf 30 -b:v 0` (VP9)
    - HEVC / H.264 / AV1 / VVC decode → fully supported natively
    - AAC encode → `-c:a libfdk_aac` (via `fdk-aac-free`) or `-c:a aac`
    - Opus / MP3 / Vorbis → `-c:a libopus`, `-c:a libmp3lame`, `-c:a libvorbis`
    - Stream copy (`-c copy`) → always available for any codec including HEVC.
- Caveats: `ffplay` is not installed; use frame capture (`-frames:v 1`) or `virtual-desktop`.

### 6.3 sound-tools skill (and `whisper` feature fragment)

- **Base skill triage:** inspect → `soxi`; effects/trims/joins/resampling → `sox`;
  spectrogram PNG generation → `sox in.wav -n spectrogram -o spec.png`; AAC/M4A decode →
  `faad -o out.wav in.m4a` (or pipe `faad -q -w in.m4a | sox - ...`); FLAC tag/edit →
  `metaflac`; encode lossy → `opusenc` / `oggenc` / `lame` / `twolame`; cue/split →
  `shnsplit`; loudness → `normalize-audio` and `vorbisgain`/`mp3gain`; speech-to-text →
  `whisper` feature (`whisper-cli`).
- **`whisper` feature fragment (`features/whisper/skill/SKILL.md`):**
    - Explains that `/usr/local/bin/whisper-cli` is dynamically linked against Fedora's
      `libwhisper.so.1` (`whisper-cpp`) and `libsndfile.so.1`, using the default offline
      model at `/usr/local/share/whisper/ggml-base-q5_1.bin`.
    - **Direct transcription (WAV/FLAC/OGG):**
      `sox input.wav -r 16000 -c 1 -b 16 /tmp/in16k.wav && whisper-cli -l auto /tmp/in16k.wav`
    - **MP3 / M4A transcription pipeline:**
        - MP3: `sox input.mp3 -r 16000 -c 1 -b 16 /tmp/in16k.wav && whisper-cli /tmp/in16k.wav`
        - M4A/AAC: `faad -q -w input.m4a | sox - -r 16000 -c 1 -b 16 /tmp/in16k.wav && whisper-cli /tmp/in16k.wav`
    - **Output formats:** `-nt` (plain text without timestamps), `-osrt` (SRT subtitles),
      `-ovtt` (WebVTT), `-oj` (JSON with timestamps), `-l fi` / `-l en` / `-l auto`
      (language code), `-t <threads>`.

### 6.4 3d-tools skill

- Triage table: quick format convert → `assimp export`; STL check/repair → `admesh`
  or trimesh `fill_holes`; mesh decimate/cleaning → `QT_QPA_PLATFORM=offscreen meshlab`
  or trimesh; compress → `draco_encoder`; VDB inspect → `vdb_print`; procedural solid
  modeling → `openscad`; booleans/UV/rendering → `blender -b --python`.
- Caveats: always prefix `meshlab` with `QT_QPA_PLATFORM=offscreen`; `openscad` headless
  exports 3D/2D geometry (`STL`, `3MF`, `DXF`, `SVG`) without X11, while `.png` preview
  requires `virtual-desktop`.

### 6.5 ocr-tools skill

- Triage table: screenshot/photo → `tesseract in.png stdout`; scanned PDF → `ocrmypdf`
  feature or `pdftoppm -r 300 | tesseract`; digital PDF with text → `pdftotext`
  (`document-tools`); complex layout → `docling` (`document-tools`); orientation/script →
  `tesseract --psm 0`.
- Caveats: Fedora langpacks ship `tessdata_fast` LSTM models (`--oem 1` / `--oem 3`); do
  not pass `--oem 0`.

## 7. Cross-cutting integration changes

1. `docs/configuration.md`: add `- image-tools`, `- video-tools`, `- sound-tools`,
   `- 3d-tools`, `- ocr-tools` under Domain capabilities and document their features and
   defaults.
2. `CHANGELOG.md`: add under **Unreleased → Added**, noting the dynamically linked Fedora
   packages and the build-time staged `ggml-base-q5_1.bin` model in `sound-tools`/`whisper`.
3. No changes to `pa_core/`, `.pa-container/dependencies/root/commands.sh`, or
   `zensical.toml`.

## 8. Size budget (rough, excluding shared deps and union dedup)

| Package / feature | Installed size |
|---|---|
| `image-tools` core | ≈ 110–155 MB (includes Perl runtime for ExifTool + `librsvg2-tools`) |
| `image-tools` + `vips`/`jxl-heif`/`gmic` | +≈ 40 / 6 / 30 MB |
| `video-tools` core | ≈ 130 MB (`ffmpeg-free` + shared `libav*-free` closure + `mediainfo` + `mkvtoolnix`) |
| `sound-tools` core | ≈ 40–55 MB (includes `sox`, `faad2`, and codec tools) |
| `sound-tools` `whisper` | +≈ 95 MB (`whisper-cpp` + `openblas` ~35 MB + `ggml-base-q5_1.bin` ~60 MB + 25 KB `whisper-cli`) |
| `3d-tools` core | ≈ 25–40 MB |
| `3d-tools` `trimesh` | +≈ 140 MB (`trimesh` + `numpy`, `scipy`, `networkx`, `lxml`, shares `openblas`) |
| `3d-tools` `blender` | +≈ 400 MB (shares `libav*-free` and `openblas` when `video-tools`/`whisper` are enabled) |
| `3d-tools` `meshlab` | +≈ 300 MB (Qt6 stack) |
| `3d-tools` `openscad` | +≈ 150 MB |
| `ocr-tools` core | ≈ 20–25 MB |
| `ocr-tools` + `ocrmypdf` | +≈ 50–60 MB (`libgs` plus the Python PDF stack) |
| `ocr-tools` language features | +≈ 0.4–8 MB per language; ≈ 64 MB for all 25 |

## 9. OCR: a separate `ocr-tools` package

Keeping `ocr-tools` separate from `image-tools` and `document-tools` isolates dependencies
so OCR-only workspaces avoid staging Pandoc/Poppler while keeping all 25 `lang-*` features
modular (same language table as in section 4.5).

## 10. Rollout order

1. `image-tools` — pure distro payload, high immediate utility.
2. `video-tools` — pure distro payload (`ffmpeg-free`, `mediainfo`, `mkvtoolnix`); smoke-test
   `libopenh264`, `libsvtav1`, and `libfdk_aac` encoding in the container.
3. `sound-tools` — core audio tools (`sox`, `faad2`, codecs) plus the `whisper` feature
   (`features/whisper/build.sh` + `whisper-cli.c` linked dynamically against
   `whisper-cpp-devel` and `libsndfile-devel`).
4. `3d-tools` — core plus `trimesh`, then headless `blender`, `meshlab`, and `openscad`.
5. `ocr-tools` — `tesseract` core, `ocrmypdf`, and the 25 `lang-*` features.
