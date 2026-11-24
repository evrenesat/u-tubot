# Third-party code

The only third-party source copied into this backend is the `scene-analyser` directory of
[`evrenesat/r2t4`](https://github.com/evrenesat/r2t4). That repository is public but has no
licence file, so reuse is not implied by publication. Every commit under `scene-analyser` is
the repository owner's; on 2026-11-24 he allowed this copy under **MIT**. The copy lives under
`src/utubot/watch/` and carries the same MIT licence in `src/utubot/watch/LICENSE`
(copyright © 2026 Evren Özkan).

Adapted at commit `29075554`, by the repository owner, contributed under MIT:

| u·tubot file | `scene-analyser` origin |
|---|---|
| `src/utubot/watch/frame_selector.py` | `frame_selector.py` (low-resolution analysis, adaptive chunks, four-frame selection; the numpy accelerator and module constants are dropped) |
| `src/utubot/watch/grids.py` | `extractor_v1.py` (shot probe, extraction, stitching) and the grid pieces of `frame_selector.py`; plus the quiet-stretch rule and the grid cap |
| `src/utubot/watch/memory.py` | `scene_memory.py` and the bounded strategy of `context_strategies.py` |
| `src/utubot/watch/tdt.py` | `tdt_format.py` (the slim format and validator; film fields dropped) |

The ideas reused without code — S-style evidence lines, unit ids as the only keepable things,
technical shot boundaries vs scenes, and bounded running context — are described in
`temp/plan.md` (2.0, 1.3), not copied source.

Dependencies of the original and of this copy: Pillow (MIT-CMU) and `ffmpeg` as an external
program. No `r2t4` package is installed. The original's `json-repair` (MIT) is not a
dependency of the copy: the backend's own JSON retry handles the one bad answer.

The copied files are adapted, not vendored unchanged: paths come from the scratch directory,
thresholds from `[cuts.watched]`, child `ffmpeg` calls go through `watch/ffmpeg.py` with a
cancel event, and the backend's job/event/progress rules wrap them. Do not remove the origin
header from a copied file.
