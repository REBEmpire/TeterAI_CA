# Build Resources — Icon Files

Place the following icon files in this directory before running `npm run build` in `src/ui/desktop/`.
electron-builder will pick them up automatically based on the target platform.

| File | Platform | Required Size | Format |
|---|---|---|---|
| `icon.ico` | Windows | 256×256 (multi-resolution ICO recommended) | ICO |
| `icon.icns` | macOS | 512×512 (ICNS with multiple resolutions) | ICNS |
| `icon.png` | Linux | 512×512 | PNG |

## Generating icons from a source PNG

If you have a high-resolution PNG (`icon-source.png`, min 512×512):

**macOS (using `iconutil`):**
```bash
mkdir icon.iconset
sips -z 16 16   icon-source.png --out icon.iconset/icon_16x16.png
sips -z 32 32   icon-source.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32   icon-source.png --out icon.iconset/icon_32x32.png
sips -z 64 64   icon-source.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128 icon-source.png --out icon.iconset/icon_128x128.png
sips -z 256 256 icon-source.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256 icon-source.png --out icon.iconset/icon_256x256.png
sips -z 512 512 icon-source.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512 icon-source.png --out icon.iconset/icon_512x512.png
iconutil -c icns icon.iconset -o icon.icns
```

**Windows (using ImageMagick):**
```bash
magick icon-source.png -resize 256x256 icon.ico
```

**Linux:**
```bash
cp icon-source.png icon.png
```

## Note

electron-builder will still package and produce an installer without icons —
it will use a default Electron icon as a placeholder. Add real icons before
distributing to end users.
