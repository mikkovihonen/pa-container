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
| Trace bitmap (PBM/PGM/BMP) to vector SVG | `potrace` + `mkbitmap` | `mkbitmap -s 2 -t 0.48 in.pbm -o - | potrace -s -o out.svg` |
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
