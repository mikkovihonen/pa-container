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
