---
name: data-tools
description: "Structured data manipulation: jq for JSON, yq for YAML/XML, and Miller (mlr) for tabular CSV/TSV and record processing."
---

# Structured Data Tools (`data-tools`)

Provides command-line utilities for querying, transforming, and converting structured data formats (JSON, YAML, XML, CSV, TSV).

## Tool Overview

| Task | Tool | Primary Command |
|---|---|---|
| Query, filter, and transform JSON | `jq` | `jq '.items[] \| .name' data.json` |
| Query, modify, and convert YAML / XML | `yq` | `yq '.spec.replicas' config.yaml` |
| Process tabular CSV / TSV with relational verbs | `mlr` (`miller`) | `mlr --icsv --opprint stats1 -a mean,stddev -f latency data.csv` |
| Convert between JSON, YAML, and CSV | `yq` / `mlr` | `yq -o=json config.yaml > config.json` |

## Common Recipes

### Query and Modify YAML Files with yq

```sh
# Read nested value
yq '.metadata.name' deployment.yaml

# Modify value in-place
yq -i '.spec.replicas = 3' deployment.yaml

# Convert YAML to clean JSON
yq -o=json deployment.yaml > deployment.json
```

### Tabular CSV Processing with Miller (mlr)

Miller treats CSV/TSV files like database tables without requiring heavy Python libraries:

```sh
# Filter rows and print formatted ASCII table
mlr --icsv --opprint filter '$status == "FAILED"' test_results.csv

# Group by category and compute aggregate statistics
mlr --icsv --opprint stats1 -a count,mean -f execution_time_ms -g category results.csv

# Convert CSV to JSON array
mlr --icsv --ojson cat data.csv > data.json
```

### Extract Array Values with jq

```sh
# Extract array elements matching condition
jq '.agents[] | select(.driver == "pi") | .id' factory.json
```
