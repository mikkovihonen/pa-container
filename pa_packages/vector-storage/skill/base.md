# Vector Storage (`vector-storage`)

Provides embedded vector storage and SIMD-accelerated distance computation for SQLite and standalone applications.

## Constituent Components
- `sqlite-vec`: Native C SIMD vector search extension for SQLite (provides `/usr/local/lib/sqlite/vec0.so`).
- `USearch`: Fast, single-file vector search engine extension for SQLite and C library (provides `/usr/local/lib/sqlite/usearch_sqlite.so` and `/usr/local/lib/libusearch.so`).

## Usage Guidelines
- **`sqlite-vec`**:
    - Load extension: `.load /usr/local/lib/sqlite/vec0`
    - Check version: `SELECT vec_version();`
    - Create vector table:
        ```sql
        CREATE VIRTUAL TABLE vec_items USING vec0(embedding float[1536]);
        ```
- **`USearch`**:
    - Load extension: `.load /usr/local/lib/sqlite/usearch_sqlite`
    - Compute cosine distance:
        ```sql
        SELECT distance_cosine_f32('[1.0, 2.0]', '[2.0, 3.0]');
        ```
    - Compute Hamming string distance:
        ```sql
        SELECT distance_hamming_unicode('alpha', 'aloha');
        ```
