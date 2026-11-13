## Feature: `jxl-heif` (JPEG XL and HEIF/AVIF Codecs)

Adds `cjxl`/`djxl`/`jxlinfo` (`libjxl-utils`), `heif-enc`/`heif-convert`/`heif-info` (`libheif-tools`), and the `ImageMagick-heic` delegate.

### Recipes

- **Encode / decode JPEG XL:**
    ```sh
    cjxl input.png output.jxl -d 1.0
    djxl output.jxl decoded.png
    ```
- **Lossless JPEG transcoding to JPEG XL (reversible back to exact original JPEG):**
    ```sh
    cjxl photo.jpg photo.jxl --lossless_jpeg=1
    ```
- **Convert Apple HEIC photos to JPEG or PNG:**
    ```sh
    heif-convert input.heic output.jpg
    magick input.heic -auto-orient output.webp
    ```
