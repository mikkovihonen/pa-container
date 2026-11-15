---
name: ocr-tools
description: "Use when extracting text from images, photos, receipts, screenshots, or scanned PDF documents using Tesseract OCR or adding searchable text layers to PDFs using OCRmyPDF."
---

# Optical Character Recognition (`ocr-tools`)

Provides optical character recognition (OCR) engines for extracting text from images and creating searchable PDFs.

## Tool Overview

| Task | Tool | Primary Command |
|---|---|---|
| Extract text from image to stdout or file | `tesseract` | `tesseract input.png stdout` |
| Extract text to PDF with invisible text layer | `tesseract` | `tesseract input.png output pdf` |
| Add searchable text layer to multi-page PDF | `ocrmypdf` | `ocrmypdf --skip-text input.pdf searchable.pdf` |
| Generate searchable PDF + sidecar text file | `ocrmypdf` | `ocrmypdf --skip-text --sidecar out.txt input.pdf searchable.pdf` |

## Common Recipes

### Extract Plain Text from Image

```sh
# Output text directly to stdout
tesseract document.png stdout -l eng

# Output to text file document.txt
tesseract document.png document -l eng
```

### Preprocessing Images for Higher Accuracy

Always upscale or binarize low-resolution images with `image-tools` before invoking Tesseract:

```sh
magick input.jpg -resize 200% -colorspace Gray -threshold 50% /tmp/prepared.png
tesseract /tmp/prepared.png stdout
```

### Searchable PDF with `ocrmypdf`

`ocrmypdf` embeds a searchable text layer while preserving existing vector graphics:

```sh
# Auto-rotate pages and deskew scanned documents
ocrmypdf --skip-text --rotate-pages --deskew input.pdf output_searchable.pdf

# Multi-lingual OCR (e.g. English + Finnish)
ocrmypdf --skip-text -l eng+fin scanned.pdf searchable.pdf
```

## Guidelines
- **Output paths**: Write intermediate images and output text files to `/tmp/pa-media`.
- **Text skipping**: Use `--skip-text` with `ocrmypdf` to avoid re-rasterizing digital PDF pages that already contain selectable text.
