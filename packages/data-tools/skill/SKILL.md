# Structured Data Processing (`data-tools`)

Provides tools for querying, transforming, formatting, and inspecting structured data formats.

## Constituent Tools
- `jq`: High-performance stream processor and query language for JSON.
- `yq`: Portable command-line YAML, JSON, XML, CSV, and properties processor.
- `mlr` (Miller): Multi-format tabular data processor (CSV, TSV, JSON, DKVP).

## Usage Guidelines
- **JSON Processing (`jq`)**:
    - Extract fields: `jq '.items[].name' data.json`
    - Filter arrays: `jq '[.[] | select(.active == true)]' users.json`
    - Compact formatting: `jq -c '.' input.json`
- **YAML & Document Processing (`yq`)**:
    - Query nested YAML: `yq '.spec.containers[0].image' deployment.yaml`
    - In-place mutation: `yq -i '.metadata.labels.version = "2.0"' service.yaml`
    - Convert formats: `yq -p=yaml -o=json deployment.yaml > deployment.json`
- **Tabular & Delimited Data (`mlr`)**:
    - Inspect CSV schema and stats: `mlr --csv stats1 -a min,mean,max -f price,qty data.csv`
    - Filter and cut tabular data: `mlr --csv filter '$status == "ok"' then cut -f id,name,status records.csv`
    - Convert CSV to pretty JSON: `mlr --c2j cat data.csv | jq '.'`
