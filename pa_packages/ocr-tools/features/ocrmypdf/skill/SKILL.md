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
