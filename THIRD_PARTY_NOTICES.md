# Third-party notices

## Eidolon-SC

- Source: https://github.com/Sallyn0225/eidolon-sc
- Upstream baseline: `caa71b63e610e54ca6cff47e12ada0434d3d88a2`
- License: GNU AGPL version 3 or later, with the upstream section 7 additional permission concerning Spine Runtimes.
- Kaibun was extracted and modified on 2026-11-14. Shared Python adapters, character profiles, reading rules, frontend components and stand rendering code retain their upstream origin. The local Kaibun extension is included in this independent derivative.

## shadcn/ui styles and generated UI components

- Source: https://github.com/shadcn-ui/ui
- License: MIT; preserved at `frontend/licenses/shadcn-MIT.md`.
- `frontend/src/app/shadcn.css` is copied from the shadcn 4.23.0 stylesheet. The CLI is not a runtime dependency.

## Spine Runtimes

- Source and historical version: https://github.com/EsotericSoftware/spine-runtimes/tree/3.6
- Historical upstream commit: `654c20e5b0e523040b6366bbd1042510d2645134`.
- The runtime JavaScript and proprietary game assets are NOT included. The historical license text is preserved in `frontend/public/vendor/spine-3.6/LICENSE` for reference. Supplying or distributing a runtime requires complying with its applicable Esoteric Software terms; the AGPL exception does not grant those third-party rights.

## Installed dependencies

Python and npm dependencies are declared in `backend/pyproject.toml` and `frontend/package.json`, with exact resolutions in their lockfiles. Packages retain their own copyright notices and licenses. See the installed packages' metadata when redistributing dependency bundles.

FFmpeg is supplied by `imageio-ffmpeg` when not provided by the user. FFmpeg has its own LGPL/GPL licensing depending on the binary's build; see https://ffmpeg.org/legal.html and the distributor's notices. No FFmpeg binary is included in this source release.

## Original works and asset services

THE iDOLM@STER SHINY COLORS and its characters and related original content belong to Bandai Namco Entertainment Inc. and their respective rightsholders. ShinyColorsDB and viewer.shinycolors.moe are referenced as upstream data/catalog sources, not as grants of ownership or redistribution permission. Fish Audio is an optional external service; character voice reference IDs from the original configuration are included, but no API keys, voice models or reference recordings are distributed. Availability and permission must be checked with the service and the relevant rightsholders.
