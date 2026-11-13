# ==============================================================================
# FILE: pa_packages/image-tools/skill/base.md
# ==============================================================================
---
name: image-tools
description: "Use when converting, resizing, cropping, compositing, or optimizing raster images (PNG, JPEG, WebP, TIFF), reading or stripping EXIF/XMP/IPTC metadata, rasterizing SVG files to PNG/PDF, or tracing bitmaps into SVG vectors."
---

# Image Processing (`image-tools`)

## Tool Triage

| Task | Tool | Primary Command |
|---|---|---|
| Convert, resize, crop, annotate, montage | ImageMagick 7 (`magick`) | `magick input.png -resize 800x600 output.webp` |
| Batch modify images in place or to a directory | ImageMagick 7 (`magick mogrify`) | `magick mogrify -path out/ -format webp -quality 82 *.jpg` |
| Render SVG to PNG / PDF (CSS & text accurate) | `rsvg-convert` (`librsvg2-tools`) | `rsvg-convert -w 1200 input.svg -o output.png` |
| Trace bitmap (PBM/PGM/BMP) to vector SVG | `potrace` + `mkbitmap` | `mkbitmap -s 2 -t 0.48 in.pbm -o - \| potrace -s -o out.svg` |
| Inspect or edit metadata (comprehensive) | `exiftool` | `exiftool -a -u -g1 image.jpg` |
| Fast C++ EXIF/IPTC/XMP inspection or stripping | `exiv2` | `exiv2 rm image.jpg` |
| Lossless JPEG rotation, crop, or optimization | `jpegtran` | `jpegtran -copy none -optimize -progressive in.jpg > out.jpg` |
| Encode / decode WebP directly | `cwebp` / `dwebp` | `cwebp -q 80 input.png -o output.webp` |
| Lossless PNG recompression | `optipng` | `optipng -o2 image.png` |
| Lossy 8-bit palette PNG quantization (~60-70% smaller) | `pngquant` | `pngquant --quality=65-85 --strip --ext .png --force image.png` |
| Verify PNG chunk integrity | `pngcheck` | `pngcheck -v image.png` |
| Inspect multi-page TIFF tags and layout | `tiffinfo` / `tiffcp` | `tiffinfo document.tif` |

## Common Recipes

### Resize and Strip Metadata for Web Delivery

```sh
magick input.jpg -auto-orient -strip -resize "1600x1600>" -quality 82 output.webp
```

### Two-Stage PNG Size Optimization

Run lossy palette quantization first (`pngquant`), then lossless deflate tuning (`optipng`):

```sh
pngquant --quality=70-85 --strip --output quantized.png input.png
optipng -o2 quantized.png
```

### High-DPI SVG to PNG and PDF Conversion

Always prefer `rsvg-convert` over `magick` for SVG inputs so embedded stylesheets and text elements render accurately:

```sh
rsvg-convert -d 300 -p 300 -w 2400 diagram.svg -o diagram.png
rsvg-convert -f pdf diagram.svg -o diagram.pdf
```

### Vectorize a Raster Logo to SVG

`potrace` accepts PBM/PGM/PPM/BMP inputs; convert PNG/JPEG via `magick` first:

```sh
magick logo.png -colorspace Gray -negate pnm:- | mkbitmap -s 2 -t 0.45 - -o - | potrace -s -o logo.svg
```

### Strip All Metadata from a Directory

```sh
exiftool -all= -overwrite_original dir/*.jpg dir/*.png
```

## Caveats and Cross-References

- **Use `magick`, not legacy verbs:** Fedora ships ImageMagick 7. Always invoke `magick input.png ... output.png` or `magick identify` / `magick mogrify` rather than bare `convert`.
- **Fedora ImageMagick security policy:** `/etc/ImageMagick/policy.xml` restricts PostScript and PDF delegates. To rasterize PDF pages to images, use `pdftoppm -png -r 300 input.pdf page` from the `document-tools` package.
- **OCR / text extraction:** Do not attempt OCR with `image-tools`. Route text extraction from screenshots, photos, and scanned documents to the `ocr-tools` package (`tesseract` / `ocrmypdf`), using `magick` only for preprocessing (upscaling, deskewing, grayscale).


# ==============================================================================
# FILE: pa_packages/image-tools/features/vips/skill/SKILL.md
# ==============================================================================
## Feature: `vips` (libvips Streaming Processing)

`vips` streams images through a demand-driven pipeline with minimal RAM, making it the preferred tool for very large images (gigapixel scans, satellite imagery, deep-zoom tile pyramids) where `magick` would exhaust container memory.

### Recipes

- **Fast thumbnail generation (shrink-on-load):**
    ```sh
    vips thumbnail huge.tif thumb.webp 800 --height 800
    ```
- **Generate DeepZoom (`dzsave`) tile pyramids:**
    ```sh
    vips dzsave huge.tif tiles_dir --suffix .webp[Q=80]
    ```
- **Inspect image header without decoding pixels:**
    ```sh
    vipsheader -a huge.tif
    ```


# ==============================================================================
# FILE: pa_packages/image-tools/features/jxl-heif/skill/SKILL.md
# ==============================================================================
## Feature: `jxl-heif` (JPEG XL and HEIF/AVIF Codecs)

Adds `cjxl`/`djxl`/`jxlinfo` (`libjxl-utils`), `heif-enc`/`heif-convert`/`heif-info` (`libheif-tools`), and the `ImageMagick-heic` delegate.

### Recipes

- **Encode / decode JPEG XL:**
    ```sh
    cjxl input.png output.jxl -d 1.0
    djxl output.jxl decoded.png
    ```
- **Lossless JPEG transcoding to JPEG XL (reversible back to exact original JPEG):**
    ```sh
    cjxl photo.jpg photo.jxl --lossless_jpeg=1
    ```
- **Convert Apple HEIC photos to JPEG or PNG:**
    ```sh
    heif-convert input.heic output.jpg
    magick input.heic -auto-orient output.webp
    ```


# ==============================================================================
# FILE: pa_packages/image-tools/features/gmic/skill/SKILL.md
# ==============================================================================
## Feature: `gmic` (G'MIC Image Processing Framework)

`gmic` provides a stack-based command-line pipeline with hundreds of mathematical, artistic, denoising, and morphological image filters.

### Recipes

- **Denoise and sharpen an image:**
    ```sh
    gmic input.png -denoise_patch 5,7 -sharpen 100 -o output.png
    ```
- **Evaluate pixel statistics or resize with Lanczos:**
    ```sh
    gmic input.png -resize 50%,50%,1,3,6 -o half.png
    ```


# ==============================================================================
# FILE: pa_packages/video-tools/skill/base.md
# ==============================================================================
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


# ==============================================================================
# FILE: pa_packages/sound-tools/skill/base.md
# ==============================================================================
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


# ==============================================================================
# FILE: pa_packages/sound-tools/features/whisper/skill/SKILL.md
# ==============================================================================
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


# ==============================================================================
# FILE: pa_packages/3d-tools/skill/base.md
# ==============================================================================
---
name: 3d-tools
description: "Use when inspecting, converting, repairing, compressing, or generating 3D meshes and volumetric grids (STL, OBJ, PLY, GLB/glTF, 3MF, FBX, OpenVDB) using assimp, admesh, draco, openvdb, and optional trimesh, Blender, MeshLab, or OpenSCAD."
---

# 3D Model Processing (`3d-tools`)

## Tool Triage

| Task | Tool | Primary Command |
|---|---|---|
| Inspect bounding box, vertex/face count, materials | `assimp info` | `assimp info model.glb` |
| Quick format conversion (FBX/DAE/OBJ/STL/PLY/GLB) | `assimp export` | `assimp export input.obj output.glb -f glb2` |
| Check and repair STL topology, normals, and holes | `admesh` | `admesh --fill-holes --normal-directions --normal-values in.stl -b out.stl` |
| Compress / decompress mesh to Google Draco (`.drc`) | `draco_encoder` / `draco_decoder` | `draco_encoder -i input.ply -o output.drc -cl 7` |
| Inspect OpenVDB volumetric grids (`.vdb`) | `vdb_print` | `vdb_print -l smoke.vdb` |
| Programmatic mesh analysis, 3MF/GLB I/O, hole repair | `trimesh` feature (default on) | `python3 -c "import trimesh; m = trimesh.load('in.3mf'); ..."` |
| Filter chains, mesh cleaning, remeshing | `meshlab` feature | `QT_QPA_PLATFORM=offscreen meshlab -i in.ply -o out.stl` |
| Parametric CAD modeling (`.scad` → `.stl`/`.3mf`/`.dxf`) | `openscad` feature | `openscad -o part.stl part.scad` |
| Complex booleans, UV unwrapping, animation, CPU Cycles rendering | `blender` feature | `blender -b scene.blend --python script.py` |

## Common Recipes

### Repair a Non-Manifold STL for 3D Printing with `admesh`

```sh
admesh --exact --nearby --remove-unconnected --fill-holes --normal-directions --normal-values broken.stl -b repaired.stl
```

### Compress a Mesh with Draco and Decode Back to PLY

```sh
draco_encoder -i model.obj -o model.drc -qp 14 -cl 7
draco_decoder -i model.drc -o decoded.ply
```

### Convert Between Common 3D Formats with `assimp`

Run `assimp listexport` to see supported export format IDs (`stl`, `stlb`, `obj`, `ply`, `plyb`, `glb2`, `gltf2`, `collada`):

```sh
assimp export input.fbx output.glb -f glb2
```

## Caveats

- **Prefer `trimesh` for 3MF and modern glTF/GLB:** When the `trimesh` feature is enabled (default), prefer it over `assimp` for `.3mf` and `.glb` manipulation.
- **No GPU acceleration in headless containers:** All geometry and rendering tools run on CPU.


# ==============================================================================
# FILE: pa_packages/3d-tools/features/trimesh/skill/SKILL.md
# ==============================================================================
## Feature: `trimesh` (Python 3D Mesh Toolkit)

`python3-trimesh` is installed on the container's system Python (`python3`) alongside `numpy`, `scipy`, `networkx`, and `lxml`, supporting STL, OBJ, PLY, GLB/glTF, 3MF, and DAE out of the box.

### Recipes

- **Inspect watertightness, volume, extents, and repair holes:**
    ```sh
    python3 - <<'PY'
    import trimesh

    mesh = trimesh.load("part.stl", force="mesh")
    print("Watertight:", mesh.is_watertight, "Extents:", mesh.extents)
    if not mesh.is_watertight:
        trimesh.repair.fix_normals(mesh)
        trimesh.repair.fill_holes(mesh)
    print("Volume:", mesh.volume)
    mesh.export("part_repaired.3mf")
    PY
    ```
- **Convert a multi-part scene (`.glb` / `.3mf`) into merged STL:**
    ```sh
    python3 -c "import trimesh; s = trimesh.load('model.glb'); s.to_geometry().export('merged.stl')"
    ```


# ==============================================================================
# FILE: pa_packages/3d-tools/features/blender/skill/SKILL.md
# ==============================================================================
## Feature: `blender` (Headless Blender 5.2 Scripting and Rendering)

Always invoke Blender with `-b` (`--background`) for headless execution. Use `--python-exit-code 1` so Python exceptions fail the shell command.

### Recipes

- **Render a `.blend` frame headless using Cycles CPU:**
    ```sh
    blender -b scene.blend -E CYCLES -o /tmp/render_#### -F PNG -f 1 -- --cycles-device CPU
    ```
- **Run a headless `bpy` geometry/conversion script:**
    ```sh
    blender -b --factory-startup --python-exit-code 1 --python - <<'PY'
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.gltf_import(filepath="input.glb")
    bpy.ops.wm.stl_export(filepath="output.stl")
    PY
    ```


# ==============================================================================
# FILE: pa_packages/3d-tools/features/meshlab/skill/SKILL.md
# ==============================================================================
## Feature: `meshlab` (Headless MeshLab CLI)

MeshLab 2023.12+ merged `meshlabserver` into the main `meshlab` binary. Because `meshlab` initializes Qt on startup, **always prefix invocations with `QT_QPA_PLATFORM=offscreen`** in headless containers.

### Recipes

- **Convert mesh formats and export vertex/face attributes:**
    ```sh
    QT_QPA_PLATFORM=offscreen meshlab -i input.ply -o output.stl
    ```


# ==============================================================================
# FILE: pa_packages/3d-tools/features/openscad/skill/SKILL.md
# ==============================================================================
## Feature: `openscad` (Parametric CAD Modeling)

Fedora 45 ships OpenSCAD 2021.01. Headless geometry exports (`STL`, `OFF`, `AMF`, `3MF`, `DXF`, `SVG`, `CSG`) run directly on CPU without a display server.

### Recipes

- **Compile `.scad` to binary STL with parameter overrides (`-D`):**
    ```sh
    openscad -o bracket.stl -D 'wall_thickness=3.2' -D '$fn=64' bracket.scad
    ```

### Caveat on `.png` Previews

Exporting `.png` images (`openscad -o preview.png part.scad`) requires an active X11/OpenGL display context (`virtual-desktop` package). Without a display, export to `.stl` first and render via `blender -b` or inspect geometry with `trimesh`.


# ==============================================================================
# FILE: pa_packages/ocr-tools/skill/base.md
# ==============================================================================
---
name: ocr-tools
description: "Use when extracting text from images, screenshots, photographs of documents, or scanned PDFs using Tesseract OCR, detecting page orientation/script, or layering searchable OCR text onto PDFs with ocrmypdf."
---

# Optical Character Recognition (`ocr-tools`)

## Extraction Ladder (Triage Across Packages)

Before running OCR on a PDF, always pick the lightest tool that matches the document structure:

| Input Type | Best Tool | Package / Feature | Command |
|---|---|---|---|
| Digital PDF with an existing text layer | `pdftotext` | `document-tools` | `pdftotext input.pdf -` |
| Image / screenshot / photo of text | `tesseract` | `ocr-tools` (core) | `tesseract image.png stdout -l eng` |
| Scanned PDF → searchable PDF output | `ocrmypdf` | `ocr-tools` (`ocrmypdf` feature) | `ocrmypdf --skip-text scanned.pdf searchable.pdf` |
| Scanned PDF → plain text (without `ocrmypdf`) | `pdftoppm` + `tesseract` | `document-tools` + `ocr-tools` | `pdftoppm -png -r 300 in.pdf page && tesseract page-1.png stdout` |
| Complex tables, multi-column reading order, formulas | `docling` | `document-tools` (`docling` feature) | `docling input.pdf` |
| Detect page orientation and script | `tesseract --psm 0` | `ocr-tools` (core `osd`) | `tesseract page.png stdout --psm 0` |

## Common Recipes

### Extract Text from an Image to Stdout or File

```sh
# Print recognized text directly to stdout
tesseract screenshot.png stdout -l eng

# Multilingual recognition (when lang-fin feature is enabled)
tesseract invoice.png stdout -l fin+eng

# List all installed language packs in the current container
tesseract --list-langs
```

### Page Segmentation Modes (`--psm`)

| `--psm` | Mode Description | Best For |
|---|---|---|
| `0` | Orientation and script detection (OSD) only | Detecting rotated pages (requires `osd`) |
| `3` | Fully automatic page segmentation (default) | Standard document pages |
| `4` | Single column of text of variable sizes | Receipts, invoices, narrow columns |
| `6` | Single uniform block of text | Cropped paragraphs, book pages |
| `7` | Single text line | Cropped headers, serial numbers, plates |
| `11` | Sparse text (find as much text as possible) | UI screenshots, diagrams, signage |

### Preprocess Low-Quality Images with `image-tools` (`magick`)

Tesseract performs best on ~300 DPI dark-text-on-light-background images. When `image-tools` is enabled, upscale and clean noisy screenshots before OCR:

```sh
magick lowres_screenshot.png -colorspace Gray -resize 200% -deskew 40% -sharpen 0x1 /tmp/cleaned.png
tesseract /tmp/cleaned.png stdout --psm 6
```

### Export Positioned Text (hOCR / TSV / ALTO XML)

```sh
tesseract page.png output_base -l eng hocr
tesseract page.png output_base -l eng tsv
tesseract page.png output_base -l eng alto
```

## Available Language Features (`lang-*`)

Core includes `eng` (English) and `osd` (Orientation & Script Detection). Enable additional languages via `ocr-tools` features:

| Feature | `-l` Code | Language | Feature | `-l` Code | Language |
|---|---|---|---|---|---|
| `lang-ara` | `ara` | Arabic | `lang-jpn` | `jpn` | Japanese |
| `lang-ces` | `ces` | Czech | `lang-kor` | `kor` | Korean |
| `lang-chi-sim` | `chi_sim` | Chinese (Simplified) | `lang-nld` | `nld` | Dutch |
| `lang-chi-tra` | `chi_tra` | Chinese (Traditional) | `lang-nor` | `nor` | Norwegian |
| `lang-dan` | `dan` | Danish | `lang-pol` | `pol` | Polish |
| `lang-deu` | `deu` | German | `lang-por` | `por` | Portuguese |
| `lang-ell` | `ell` | Greek | `lang-rus` | `rus` | Russian |
| `lang-fin` | `fin` | Finnish | `lang-spa` | `spa` | Spanish |
| `lang-fra` | `fra` | French | `lang-swe` | `swe` | Swedish |
| `lang-heb` | `heb` | Hebrew | `lang-tur` | `tur` | Turkish |
| `lang-hin` | `hin` | Hindi | `lang-ukr` | `ukr` | Ukrainian |
| `lang-hun` | `hun` | Hungarian | `lang-vie` | `vie` | Vietnamese |
| `lang-ita` | `ita` | Italian | | | |

## Caveats

- **LSTM-only models (`tessdata_fast`):** Fedora's `tesseract-langpack-*` packages ship integer-quantized LSTM models (`--oem 1` / default `--oem 3`). **Never pass `--oem 0` or `--oem 2`** (legacy Tesseract 3 engine), or Tesseract will abort with a missing component error.


# ==============================================================================
# FILE: pa_packages/ocr-tools/features/ocrmypdf/skill/SKILL.md
# ==============================================================================
## Feature: `ocrmypdf` (Searchable PDF Layering)

`ocrmypdf` rasterizes scanned PDF pages via Ghostscript, runs Tesseract OCR, and embeds an invisible searchable text layer using `pikepdf` while preserving original vector graphics and existing digital text pages.

### Recipes

- **Add a searchable text layer (skipping pages that already have text):**
    ```sh
    ocrmypdf --skip-text input.pdf searchable.pdf
    ```
- **Multilingual OCR with auto-rotation and deskewing:**
    ```sh
    ocrmypdf --skip-text --rotate-pages --deskew -l fin+eng scanned.pdf searchable_fixed.pdf
    ```
- **Produce a searchable PDF AND a sidecar plain-text file in one pass:**
    ```sh
    ocrmypdf --skip-text --sidecar extracted_text.txt scanned.pdf searchable.pdf
    ```
