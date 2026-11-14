## Feature: `vips` (libvips Streaming Processing)

`vips` streams images through a demand-driven pipeline with minimal RAM, making it the preferred tool for very large images (gigapixel scans, satellite imagery, deep-zoom tile pyramids) where `magick` would exhaust container memory.

### Recipes

- **Fast thumbnail generation (shrink-on-load):**
    ```sh
    vips thumbnail huge.tif thumb.webp 800 --height 800
    ```
- **Generate DeepZoom (`dzsave`) tile pyramids:**
    ```sh
    vips dzsave huge.tif tiles_dir --suffix .webp[Q=80]
    ```
- **Inspect image header without decoding pixels:**
    ```sh
    vipsheader -a huge.tif
    ```
