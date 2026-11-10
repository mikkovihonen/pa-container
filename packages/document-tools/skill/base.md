# Document Tools (`document-tools`)

Provides tools for document conversion, markup transformation, and PDF inspection/text extraction.

## Constituent Tools
- `pandoc`: Universal markup converter supporting Markdown, HTML, PDF, DOCX, LaTeX, EPUB, and more.
- `pdftotext`: High-performance PDF text extractor preserving layout or sequential text.
- `pdfinfo`: PDF metadata and page metrics inspector.
- `pdftoppm`: PDF page to raster image (PNG/JPEG) renderer.
- `pdfimages`: Extract raw image streams embedded inside PDF files.

## Usage Guidelines
- **Pandoc Format Conversion**:
    - Convert Markdown to HTML: `pandoc document.md -o document.html --standalone`
    - Convert Markdown to DOCX: `pandoc notes.md -o notes.docx`
    - Strip formatting / convert to plain text: `pandoc input.docx -t plain -o output.txt`
- **PDF Extraction**:
    - Extract text from PDF: `pdftotext document.pdf extracted.txt`
    - Extract text preserving physical layout: `pdftotext -layout table.pdf extracted_table.txt`
    - Inspect document metadata and page count: `pdfinfo report.pdf`
    - Render first page of PDF as PNG: `pdftoppm -png -f 1 -l 1 report.pdf page1`
    - Extract all images embedded in PDF: `pdfimages -png report.pdf extracted_images/img`
