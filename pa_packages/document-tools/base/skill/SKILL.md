# Document Tools (Pandoc and Poppler)

Universal document converter (Pandoc) and PDF text/metadata extraction tools (Poppler utilities).

## Tool Triage
- Convert markdown, docx, html, latex: `pandoc input.md -o output.pdf`
- Extract text from PDF: `pdftotext input.pdf output.txt`
- Extract images from PDF: `pdfimages -png input.pdf img`
- Inspect PDF metadata: `pdfinfo input.pdf`
