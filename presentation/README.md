# Presentation assets

Portfolio / demo deliverables for the Heweso Competitive Pricing Agent. Generated 2026-08-04.

| File | What it is |
|---|---|
| `Heweso_Satis_Sunumu.pptx` | 13-slide **sales pitch** deck (Turkish). Audience = Heweso management; the product is positioned as a premium autonomous-pricing capability Heweso adds to its platform for its mid-size retailer customers. ROI figures are an **illustrative example scenario** (assumptions in each slide's speaker notes), not real data. No pricing slide — closes with a pilot proposal. |
| `Heweso_Sistem_Akisi.pptx` | Single-slide **end-to-end system-flow diagram**. Swimlane header (ACTORS · UYGULAMA & VERİ · TETİKLEME · AWS BULUT) + 5 LOOP bands (setup, trigger, agent decision, data pipeline, weekly analytics). Every node is an editable shape + white icon glyph. |
| `deck_build.js` | pptxgenjs generator for the sales deck. |
| `diagram_build.js` | pptxgenjs generator for the system-flow diagram (also renders react-icons glyphs into the node tiles). |

## Rebuild

`pptxgenjs` is the only hard dependency for the deck; the diagram additionally needs the icon toolchain.

```bash
# deck
npm install pptxgenjs
node deck_build.js            # -> Heweso_Satis_Sunumu.pptx

# diagram (needs icon libs too)
npm install pptxgenjs react react-dom sharp react-icons
node diagram_build.js         # -> Heweso_Sistem_Akisi.pptx
```

Notes:
- Both scripts use a custom slide size; the deck is 13.33×7.5, the diagram 13.33×9.0.
- The diagram icons are Font Awesome 6 glyphs (`react-icons/fa6`) rendered white → transparent PNG via `sharp`, embedded per node. Swap the `ICONMAP` entries to change icons.
- No LibreOffice on this machine — visual QA was done by exporting to PDF via Keynote (`osascript`) then `pdftoppm`. In a normal environment use the pptx skill's `soffice.py` + `pdftoppm` pipeline instead.

Every element is editable in PowerPoint/Keynote (boxes = shapes, icons = images, text = text boxes) — nothing is a flattened image.
