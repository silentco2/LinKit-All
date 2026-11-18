# LinKit All logo

**Meaning:** an "lk" monogram on a rubber-stamp tile, set slightly crooked inside a double ring, like a stamp pressed on an application. The -3 degree tilt and the ring keep it apart from LinkedIn's square tile.

## Files

| File | Use |
|---|---|
| `logo-symbol.svg` | The mark, colour, light backgrounds |
| `logo-symbol-dark.svg` | The mark, colour, dark backgrounds |
| `logo-symbol-black.svg` / `logo-symbol-white.svg` | One colour (print, stamps, single-ink) |
| `logo-symbol-small.svg` | 16-31 px: no ring, no tilt, thicker letters |
| `logo-horizontal.svg` / `-dark` / `-black` | Symbol + wordmark, side by side (default lockup) |
| `logo-stacked.svg` | Symbol over wordmark (square spaces) |
| `web-icons/` | `favicon.ico`, `favicon.svg`, `apple-touch-icon.png` (180), `icon-192.png`, `icon-512.png`, `site.webmanifest` |
| `concepts/` | Exploration history; `build_final.py` regenerates every file above |

The knockouts (letters and ring gap) are real holes, so the background shows through.

## Colours

| Name | HEX | RGB | Use |
|---|---|---|---|
| Stamp blue | `#2c43a6` | 44, 67, 166 | Tile, light mode |
| Stamp blue (dark) | `#9dadf5` | 157, 173, 245 | Tile, dark mode |
| Ink | `#1f1d1a` | 31, 29, 26 | Wordmark, light mode |
| Dark-mode text | `#efebe3` | 239, 235, 227 | Wordmark, dark mode |
| Paper | `#fbfaf7` | 251, 250, 247 | Light background |
| Dark desk | `#191816` | 25, 24, 22 | Dark background |

## Clear space and sizes

- Clear space: twice the ring width (11 units of the 256 grid, so 22 units, about 9% of the symbol's width) on every side.
- Minimum size: full symbol 32 px (10 mm in print). Below that use `logo-symbol-small.svg` (down to 16 px). Horizontal lockup: 24 px tall minimum.

## Do not

- Do not untilt the full mark (the small cut is the only untilted version).
- Do not recolour to LinkedIn blue `#0A66C2`.
- Do not remove the ring at large sizes.
- No shadows, gradients, outlines or effects; do not stretch or rotate further.
- Do not set the wordmark in another font.

## Notes

- No trademark search has been done. Run one before relying on the name or mark.
- The wordmark is IBM Plex Sans Medium, converted to outlines (SIL OFL 1.1, which allows this). The files contain no live text.
