## Feature: `gmic` (G'MIC Image Processing Framework)

`gmic` provides a stack-based command-line pipeline with hundreds of mathematical, artistic, denoising, and morphological image filters.

### Recipes

- **Denoise and sharpen an image:**
    ```sh
    gmic input.png -denoise_patch 5,7 -sharpen 100 -o output.png
    ```
- **Evaluate pixel statistics or resize with Lanczos:**
    ```sh
    gmic input.png -resize 50%,50%,1,3,6 -o half.png
    ```
