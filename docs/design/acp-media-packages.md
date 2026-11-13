# Plan: Media Agent Capability Packages (image-tools, video-tools, sound-tools, 3d-tools, ocr-tools)

Status: **Proposed — not yet implemented.** This document specifies five new ACPs for media
processing. All Fedora package names, versions, shipped binaries, and codec links below were
verified against the Fedora 45 release repository (`fedora-minimal:45` is the agent base
image). The staged ffmpeg build was verified by downloading the aarch64 autobuild tarball,
checking its SHA-256 against the release digest, and running `ffmpeg`/`ffprobe` in this
environment.

## 1. Summary

Add five opt-in Agent Capability Packages under `pa_packages/`:

| Package | Category | Core payload | Features |
|---|---|---|---|
| `image-tools` | `media` | ImageMagick, ExifTool, exiv2, webp/jpeg/tiff/png utilities, optipng, pngquant, pngcheck, potrace | `vips`, `jxl-heif`, `gmic` |
| `video-tools` | `media` | Full ffmpeg 9.0 (staged release build: x264/x265/AV1 encoders), mediainfo, mkvtoolnix | — (none) |
| `sound-tools` | `media` | SoX, flac, opus-tools, vorbis-tools, lame, twolame, shntool, normalize, vorbisgain, mp3gain, espeak-ng | — (none) |
| `3d-tools` | `media` | assimp, admesh, draco, openvdb | `trimesh` (default on), `blender`, `meshlab`, `openscad` |
| `ocr-tools` | `media` | tesseract with English and orientation data | `ocrmypdf`, 25 `lang-*` language features |

Payloads are Fedora distro packages — installed into the target image via
`collect_distro_packages` — with one deliberate exception: `video-tools` stages the
full-featured ffmpeg from a pinned FFmpeg-Builds autobuild release (`binary_download`,
per-arch URLs, SHA-256-pinned), because Fedora ships only `ffmpeg-free` (no
x264/x265/HEVC encode). The `node` ACP set the staged-binary precedent. No build scripts,
no MCP servers, no runtime egress. The only runtime privilege change is `none`.

## 2. Design principles

1. **Five focused packages, not one `media-tools`.** Workspaces enable only what they
   need. Media payloads differ in size by an order of magnitude (sound-tools ≈ 60 MB vs
   the `blender` feature ≈ +400 MB). Skills stay focused per domain, following the
   `code-intelligence` triage-skill pattern.
2. **Distro-first payloads, one staged-binary exception.** Fedora 45 ships every tool.
   Distro packages receive CVE and version updates automatically, and
   `collect_distro_packages` deduplicates installs across packages. Trade-off: versions
   float with the Fedora release. No SHA-256 pinning is needed.
   Exception: `video-tools` ffmpeg. Fedora ships only `ffmpeg-free` (no x264/x265/HEVC
   encode) and this plan does not add RPM Fusion, so the full build is staged from the
   FFmpeg-Builds autobuild as a `binary_download` payload — per-arch URL plus SHA-256 pin,
   the `node` ACP precedent. `virtual-desktop` and `code-intelligence` already combine a
   staged or build payload with a distro `packages:` list, so `video-tools` can stage ffmpeg
   and still take `mediainfo`/`mkvtoolnix` from Fedora in one payload.
3. **Lean core, heavy features.** Core payloads stay small. Heavy or specialized tools go
   behind features (`default: false`), following the `document-tools`/`docling` precedent.
   Exception: ffmpeg stays in `video-tools` core — it is the package's identity, not a
   specialized add-on.
4. **One ffmpeg, owned by `video-tools`.** `video-tools` core stages the full build.
   `sound-tools` declares no ffmpeg and no `ffmpeg` feature; its skill routes ffmpeg
   needs (AAC/M4A decode, spectrograms) to `video-tools`. One copy in the fleet, one
   update path.
5. **No hard GUI dependencies.** Blender, MeshLab, and OpenSCAD run headless first-class
   (`blender -b`, `meshlab -i/-o`, `openscad -o`). Unlike `browser`/`chromium` (where GUI use
   is the point), none of these features declare `runtime.dependencies: [virtual-desktop]`.
   Skills mention the virtual desktop as an optional companion for interactive use.
6. **No egress anywhere.** No package or feature declares `egress.allow_hosts` — `yt-dlp`
   is out of scope by decision, and no downloader payload ships. Everything works
   offline; verification runs with `--network=none`. The only network use is the
   build-time tarball fetch of the `binary_download` payload, checked against its
   SHA-256 pin.
7. **Skills are the payload that matters.** Agents already know the tools generically. The
   skills contribute environment-specific truth: Fedora codec policy, ImageMagick security
   policy limits, headless recipes, and format triage tables.
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
| `perl-Image-ExifTool` | 13.50 | `exiftool` | ~21 MB |
| `exiv2` | 0.28.9 | `exiv2` | ~12.5 MB |
| `libwebp-tools` | 1.6.0 | `cwebp`, `dwebp`, `webpmux`, `webpinfo`, `anim_*` | ~0.5 MB |
| `libjpeg-turbo-utils` | 3.1.4.1 | `cjpeg`, `djpeg`, `jpegtran` | ~0.5 MB |
| `libtiff-tools` | 4.7.2 | `tiffinfo`, `tiffcp`, `tiffset`, … | ~1.4 MB |
| `optipng` | 7.9.1 | `optipng` | ~0.2 MB |
| `pngquant` | 2.18.0 | `pngquant` | ~0.1 MB |
| `pngcheck` | 4.0.1 | `pngcheck` | ~0.2 MB |
| `potrace` | 1.16 | `potrace`, `mkbitmap` | ~0.3 MB |
| `vips` (feature) | 8.18.3 | `vips` | ~3.7 MB |
| `libjxl-utils` (feature) | 0.11.2 | `cjxl`, `djxl`, `jxlinfo` | ~0.8 MB |
| `libheif-tools` (feature) | 1.23.5 | `heif-enc`, `heif-convert`, `heif-info` | ~0.7 MB |
| `gmic` (feature) | 4.0.3 | `gmic` | ~24 MB |

Notes:

- Fedora ImageMagick 7 ships both the `magick` entrypoint and legacy `convert`/`mogrify`
  names. The skill must teach `magick <subcommand>` as primary.
- Fedora's IM security policy (`/etc/ImageMagick/policy.xml`) blocks some formats
  (historically PS/EPS/PDF/XPS). Confirm the exact F45 policy during implementation. The
  skill routes PDF rasterization to `pdftoppm` from `document-tools`.
- `ImageMagick` also provides `import`, which the `virtual-desktop` x11 feature already
  installs for screenshots. The union deduplicates the overlap when both are enabled.

### 3.2 video-tools

| Component | Version | Ships | Installed |
|---|---|---|---|
| `ffmpeg` (staged binary_download) | n9.0.2-57 (autobuild 2026-11-12) | `ffmpeg`, `ffprobe` (static) | ≈ 252 MB (≈ 126 MB each) |
| `mediainfo` (distro) | 26.05 | `mediainfo` (CLI; GUIs are separate `mediainfo-qt`/`mediainfo-gui`) | ~0.2 MB |
| `mkvtoolnix` (distro) | 102.0 | `mkvmerge`, `mkvextract`, `mkvinfo`, `mkvpropedit` | ~32 MB |

Notes:

- **Fedora ships `ffmpeg-free` only** — its `libavcodec-free` 9.0.2 carries
  `libopenh264`, `fdk-aac` (via `fdk-aac-free`), `libmp3lame`, `libvpx`, `libaom`,
  `librav1e`, `libdav1d`, `libtheora`, `libvorbis`, `libopus`, `libtwolame`,
  `libxvidcore`, `libwebp` — but no x264/x265/HEVC at all. This plan does not add
  RPM Fusion, so `video-tools` stages the full-featured GPL build from the
  FFmpeg-Builds project instead (`binary_download`, section 4.2).
- The pinned build is `ffmpeg-n9.0.2-57-gd838f9f9ae` from the immutable
  `autobuild-2026-11-12-15-40` release tag. Verified in this environment: the aarch64
  tarball matches its published SHA-256, and `ffmpeg`/`ffprobe` run on the glibc agent
  image and print `n9.0.2-57-gd838f9f9ae-20261112`.
- Encoders verified present: `libx264`, `libx265`, `libsvtav1`, `libaom-av1`,
  `librav1e`, `libvpx-vp9`, `libopenh264`, `libtheora`, `libvorbis`, `libopus`,
  `libmp3lame`, `libtwolame`, native `aac`, `libwebp`, and `libvvenc` (H.266 VVC).
  H.264 and HEVC encode now work. `libfdk_aac` is **absent** (`--disable-libfdk-aac`
  in the GPL build; no nonfree variant is published) — the skill teaches native `aac`.
- `ffplay` is deliberately **not staged** (≈ 127 MB): the container has no audio device
  and ffplay is an interactive player. Frame capture replaces it; the virtual desktop
  covers interactive viewing. The `extract_map` maps `ffmpeg` and `ffprobe` only.
- Tarball layout: `ffmpeg-n9.0.2-57-gd838f9f9ae-<arch>-gpl-9.0/bin/{ffmpeg,ffplay,ffprobe}`
  plus `LICENSE.txt` (GPL-3.0), `doc/`, `man/`, `presets/`. Compressed size is
  ≈ 122 MB (aarch64) / ≈ 145 MB (x86_64); ≈ 252 MB staged on disk for the two mapped
  binaries. That replaces the ≈ 100 MB `ffmpeg-free` closure — full codec coverage
  costs roughly 2.5× the distro build.
- Pinning: the `latest` release tag is a moving target (assets are rebuilt on upstream
  changes); the `autobuild-2026-11-12-15-40` tag is frozen. Pin the frozen tag. Updates
  re-pin URL and SHA-256 through a PR, mirroring how `node` tracks upstream releases.
- `yt-dlp` is out of scope: no downloader payload and no egress allowlist anywhere in
  these packages. Download tools stay a per-workspace decision outside this plan.

### 3.3 sound-tools

| Fedora package | Version | Ships | Installed |
|---|---|---|---|
| `sox` | 14.4.2.0 | `sox`, `soxi`, `rec`/`play` | ~2 MB (+ codec libs) |
| `flac` | 1.5.0 | `flac`, `metaflac` | ~0.4 MB |
| `opus-tools` | 0.2 | `opusenc`, `opusdec`, `opusinfo` | ~0.2 MB |
| `vorbis-tools` | 1.4.3 | `oggenc`, `oggdec`, `ogginfo`, `ogg123` | ~1.7 MB |
| `lame` | 4.0 | `lame` | ~0.6 MB |
| `twolame` | 0.4.0 | `twolame` | ~0.2 MB |
| `shntool` | 3.0.10 | `shnsplit`, `shninfo`, `shnlen`, … | ~0.4 MB |
| `normalize` | 0.7.7 | `normalize-audio` | ~0.2 MB |
| `vorbisgain` | 0.37 | `vorbisgain` | ~0.1 MB |
| `mp3gain` | 1.6.2 | `mp3gain` | ~0.1 MB |
| `espeak-ng` | 1.52.0 | `espeak-ng` (TTS; ~24 MB is voice data) | ~25 MB |

Notes:

- `sox` covers WAV/MP3/FLAC/Ogg/Opus pipelines. It cannot read AAC/M4A or draw
  spectrograms — those routes go to the full ffmpeg in `video-tools` core (principle 4).
  The `sound-tools` skill cross-references it.
- No `ffmpeg` feature exists in this package: sound-only workspaces that need
  AAC/M4A decode enable `video-tools`. One ffmpeg in the fleet, one update path.
- `espeak-ng` is the only speech synthesis tool in Fedora without heavy deps. Keep it in
  core (decision point); alternatives like Piper are not packaged.

### 3.4 3d-tools

| Fedora package | Version | Ships | Installed |
|---|---|---|---|
| `assimp` | 6.0.5 | `assimp` CLI (`version`, `info`, `export`, `extract`, `cmpdiff`) + libs | ~6.8 MB |
| `admesh` | 0.98.5 | `admesh` (STL check/repair/fill) | ~0.1 MB |
| `draco` | 1.5.7 | `draco_encoder`, `draco_decoder` | ~1.7 MB |
| `openvdb` | 13.1.0 | `vdb_print` (grid inspection; this build ships no `vdb_render`) | ~3.2 MB |
| `python3-trimesh` (feature) | 5.1.0 | trimesh Python module (verified: requires only `python3-numpy >= 1.21` and `python(abi) = 3.15` — matches the core `python` ACP exactly) | ~5.3 MB (+ numpy) |
| `blender` (feature) | 5.2.2 | `blender` (headless `-b` first-class; `blender-thumbnailer`) | ~229 MB (+ ~200 MB deps) |
| `meshlab` (feature) | 2025.07 | `meshlab` (2023.12+ merged `meshlabserver` into the main binary; CLI via `-i/-o` filters) | ~29 MB (+ Qt6 stack) |
| `openscad` (feature) | 2021.01 | `openscad` headless render (`-o out.stl`) | ~7.7 MB (+ Qt/OpenGL deps) |

Notes:

- Fedora's `python3-trimesh` binds to **system Python 3.15**, which the core `python`
  ACP already installs (`payload: distro_package [python3, …]`). So the `trimesh` feature
  needs no `uv pip` staging and no build script — unlike `docling`, it is a plain distro
  package. `pygltflib` is not needed: trimesh reads/writes GLB/GLTF natively.
- OpenSCAD in F45 is the dated 2021.01 release. It renders headless fine; note the age in
  the skill.
- Deferred candidates (not in v1): `f3d` (3D viewer, GUI-oriented, pairs with
  `virtual-desktop`), `prusa-slicer` (CLI slicing, +~127 MB + wx deps), COLMAP (not in F45),
  `openvdb` `vdb_render` (not shipped).

### 3.5 ocr-tools

| Fedora package | Version | Ships | Installed |
|---|---|---|---|
| `tesseract` | 5.5.3 | `tesseract` CLI; ships no language data itself | ~0.1 MB |
| `tesseract-libs` | 5.5.3 | libtesseract (pulled as dep) | ~3.0 MB |
| `leptonica` | 1.87.0 | libleptonica raster I/O for tesseract (pulled as dep) | ~3.2 MB |
| `tesseract-common` | 5.5.3 | owns `/usr/share/tesseract/tessdata/` and engine configs (pulled as dep) | ~0.02 MB |
| `tesseract-langpack-eng` | 4.1.0 | `eng.traineddata` | ~4.0 MB |
| `tesseract-osd` | 4.1.0 | `osd.traineddata` — orientation and script detection | ~10.3 MB |
| `ocrmypdf` (feature) | 16.13.0 | `ocrmypdf` (noarch); requires `tesseract >= 4.1.1`, `ghostscript >= 9.15`, pikepdf, img2pdf, pdfminer-six | ~1.3 MB + ~45 MB deps (`libgs` ~24.6 MB dominates) |

Notes:

- 123 `tesseract-langpack-*` packages exist (0.4–8 MB each), plus `tesseract-script-*`
  packs and vertical-text variants (`jpn_vert`, `chi_sim_vert`, `chi_tra_vert`,
  `kor_vert`). Section 9.1 lists the curated 25 that become features.
- Excluded: `gocr` 0.52 and `ocrad` 0.29 (inferior engines, redundant),
  `python3-pytesseract` 0.3.13 (the CLI is enough for agents), `tesseract-tools`
  (model training utilities), `ocrmypdf+watcher` (directory watcher).
- `ocrmypdf` needs no Poppler: ghostscript rasterizes the pages and pikepdf writes the
  text layer. It works without `document-tools` enabled.
- The `document-tools` `docling` feature remains the neural tier; the extraction ladder
  spans packages (section 9).

## 4. Package manifests (implementation-ready skeletons)

YAML indentation follows the existing 4-space manifest style. Verification commands run
with `--network=none` via `/bin/sh -c`, stderr merged into stdout, exit code 0 required.
The `video-tools` `binary_download` payload downloads and SHA-256-checks its tarball at
build time only (the `node` ACP precedent); the runtime stays offline.

### 4.1 `pa_packages/image-tools/package.yaml`

```yaml
schema_version: "0.7.0"
name: "image-tools"
version: "1.0.0"
description: "Image processing capability: ImageMagick conversion and effects, ExifTool/exiv2 metadata, WebP/JPEG/TIFF/PNG codec utilities, optimizers, and potrace vectorization"
category: "media"
license: "GPL-2.0-or-later"

payload:
    type: distro_package
    packages:
        - "ImageMagick"
        - "perl-Image-ExifTool"
        - "exiv2"
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
        description: "Modern still-image codecs: JPEG XL (cjxl/djxl) and HEIF/AVIF encode and decode (heif-enc/heif-convert)"
        default: false
        payload:
            type: distro_package
            packages:
                - "libjxl-utils"
                - "libheif-tools"
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
    command: "magick -version && exiftool -ver && cwebp -version && optipng -v"
    expected_output_contains: "ImageMagick"
```

### 4.2 `pa_packages/video-tools/package.yaml`

```yaml
schema_version: "0.7.0"
name: "video-tools"
version: "9.0.2"
description: "Video processing capability: full-featured ffmpeg (staged release build with x264/x265/AV1 encoders), MediaInfo metadata, and MKVToolNix muxing and track extraction"
category: "media"
license: "GPL-3.0-or-later"

payload:
    type: binary_download
    packages:
        - "mediainfo"
        - "mkvtoolnix"
    platforms:
        x86_64:
            url: "https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-11-12-15-40/ffmpeg-n9.0.2-57-gd838f9f9ae-linux64-gpl-9.0.tar.xz"
            sha256: "ccedeabdb6c1bbfd44647225e3a4452a1983a770847c2d7de261fcbc407250df"
            extract_map:
                "ffmpeg-n9.0.2-57-gd838f9f9ae-linux64-gpl-9.0/bin/ffmpeg": "/usr/local/bin/ffmpeg"
                "ffmpeg-n9.0.2-57-gd838f9f9ae-linux64-gpl-9.0/bin/ffprobe": "/usr/local/bin/ffprobe"
        aarch64:
            url: "https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-11-12-15-40/ffmpeg-n9.0.2-57-gd838f9f9ae-linuxarm64-gpl-9.0.tar.xz"
            sha256: "2348acf1c6fec860612bf799ab1b91a0f5e8ab3d8a95b28511c7ef8cd72bf1cd"
            extract_map:
                "ffmpeg-n9.0.2-57-gd838f9f9ae-linuxarm64-gpl-9.0/bin/ffmpeg": "/usr/local/bin/ffmpeg"
                "ffmpeg-n9.0.2-57-gd838f9f9ae-linuxarm64-gpl-9.0/bin/ffprobe": "/usr/local/bin/ffprobe"

skill:
    enabled: true
    source: "skill/base.md"
    target_agents: ["all"]

verification:
    command: "ffmpeg -version | head -1 && ffprobe -version | head -1 && mediainfo --Version | head -1 && mkvmerge --version"
    expected_output_contains: "ffmpeg"
```

Notes on this skeleton:

- `version:` tracks the staged ffmpeg build (`n9.0.2-57` → `9.0.2`), the `node` ACP
  precedent — every re-pin is visible in one field.
- `payload.packages` rides along with any payload type: `collect_distro_packages`
  merges the list into the final-stage `microdnf` install regardless of `type`.
  `virtual-desktop` (5 packages) and `code-intelligence` (3 packages) already combine a
  non-distro core payload with a distro `packages:` list. Verified against this skeleton:
  `collect_distro_packages([("video-tools", [])])` yields `mediainfo, mkvtoolnix`.
- The aarch64 pin was verified end-to-end in this environment: the URL downloads, the
  SHA-256 matches, the tarball layout matches the `extract_map`, and both binaries run.
  The x86_64 SHA-256 is the GitHub release digest, and its `extract_map` follows the same
  archive-name convention (top directory equals the asset name minus `.tar.xz`) — confirm
  both in the implementation smoke test on x86_64.
- No `build.sh` is needed: `binary_download` is declarative (unlike `document-tools`,
  which stages Pandoc through a build script).
- No features and no egress blocks ship in this package.

### 4.3 `pa_packages/sound-tools/package.yaml`

```yaml
schema_version: "0.7.0"
name: "sound-tools"
version: "1.0.0"
description: "Audio processing capability: SoX effects and analysis, FLAC/Ogg/Opus codecs, LAME/twolame MP3, shntool splitting, gain normalization, and espeak-ng speech synthesis"
category: "media"
license: "GPL-2.0-or-later"

payload:
    type: distro_package
    packages:
        - "sox"
        - "flac"
        - "opus-tools"
        - "vorbis-tools"
        - "lame"
        - "twolame"
        - "shntool"
        - "normalize"
        - "vorbisgain"
        - "mp3gain"
        - "espeak-ng"

skill:
    enabled: true
    source: "skill/base.md"
    target_agents: ["all"]

verification:
    command: "sox --version && flac --version | head -1 && opusenc --version && espeak-ng --version"
    expected_output_contains: "sox"
```

No `ffmpeg` feature: ffmpeg belongs to `video-tools` core (principle 4), and a second
staged copy would duplicate ≈ 252 MB. The skill cross-references `video-tools` for
AAC/M4A decode and spectrograms.

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
        description: "trimesh Python mesh toolkit for load/convert/repair/analyze workflows (STL, OBJ, PLY, GLB/TF, 3MF) on the container Python"
        default: true
        payload:
            type: distro_package
            packages:
                - "python3-trimesh"
        skill_fragment: "features/trimesh/skill/SKILL.md"
        verification:
            command: "python3 -c 'import trimesh, numpy; print(trimesh.__version__)'"
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
            command: "blender -v | head -1"
            expected_output_contains: "Blender"
    meshlab:
        description: "MeshLab mesh processing, cleaning, and format conversion CLI ('meshlab -i in -o out' filter chains)"
        default: false
        payload:
            type: distro_package
            packages:
                - "meshlab"
        skill_fragment: "features/meshlab/skill/SKILL.md"
        verification:
            command: "meshlab --help 2>&1 | head -2"
            expected_output_contains: "meshlab"
    openscad:
        description: "OpenSCAD parametric solid modeling with headless STL/PNG rendering (2021.01 release)"
        default: false
        payload:
            type: distro_package
            packages:
                - "openscad"
        skill_fragment: "features/openscad/skill/SKILL.md"
        verification:
            command: "openscad -v 2>&1 | head -1"
            expected_output_contains: "OpenSCAD"

verification:
    command: "assimp version && admesh --version && draco_encoder 2>&1 | head -1 && vdb_print 2>&1 | head -1"
    expected_output_contains: "assimp"
```

Caveats to resolve at implementation time (the flag behavior of `admesh`, `draco_encoder`,
`vdb_print`, `meshlab --help`, and `blender -v` must be smoke-tested; use whichever
invocation prints a stable banner with exit code 0 — verification merges stderr, so
`2>&1` forms are acceptable).

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
            command: "test -f /usr/share/tesseract/tessdata/ara.traineddata"
    lang-ces:
        description: "Czech OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-ces"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/ces.traineddata"
    lang-chi-sim:
        description: "Chinese (Simplified) OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-chi_sim"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/chi_sim.traineddata"
    lang-chi-tra:
        description: "Chinese (Traditional) OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-chi_tra"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/chi_tra.traineddata"
    lang-dan:
        description: "Danish OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-dan"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/dan.traineddata"
    lang-deu:
        description: "German OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-deu"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/deu.traineddata"
    lang-ell:
        description: "Greek OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-ell"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/ell.traineddata"
    lang-fin:
        description: "Finnish OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-fin"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/fin.traineddata"
    lang-fra:
        description: "French OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-fra"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/fra.traineddata"
    lang-heb:
        description: "Hebrew OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-heb"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/heb.traineddata"
    lang-hin:
        description: "Hindi OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-hin"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/hin.traineddata"
    lang-hun:
        description: "Hungarian OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-hun"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/hun.traineddata"
    lang-ita:
        description: "Italian OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-ita"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/ita.traineddata"
    lang-jpn:
        description: "Japanese OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-jpn"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/jpn.traineddata"
    lang-kor:
        description: "Korean OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-kor"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/kor.traineddata"
    lang-nld:
        description: "Dutch OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-nld"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/nld.traineddata"
    lang-nor:
        description: "Norwegian OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-nor"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/nor.traineddata"
    lang-pol:
        description: "Polish OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-pol"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/pol.traineddata"
    lang-por:
        description: "Portuguese OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-por"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/por.traineddata"
    lang-rus:
        description: "Russian OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-rus"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/rus.traineddata"
    lang-spa:
        description: "Spanish OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-spa"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/spa.traineddata"
    lang-swe:
        description: "Swedish OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-swe"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/swe.traineddata"
    lang-tur:
        description: "Turkish OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-tur"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/tur.traineddata"
    lang-ukr:
        description: "Ukrainian OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-ukr"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/ukr.traineddata"
    lang-vie:
        description: "Vietnamese OCR language data"
        default: false
        payload:
            type: distro_package
            packages:
                - "tesseract-langpack-vie"
        verification:
            command: "test -f /usr/share/tesseract/tessdata/vie.traineddata"

verification:
    command: "tesseract --version | head -2 && tesseract --list-langs"
    expected_output_contains: "eng"
```

Caveats to resolve at implementation time: `tesseract --list-langs` must exit 0 with
`eng` and `osd` installed (its output may go to stderr — verification merges stderr, but
confirm the exit code); `ocrmypdf --version` must exit 0 (it probes its plugin stack).

## 5. File trees

```
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

`assemble_package_skill` falls back to `features/<feature>/skill/SKILL.md` when
`skill_fragment` is declared, so no `build.sh` is needed anywhere in these packages —
`video-tools` stages ffmpeg declaratively through `binary_download`, with no
`document-tools`-style build script. The skill source is `skill/base.md` (the
browser/virtual-desktop pattern), not `SKILL.md`, because feature fragments get appended
to it. The 25 `ocr-tools` language features declare no `skill_fragment` —
`language-servers` already ships five fragment-free features — because the base skill
documents `-l <code>` for every language in one table.

## 6. Skill content plan

All five skills follow the `code-intelligence` triage pattern: a decision table first,
recipes second, caveats last. Frontmatter `description` must state the trigger conditions,
as other packages do.

### 6.1 image-tools skill

- Frontmatter: use for image conversion, resizing, cropping, optimization, metadata
  extraction, or vectorization.
- Triage table: convert/resize/batch → `magick`; metadata read/write → `exiftool` (first)
  or `exiv2` (fast, XMP/EXEV/IPTC); lossless JPEG ops → `jpegtran`; WebP → `cwebp/dwebp`;
  PNG optimization → `optipng` (lossless) then `pngquant` (palette/lossy, when size
  matters); PNG integrity → `pngcheck`; TIFF inspection → `tiffinfo`; raster→SVG →
  `potrace` (with `mkbitmap` preprocessing).
- Recipes: batch resize with `magick mogrify`, thumbnail strips, `-quality`/`-strip`
  guidance for web payloads, `optipng`+`pngquant` pipeline ordering.
- Caveats: Fedora IM policy may block PS/EPS/PDF (route PDFs to `pdftoppm` from
  `document-tools`); prefer `magick` over legacy verbs; `import` exists but belongs to the
  virtual-desktop screenshot flow.
- Cross-reference: OCR and text extraction from images route to the `ocr-tools`
  package (sections 4.5 and 9). Do not add OCR tools to this package.

### 6.2 video-tools skill

- Triage: codec/container questions → `ffprobe` first; transcode → `ffmpeg`; remux without
  re-encode → `mkvmerge` or `ffmpeg -c copy`; per-track extraction → `mkvextract`;
  metadata report → `mediainfo`.
- Codec guidance table (this is the highest-value content): H.264 → `-c:v libx264` (or
  `libopenh264`), HEVC → `-c:v libx265`, AV1 → `-c:v libsvtav1` (fast) / `libaom-av1` /
  `librav1e`, VVC → `-c:v libvvenc`, VP9 → `-c:v libvpx-vp9`, AAC → `-c:a aac`
  (native; `libfdk_aac` is not in the GPL build), MP3 → `libmp3lame`, Opus → `libopus`.
  State that `-c copy` and stream-copy remuxes are always available.
- Recipes: extract audio without re-encode, single-frame capture at timestamp, keyframe-only
  cuts (`-ss` before `-i`), two thumbnails strips, burn-less subtitle copy into MKV, and
  x264/x265 quality presets (`-crf` with `-preset`, 10-bit `-pix_fmt yuv420p10le`).
- Caveats: `ffplay` is not installed (no audio device; use frame capture or the virtual
  desktop); the staged build is pinned to the `n9.0.2-57` autobuild — if `ffmpeg -version`
  prints a different string, the pin drifted; the binaries are static, so ffmpeg's
  libraries are embedded and not linkable by other tools.
- Cross-reference: audio-only pipelines route to `sound-tools`; downloads are out of
  scope (per-workspace decision, not a payload here).

### 6.3 sound-tools skill

- Triage: inspect → `soxi` (`ffprobe` when `video-tools` is enabled); effects/trims/joins → `sox`; FLAC tag/edit →
  `metaflac`; encode lossy → `opusenc` (preferred) / `oggenc` / `lame` / `twolame`;
  cue/split → `shnsplit`; loudness → `normalize` (waveform) and `vorbisgain`/`mp3gain`
  (replay-gain style); speech → `espeak-ng`.
- Recipes: WAV→FLAC archive, MP3→Opus transcode, batch loudness normalize, splice by cue
  sheet, TTS to WAV then FLAC/Opus.
- Caveats: sox cannot read AAC/M4A — enable `video-tools` (its core ffmpeg covers them);
  recording is not possible (no audio devices) — generate files instead.

### 6.4 3d-tools skill

- Triage table: quick format convert → `assimp export`; STL check/repair → `admesh`
  (fast) or trimesh `fill_holes` (programmatic); mesh decimate/decoding → `meshlab`
  feature or trimesh; compress → `draco_encoder`; VDB inspect → `vdb_print`; procedural
  solid modeling → `openscad` feature; anything else (booleans, repair, UV/light bake,
  rendering) → `blender -b --python` feature.
- Recipes: `assimp export in.glb out.stl`, draco CLI compress/decompress flags, trimesh
  one-liners (load/repair/save, watertight check, bounds/volume), headless blender render
  (`blender -b scene.blend -o /tmp/frame_####.png -a`), openscad STL render
  (`openscad -o out.stl in.scad`).
- Caveats: OpenSCAD is 2021.01 in F45; `meshlabserver` no longer exists — the CLI moved
  into `meshlab` itself; no GPU in headless mode (CPU rendering only); prefer trimesh for
  GLB work over assimp for glTF extensions.

### 6.5 ocr-tools skill

- Frontmatter: use for extracting text from images, screenshots, photos of pages, and
  scanned PDFs; for adding searchable text layers to PDFs; and for language selection.
- Triage table: text from a screenshot or photo → `tesseract in.png stdout`; scanned
  PDF → `ocrmypdf` feature (one command, searchable output) or a
  `pdftoppm -r 300 | tesseract` loop; PDF with a text layer → `pdftotext` from
  `document-tools` first (test with `pdfinfo` or a `pdftotext` yield check); deep layout
  analysis (tables, reading order, equations) → `document-tools` `docling` feature;
  page orientation or script detection → `tesseract --psm 0` (uses the core `osd` data).
- Recipes: `-l deu+eng` multilingual reads; `--psm` mode selection (single column vs
  block vs sparse text); preprocessing with `magick` from `image-tools` (upscale to
  ~300 DPI, grayscale, deskew); hOCR and ALTO output for positioned text;
  `tesseract --list-langs` to enumerate installed data; `ocrmypdf --skip-text`,
  `--language deu`, `--optimize` levels.
- Caveats: only `eng` and `osd` ship in core; every other language needs its `lang-*`
  feature; ~300 DPI input matters — upscale before OCR; more languages arrive via a PR
  (a mechanical feature block) or per-workspace through
  `.pa-container/dependencies/root/commands.sh`.
- Cross-references: `image-tools` (preprocess with `magick`), `document-tools`
  (`pdftotext` for text layers, `docling` for deep layout, `pdftoppm` as page feed).

## 7. Cross-cutting integration changes

1. `docs/configuration.md`:
    - Add all five packages to the example `packages:` block under Domain capabilities:
      `- image-tools`, `- video-tools`, `- sound-tools`, `- 3d-tools`, `- ocr-tools`
      (with `features: []`, `config: {}`, `secrets: []` per the canonical spec example).
    - Extend the **Available packages → Domain Capabilities** list with one bullet per
      package, including their feature lists and defaults, mirroring the `browser` and
      `vector-storage` entries.
2. `CHANGELOG.md`: add under **Unreleased → Added** at implementation time, one entry per
   package (with the feature/default summary), noting image size impact. The `video-tools`
   entry must call out the staged GPL-3.0 build, its pinned autobuild version, and the
   re-pin policy (PR per update).
3. No changes to:
    - `pa_core/` (discovery, builder, projection, and smoke tests are generic and pick up
      new directories automatically; the `binary_download` channel needs no builder change
      either — `node` already exercises it — and `test_discover_packages` asserts `>= 20`,
      already satisfied).
    - `.pa-container/dependencies/root/commands.sh` — package payloads install through the
      ACP builder's `microdnf` channel, never through workspace root commands.
    - `zensical.toml` nav — `docs/design/` files are intentionally not in the nav.
4. Verification workflow per package:
    - `pa build --packages <name>` (then with features, e.g.
      `pa build --packages 3d-tools --features blender,trimesh` — subject to CLI flag
      support).
    - `pa test --packages <name>` for the in-container smoke contract, and with
      `--features` where the CLI supports feature-specific verification.
5. Pre-commit: `uv run pre-commit run --all-files` (format-markdown and pymarkdown scan
   will lint every new `SKILL.md` and this plan; follow the 4-space list indentation).

## 8. Size budget (rough, excluding shared deps and union dedup)

| Package / feature | Installed size |
|---|---|
| `image-tools` core | ≈ 100–150 MB |
| `image-tools` + `vips`/`jxl-heif`/`gmic` | +≈ 40 / 5 / 30 MB |
| `video-tools` core | ≈ 290 MB (≈ 252 MB staged ffmpeg + mediainfo/mkvtoolnix) |
| `sound-tools` core (incl. espeak-ng) | ≈ 60–80 MB |
| `3d-tools` core | ≈ 25–40 MB |
| `3d-tools` `trimesh` | +≈ 45 MB (numpy + trimesh) |
| `3d-tools` `blender` | +≈ 400 MB |
| `3d-tools` `meshlab` | +≈ 300 MB (Qt6 stack) |
| `3d-tools` `openscad` | +≈ 150 MB |
| `ocr-tools` core | ≈ 20–25 MB |
| `ocr-tools` + `ocrmypdf` | +≈ 50–60 MB (`libgs` plus the Python PDF stack) |
| `ocr-tools` language features | +≈ 0.4–8 MB per language; ≈ 64 MB for all 25 |

## 9. OCR: a separate `ocr-tools` package

OCR extracts text from pixels. The task, not the input format, sets the package boundary.
That rules out `image-tools`, which stays in the pixel domain: convert, optimize, inspect,
vectorize. Two homes remained, and this plan picks the second:

1. **An `ocr` feature of `document-tools` (rejected).** Task-wise it fits best:
   `pdftoppm` rasterizes, `pdftotext` reads text layers, `docling` adds the neural tier,
   and scanned PDFs are the one gap `pdftotext` cannot close. But it couples OCR to the
   staged Pandoc payload, and it gives language data no first-class place.
2. **A separate `ocr-tools` package (chosen).** Size isolation wins:
    - OCR-only workspaces (screenshots, photos of pages, signage) never stage Pandoc or
      Poppler.
    - Languages become first-class features — one `lang-*` feature per language, enabled
      in any combination, at 0.4–8 MB each.
    - `ocrmypdf` rasterizes with ghostscript and writes with pikepdf, so it depends on
      neither Poppler nor Pandoc. No payload coupling remains.
    - `document-tools` keeps its scope: digital-document conversion plus the `docling`
      neural tier.

The packages compose through skills, not payloads:

- Extraction ladder: text layer via `pdftotext` (`document-tools`) → raster text via
  `tesseract` or `ocrmypdf` (`ocr-tools`) → deep layout via `docling` (`document-tools`).
  The `ocr-tools` skill teaches the ladder and links the neighbors.
- Preprocessing routes to `magick` (`image-tools`): upscale to ~300 DPI, grayscale,
  deskew. Per-page loops rasterize with `pdftoppm` (`document-tools`) when it is enabled.

### 9.1 Language features

`eng` and `osd` ship in core: English is the baseline every workspace expects, and
orientation data is required for `--psm 0` and auto-rotation. Every further language is
one `default: false` feature that installs one `tesseract-langpack-<code>` package.
Verification is a file-presence test on the installed traineddata — the same pattern the
`browser` package uses for its libraries. The curated v1 set (25 features, alphabetical):

| Feature | Language | `--l` code | Installed |
|---|---|---|---|
| `lang-ara` | Arabic | `ara` | ~1.4 MB |
| `lang-ces` | Czech | `ces` | ~3.7 MB |
| `lang-chi-sim` | Chinese, Simplified | `chi_sim` | ~2.4 MB |
| `lang-chi-tra` | Chinese, Traditional | `chi_tra` | ~2.3 MB |
| `lang-dan` | Danish | `dan` | ~2.5 MB |
| `lang-deu` | German | `deu` | ~1.5 MB |
| `lang-ell` | Greek | `ell` | ~1.4 MB |
| `lang-fin` | Finnish | `fin` | ~7.7 MB |
| `lang-fra` | French | `fra` | ~1.1 MB |
| `lang-heb` | Hebrew | `heb` | ~0.9 MB |
| `lang-hin` | Hindi | `hin` | ~1.1 MB |
| `lang-hun` | Hungarian | `hun` | ~5.2 MB |
| `lang-ita` | Italian | `ita` | ~2.6 MB |
| `lang-jpn` | Japanese | `jpn` | ~2.4 MB |
| `lang-kor` | Korean | `kor` | ~1.6 MB |
| `lang-nld` | Dutch | `nld` | ~5.9 MB |
| `lang-nor` | Norwegian | `nor` | ~3.5 MB |
| `lang-pol` | Polish | `pol` | ~4.7 MB |
| `lang-por` | Portuguese | `por` | ~1.9 MB |
| `lang-rus` | Russian | `rus` | ~3.8 MB |
| `lang-spa` | Spanish | `spa` | ~2.2 MB |
| `lang-swe` | Swedish | `swe` | ~4.1 MB |
| `lang-tur` | Turkish | `tur` | ~4.4 MB |
| `lang-ukr` | Ukrainian | `ukr` | ~3.7 MB |
| `lang-vie` | Vietnamese | `vie` | ~0.5 MB |

Notes:

- All data ships in the tesseract-4 traineddata format; the 5.5 engine reads it fine.
  Fedora deliberately keeps the 4.1-format data for compatibility.
- Not in v1: vertical-text variants (`jpn_vert` ~3.0 MB, `chi_sim_vert` ~1.9 MB,
  `chi_tra_vert` ~1.8 MB, `kor_vert` ~1.1 MB), the `tesseract-script-*` packs, and the
  other ~95 langpacks. Any addition is a mechanical feature block.
- Per-workspace language additions without a PR: append
  `microdnf install -y tesseract-langpack-<code>` to
  `.pa-container/dependencies/root/commands.sh`.

### 9.2 Feature structure

- Only `ocrmypdf` carries a `skill_fragment`. The 25 language features declare none —
  `language-servers` already ships five fragment-free features — because the base skill
  documents `-l <code>` for every language in one table.
- Language verification uses `test -f /usr/share/tesseract/tessdata/<code>.traineddata`
  (the `tesseract-common` package owns that directory). No engine start, no output check.
- The `license:` field aggregates across features: `Apache-2.0` (tesseract, language
  data) plus `MPL-2.0` (ocrmypdf) plus `AGPL-3.0-or-later` (ghostscript `libgs`).

## 10. Rollout order

Implement in this order (each step is independently shippable and testable):

1. `image-tools` — no open decisions; largest agent value (docs, web, and ML pipelines).
2. `sound-tools` — no open decisions; it ships no `ffmpeg` feature (principle 4).
3. `video-tools` — re-verify both pinned autobuild SHA-256s at implementation time, confirm
   the x86_64 tarball layout, and smoke-test the `packages:` ride-along install
   (`mediainfo`/`mkvtoolnix`) alongside the staged binaries.
4. `3d-tools` — core plus `trimesh` first; `blender`/`meshlab`/`openscad` features last
   (size decisions).
5. `ocr-tools` — independent of the other packages; the skeleton is mechanical (one
   `ocrmypdf` feature plus 25 copy-paste language blocks). Ship any time; prefer after
   step 1 so the `image-tools` skill cross-reference has a target.

Each step: create the file tree (section 5), paste the manifest skeleton (section 4),
write the skill content (section 6), update `docs/configuration.md` and the CHANGELOG
entry (section 7), then run `pa build --packages <name>` and `pa test --packages <name>`.
For `ocr-tools`, also verify a language-feature subset explicitly, e.g.
`pa test --packages ocr-tools --features ocrmypdf,lang-deu,lang-jpn`.

## 11. Open questions

1. **Category.** This plan introduces a new `media` category for all five packages
   (existing categories: devtools, search, browser, desktop, …). Alternatively reuse
   `devtools`. Preference: `media`.
2. **ffmpeg build channel.** The pinned build is the FFmpeg-Builds `gpl` autobuild of the
   `n9.0` branch (`autobuild-2026-11-12-15-40`, ffmpeg `n9.0.2-57`). Alternatives: track
   the older `n8.1` branch instead (longer support runway), or pin the moving `latest`
   tag (always fresh, but re-pins itself silently — rejected here). The `gpl` variant is
   required for x264/x265; it excludes `libfdk_aac` (native `aac` instead). Confirm the
   channel and the re-pin cadence (PR per upstream point release).
3. **ffplay exclusion.** Dropping `ffplay` saves ≈ 127 MB and it is unusable headless
   (no audio device). Include it anyway for `virtual-desktop` playback? This plan
   excludes it.
4. **sound-tools AAC/M4A coverage.** With the `ffmpeg` feature gone, sound-only
   workspaces that need AAC/M4A decode or spectrograms must enable `video-tools`
   (+≈ 290 MB). Accept the coupling, or revisit a slimmer path later?
5. **espeak-ng in sound-tools core.** It is a synthesizer rather than a processor, but it
   is the only free packaged TTS and enables speech/audio-content tasks. Keep in core, or
   split into a `tts` feature?
6. **3d-tools GUI features.** `f3d` and `prusa-slicer` exist in F45. Defer both to a
   follow-up, or include now? This plan defers.
7. **License strings.** The `license:` field is documentation metadata. This plan proposes
   the most-restrictive aggregate per package (`video-tools` ships the staged build's
   GPL-3.0 `LICENSE.txt`; `3d-tools` is
   `MPL-2.0 AND Apache-2.0 AND MIT AND GPL-2.0-or-later`). Confirm the convention with
   `data-tools` (MIT) and `document-tools` (GPL-2.0-or-later) as precedent.
8. **Verification command details.** The `3d-tools` core chain uses tool banner flags
   (`admesh --version`, bare `draco_encoder`/`vdb_print` output). Final flags must be
   validated in a smoke container during implementation.
9. **`ocrmypdf` feature default.** Proposed `false`: it adds ~50–60 MB (ghostscript
   `libgs` plus the Python PDF stack), and the plain tesseract pipeline still serves
   scanned PDFs via `pdftoppm`. Flip to `true` if scanned-PDF workflows dominate.
10. **ocr-tools language set.** The 25 proposed features cost ~0.4–8 MB each when enabled.
    Trim or extend the set? Vertical-text variants are deferred to a follow-up.
