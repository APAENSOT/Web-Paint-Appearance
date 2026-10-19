# Studio exterior bodies - CX743 update 2026-10-14

Eight prepared bodies are registered for colour setup and point-profile saving in Model Detail when their exact model is offered by the plant Standard. Their backend registry pins the file hash, mesh names and mesh-local bounds. The accepted Ranger file and its point coordinates are unchanged.

| Body | Geometry and source |
|---|---|
| Ranger SGL | Credited Ranger derivative. Cab shortened 0.75 m; curved rear-window infill; original pressed door surfaces retained with localized handle infill. Complete bed and tailgate translated rigidly, preserving wheel arches. Roof stamping fitted to side rails. |
| Ranger RAPCAP | Credited Ranger derivative. Cab shortened 0.33 m; original access-door pressings retained with boundary-fitted rear-handle infill. Complete bed translated without stretching. Roof stamping fitted to side rails. |
| Raptor | Credited Ranger derivative. One 1.075 lateral scale preserves non-roof panel relationships; roof stamping fitted to side rails. Simplified wide-body interpretation. |
| Ranger Super Duty | Replaces the old 2010 extraction. Modern Ranger double-cab derivative, 1.035 lateral scale, guided by the owner's new body references. |
| Everest / U704 | Supplied 2023 FBX panels and recovered pillars; sunroof aperture, original roof stamping fitted to rails, original contoured rear returns and central liftgate skin; loose front fragments removed. Earlier rectangular patches are removed. |
| Transit / V363 | Supplied 2020 high-roof body; side windows and separate rear-door windows, lower skin fitted to the source upper boundary, curved lower return, locks and floor. Highlighted central lower front bumper surfaces removed. |
| Amarok / J73 | Supplied 2011 exterior panels and recovered pillars; small loose pieces below hood removed. |
| Territory / CX743 | Extracted from the owner's `Territory+2022.skp`. Original curved bonnet, four doors, fenders, quarter panels, roof and liftgate are retained. Window pillars are restored as neutral metal, the panoramic opening is preserved, and a curved return joins the liftgate skins. Glass, wheels and fitted equipment are excluded. |

These are visualization shells, not engineering CAD or complete structural body-in-white. Glass, wheels, lamps, mirrors, interior equipment, bumpers and drivetrain are omitted. Reconstructed panels and scale changes are modelling choices, not certified dimensions.

## Identity and future points

Frontend `body-assets.ts` and backend `prepared_model_assets.json` use the exact Standard model codes, including `J73 DBL` for Amarok. CX743 uses `territory@20261014-cx743-reference-2`; the other prepared bodies retain `<body-id>@20261013-repair-3`. One profile per plant + model + domain is shared across colours and months. Prepared bodies support whole-body placement and camera views; the accepted Ranger also supports its existing focused panel regions. The Escape CX482 label and point numbers in the reference image were not imported as CX743 data.

A changed body requires explicit registration of a new immutable version/hash. Old anchors remain stored and are disclosed as incompatible until replotted; they are never transferred automatically. The owner's registration script freezes approved metadata and marks this manifest registered; a fresh geometry packaging run returns candidates to review status.

## Attribution

Ranger derivatives including modern Super Duty retain `../ranger/ATTRIBUTION.md`: Asadawut.Kaewma, CC BY 4.0, Ford Ranger Next-Gen 2023 Sport, with modifications listed above. Other source archives, including `Territory+2022.skp`, were supplied by the owner and had no accompanying author/license record. This does not assign the Ranger licence to other sources. Territory was converted locally using [OpenSKP 0.2.5](https://extensions.blender.org/add-ons/openskp-import-export/); the supplied files were not uploaded.

## Rebuild and checks

The GLB files here are final. The model-preparation tooling (Blender scripts under `frontend/scripts/model-assets/` and `backend/scripts/register_studio_assets.py` in the original working repository) and the source archives stay with the owner and are not part of this repository; ask the owner if a body has to be rebuilt.

CX743 references: [Ford 2021 CX743 owner manual](https://www.fordservicecontent.com/Ford_Content/Catalog/owner_information/2021-Territory_CX743_CF4-PHL-OM.pdf), owner's Territory photo and `Downloads/Profile/CX743.png`. Ford lists the complete vehicle at 4,580 × 1,936 × 1,674 mm, wheelbase 2,716 mm. These guide proportions; the stripped visual shell does not include the bumper envelope and is not a dimensional CAD substitute.

Frontend tests validate finite GLB geometry, hash, size and exact registry versions. Backend descriptor metadata changes with the asset; no database schema or OpenAPI changes are needed.
