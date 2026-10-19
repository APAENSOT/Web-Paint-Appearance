# Monthly Detail vehicle references

The owner supplied grayscale references from `C:/Users/Salmon/Downloads/Profile`: P703 Ranger, P703 Raptor, Super Duty, U704, V363 and J73. CX743 now uses the owner's `CX743.png`, copied unchanged to `territory.png` (SHA-256 `3831caf3b2fbdfe75b47a58700876f6787c5fb94d47bef774023c54fa742ebc5`). Existing body-model Standard bindings remain authoritative.

`ranger-sgl-body.png`, `ranger-rapcap-body.png` and `territory-body.png` were older shell screenshots (`20261013-repair-3`) that no gallery card selected; removed 2026-10-20, recoverable with `git show 62ef45f:frontend/public/models/profiles/<file>`. The local development capture entry `model-thumbnails.html?model=<exact model code>` renders the current GLB through Studio. The supplied CX482/Escape picture is deliberately not used for CX743/Territory.

Gallery photos retain the original supplied files. SGL and RAPCAP reuse ranger.png at the owner's request. Monthly Detail now overlays the saved plant colour only through the body-surface masks in `masks/`. Glass, lamps, wheels, badges, grille, shadows and background remain in the original photo. An SVG channel transfer retains body shading and highlights. No saved colour means the original photo is shown. This is an illustrative reference, not a calibrated paint match or a claim that every model × colour combination has production samples. The opened 3D body uses the actual saved HEX and Standard Solid/Metallic finish.

The generated design references (kept by the owner, not in this repository) are critique references only. Their illustrative counts are never used in the application.

