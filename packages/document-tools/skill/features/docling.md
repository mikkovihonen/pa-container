## Optional Feature: Docling AI-Native Document Parser (`docling`)

Provides deep neural layout analysis and document structure extraction (PDF, DOCX, PPTX, XLSX to Markdown / JSON).

### Usage
- Convert PDF to structured Markdown: `docling input.pdf --to md -o output/`
- Convert DOCX to Markdown: `docling document.docx --to md`
- Output full document JSON AST: `docling input.pdf --to json`
