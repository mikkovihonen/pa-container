---
name: document-tools
description: Docling AI-native document parser for deep layout analysis and structure extraction (PDF, DOCX, PPTX, XLSX to Markdown or JSON).
---

# Docling AI-Native Document Parser (`docling`)

The `docling` feature provides neural layout analysis and document structure extraction. It converts PDF, DOCX, PPTX, and XLSX files to Markdown or JSON.

## Usage
- Convert a PDF to structured Markdown: `docling input.pdf --to md -o output/`
- Convert a DOCX file to Markdown: `docling document.docx --to md`
- Output the full document JSON AST: `docling input.pdf --to json`
