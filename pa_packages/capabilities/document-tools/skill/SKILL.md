---
name: document-tools
description: "Document conversion and extraction: Pandoc for universal format conversion (Markdown, HTML, DOCX, LaTeX) and Poppler for PDF text and image extraction."
---

# Document Tools (`document-tools`)

Provides tools for document format conversion, PDF inspection, text extraction, and embedded image extraction using Pandoc and Poppler.

## Tool Overview

| Task | Tool | Primary Command |
|---|---|---|
| Convert Markdown, HTML, LaTeX, DOCX | `pandoc` | `pandoc input.md -o output.docx` |
| Extract text from PDF documents | `pdftotext` | `pdftotext input.pdf output.txt` |
| Extract embedded images from PDF | `pdfimages` | `pdfimages -png input.pdf /tmp/extracted_img` |
| Inspect PDF metadata and page count | `pdfinfo` | `pdfinfo input.pdf` |
| Render PDF pages to PNG raster images | `pdftoppm` | `pdftoppm -png -r 150 input.pdf /tmp/page` |

## Common Recipes

### Convert Markdown to Standalone HTML with CSS

```sh
pandoc document.md --standalone -o document.html
```

### Fast PDF Text Extraction

```sh
# Extract text to stdout
pdftotext input.pdf -

# Extract text preserving layout spacing
pdftotext -layout input.pdf output.txt
```

### Render PDF Pages to PNG for Visual Verification

```sh
# Render first page at 200 DPI
pdftoppm -png -r 200 -f 1 -l 1 input.pdf /tmp/page_1
```

## Guidelines
- **Output paths**: Write intermediate extracted text and images to `/tmp/pa-docs`.
- **Delegates**: To rasterize PDF pages with ImageMagick without delegate policy restrictions, use `pdftoppm -png` first.
