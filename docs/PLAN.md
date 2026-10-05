# Plan

## Who it is for

Animation students who have drawn on paper, photographed or scanned each
drawing, and need the drawings on a transparent background in OpenToonz.
They should not need Python, a terminal, or Photoshop.

## Decisions

| Decision | Why |
|---|---|
| One `.exe` in a zip, no installer | Works from Downloads or a USB stick; nothing needs admin rights. Browsers block a zip less often than a bare `.exe`. |
| Built by GitHub Actions on a version tag | Nobody builds by hand; the Releases page is the one link to hand out. |
| Tkinter window | Ships with Python, so the app stays small and has few parts to break. |
| Three numbered steps on one screen | A student can finish without reading instructions. |
| Two sliders in plain words | The engine has more controls, but these two fix nearly every case. |
| Live preview with hold-Space compare | Students see the result before committing a whole shot. |
| Output goes to `<folder>_clean` | Originals are never touched, and there is no save dialog to get wrong. |
| Same file names, same pixel size, always PNG | Frame numbers and registration carry over. |
| Settings are remembered | A student shooting on the same setup adjusts once. |

## Known limits

- The `.exe` is unsigned, so Windows SmartScreen warns on first run. College
  lab machines that block unsigned apps will need IT to allow it, or the app
  can be run from source.
- Output is always one line colour. Blue and red pencil are not kept as
  separate colours.
- Anything darker than the paper is kept, including margin notes.
- Windows only for the packaged app. The source runs on macOS and Linux.

## Could come next

1. **Keep pencil colours** (blue rough, red notes, graphite clean-up) as an option.
2. **Drag and drop** a folder onto the window.
3. **Crop** a margin off every drawing to remove table edges and timing charts.
4. **Peg-hole registration** to line up drawings shot slightly out of place.
5. **macOS build** from the same workflow.
6. **Code signing** to remove the SmartScreen warning.
