---
name: image-tools
description: "Use when converting, resizing, cropping, compositing, or optimizing raster images (PNG, JPEG, WebP, TIFF, JXL, HEIF), reading or stripping metadata with ExifTool, streaming gigapixel images with libvips, or tracing bitmaps into SVG vectors with Potrace."
---

# Image Processing (`image-tools`)

Provides ImageMagick 7, ExifTool, WebP, OxiPNG, Potrace, libvips, and modern image codecs (JPEG XL and HEIF/AVIF) for asset generation, frontend optimization, and diagram processing.

## Tool Overview

| Task | Tool | Primary Command |
|---|---|---|
| Convert, resize, crop, annotate, montage | ImageMagick 7 (`magick`) | `magick input.png -resize 800x600 output.webp` |
| Batch modify images in place or to a directory | ImageMagick 7 (`magick mogrify`) | `magick mogrify -path out/ -format webp -quality 82 *.jpg` |
| Trace bitmap (PBM/PGM/BMP) to vector SVG | `potrace` + `mkbitmap` | `mkbitmap -s 2 -t 0.48 in.pbm -o - \| potrace -s -o out.svg` |
| Inspect or edit metadata (comprehensive) | `exiftool` | `exiftool -a -u -g1 image.jpg` |
| Encode / decode WebP directly | `cwebp` / `dwebp` | `cwebp -q 80 input.png -o output.webp` |
| Lossless PNG recompression | `oxipng` | `oxipng -o 4 --strip all image.png` |
| High-performance streaming image processing | `vips` | `vips thumbnail huge.tif thumb.webp 800 --height 800` |
| Encode / decode JPEG XL | `cjxl` / `djxl` | `cjxl input.png output.jxl -d 1.0` |
| Convert Apple HEIC photos to JPEG / PNG | `heif-convert` | `heif-convert input.heic output.jpg` |

## Common Recipes

### Resize and Strip Metadata for Web Delivery

```sh
magick input.jpg -auto-orient -strip -resize "1600x1600>" -quality 82 output.webp
```

### Lossless PNG Optimization with OxiPNG

```sh
oxipng -o 4 --strip all input.png --out optimized.png
```

### Vectorize a Raster Logo to SVG

`potrace` accepts PBM/PGM/PPM/BMP inputs; convert raster formats via `magick` first:

```sh
magick logo.png -colorspace Gray -negate pnm:- | mkbitmap -s 2 -t 0.45 - -o - | potrace -s -o logo.svg
```

### Fast Streaming Thumbnails for Large Files with `vips`

`vips` streams images with minimal memory footprint:

```sh
vips thumbnail huge.tif thumb.webp 800 --height 800
vipsheader -a huge.tif
```

### Modern Codecs: JPEG XL and Apple HEIC

```sh
# Encode to JPEG XL
cjxl input.png output.jxl -d 1.0

# Extract Apple HEIC to JPEG
heif-convert input.heic output.jpg
```

### Strip All Metadata from a Directory

```sh
exiftool -all= -overwrite_original dir/*.jpg dir/*.png
```

## Guidelines
- **Always use `magick`**: Use `magick input.png ... output.png` instead of legacy `convert`.
- **Output storage**: Write processed media to `/tmp/pa-media` or project assets directories.
- **Text recognition**: Route OCR tasks to `ocr-tools` (`tesseract` / `ocrmypdf`).
