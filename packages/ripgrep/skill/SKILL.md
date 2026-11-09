---
name: ripgrep
description: Fast recursive text and regex search across codebases using ripgrep (rg).
---

# ripgrep (rg)

## Common Commands

### 1. Search for Text
```bash
rg "search_term"
```

### 2. Search Specific File Types
```bash
rg "fn main" -t rust
rg "class " -t py
```

### 3. Case Insensitive Search
```bash
rg -i "pattern"
```
