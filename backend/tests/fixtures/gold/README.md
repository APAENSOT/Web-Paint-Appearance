# Gold reference fixtures

Read-only inputs for the backend tests. They hold **labels only**: measuring-point
names, order and orientation per plant and model, the owner's sign-off record for
the SAP/FVL P703 checkpoint map, and per-model point counts. No measurement value,
VIN or Job Number is in any of them.

| File | Read by |
|---|---|
| `AAT-P703-film-points.json`, `LEFTOVER-film-points.json`, `FTM-QS-film-points.json` | `test_t48`, `test_t54`, `test_t55`, `test_t57` |
| `P703-DBL-film-location-map.json` | `test_t47` |
| `WS-plant-gold.json` | `test_t58` |
| `G1-P703-OWNER-PROOF.md` | `test_t30`, `test_t31` |
| `T83-gold-counts-before-0030.txt` | `test_t83` |

They were produced from the plant workbooks in the original working repository and
are frozen here; the tests compare the restored database against them.
