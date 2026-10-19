"""Pure, ungraded IMG family aggregation. No framework or database imports."""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from app.domain.grading import orientation_of

LAYERS = ("ECOAT", "PRIMER", "BASE", "CLEAR")
MEASURES = (*LAYERS, "CALCULATED_TOTAL")
ORIENTS = ("H", "V")
RANGER_RAPTOR = frozenset(("P703 DBL RANGER", "P703 DBL RAPTOR"))


def family_of(code: str, catalogue: dict[str, dict]) -> tuple[str, str]:
    """An active catalogue model reports under its stored family.

    Owner decision 2026-10-13: every P703 variant (Ranger, Raptor, RAPCAP,
    Single CAP, Super Duty) is one P703 slot. A model missing from the
    catalogue, inactive, or without a family is never guessed: it gets its own
    explicit UNMAPPED slot. Nothing matches by name prefix.
    """
    model = catalogue.get(code)
    if model is None or not model.get("is_active") or not model.get("model_family"):
        return f"UNMAPPED:{code}", (model or {}).get("display_name") or code
    return model["model_family"], model["model_family"]


def number(value) -> Decimal | None:
    if value is None:
        return None
    try:
        found = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return found if found.is_finite() else None


def _new(plant, key, name, orient, metric, measure):
    return {
        "id": f"{plant}|{key}|{metric}|{orient}|{measure or '-'}",
        "plant_code": plant, "family_key": key, "family_name": name,
        "orient": orient, "metric": metric,
        "unit": "CF" if metric == "CF" else "micron",
        "film_measure": measure, "mean": None, "included_count": 0,
        "count_unit": "CF_READING" if metric == "CF" else "FILM_POINT" if measure == "CALCULATED_TOTAL" else "LAYER_READING",
        "availability": "NO_ELIGIBLE_READINGS", "member_models": [],
        "models": [], "colors": [], "locations": [],
        "exclusions": {"SETTING_EXCLUDED": 0, "INCOMPLETE_TOTAL": 0,
                       "UNKNOWN_ORIENTATION": 0, "INVALID_VALUE": 0,
                       "DUPLICATE_LAYER": 0},
        "_values": [], "_models": Counter(), "_colors": Counter(),
        "_locations": Counter(), "_members": {},
    }


def aggregate(cf_rows: list[dict], film_rows: list[dict], catalogue: dict[str, dict], measure: str,
              group: str = "family") -> list[dict]:
    """Pool facts; point total uses exactly one valid value per layer.

    `group="color"` slots by plant x canonical colour instead of family (IMG
    Color); every other rule -- eligibility, point identity, exclusions -- is
    the same code path.
    """
    slots = {}
    point_rows = defaultdict(list)

    def slot(row, metric, orient, selected):
        if group == "color":
            key = name = row["color"] or "(unknown)"
        else:
            key, name = family_of(row["model"], catalogue)
        identity = (row["plant"], key, metric, orient, selected)
        if identity not in slots:
            slots[identity] = _new(row["plant"], key, name, orient, metric, selected)
        found = slots[identity]
        meta = catalogue.get(row["model"], {})
        found["_members"][row["model"]] = meta.get("display_name") or row["model"]
        return found

    def include(found, row, value):
        found["_values"].append(value)
        found["_models"][row["model"]] += 1
        found["_colors"][row["color"] or "(unknown)"] += 1
        found["_locations"][row["location"] or "(unknown)"] += 1

    for row in cf_rows:
        axis = orientation_of(row.get("tolerance_group"))
        value = number(row.get("value"))
        counted = row.get("counted") is not False
        for orient in ORIENTS:
            found = slot(row, "CF", orient, None)
            # Same disclosure rule as Film: a point switched off or retired is
            # a setting exclusion, never also an unknown-orientation one.
            if not counted:
                if axis == orient or axis is None:
                    found["exclusions"]["SETTING_EXCLUDED"] += 1
            elif axis is None:
                found["exclusions"]["UNKNOWN_ORIENTATION"] += 1
            elif axis == orient:
                if value is None:
                    found["exclusions"]["INVALID_VALUE"] += 1
                else:
                    include(found, row, value)

    # A point observation is the canonical logical vehicle and point, with
    # measured date and model included as defensive boundaries. No source
    # row or point number alone can pair different observations.
    for row in film_rows:
        point_rows[(row["plant"], row["model"], row["logical_vehicle_id"],
                    row["measured_date"], row["location"])].append(row)

    for rows in point_rows.values():
        first = rows[0]
        axis = first.get("orientation")
        counted = first.get("counted") is not False
        selected = [r for r in rows if r["layer_code"] == measure] if measure != "CALCULATED_TOTAL" else rows
        # Each exclusion is a measured point for Total and a layer reading
        # for a selected individual layer.
        for orient in ORIENTS:
            found = slot(first, "FILM", orient, measure)
            if not counted:
                if axis == orient or axis not in ORIENTS:
                    found["exclusions"]["SETTING_EXCLUDED"] += 1 if measure == "CALCULATED_TOTAL" else len(selected)
                continue
            if axis not in ORIENTS:
                found["exclusions"]["UNKNOWN_ORIENTATION"] += 1 if measure == "CALCULATED_TOTAL" else len(selected)
                continue
            if axis != orient:
                continue
            if measure != "CALCULATED_TOTAL":
                for row in selected:
                    value = number(row.get("value"))
                    if value is None:
                        found["exclusions"]["INVALID_VALUE"] += 1
                    else:
                        include(found, row, value)
                continue
            by_layer = defaultdict(list)
            for row in rows:
                if row["layer_code"] in LAYERS:
                    by_layer[row["layer_code"]].append(number(row.get("value")))
            if any(len(by_layer[layer]) > 1 for layer in LAYERS):
                found["exclusions"]["DUPLICATE_LAYER"] += 1
            elif any(len(by_layer[layer]) == 1 and by_layer[layer][0] is None for layer in LAYERS):
                found["exclusions"]["INVALID_VALUE"] += 1
            elif any(not by_layer[layer] for layer in LAYERS):
                found["exclusions"]["INCOMPLETE_TOTAL"] += 1
            else:
                include(found, first, sum((by_layer[layer][0] for layer in LAYERS), Decimal(0)))

    result = []
    for found in slots.values():
        values = found.pop("_values")
        found["included_count"] = len(values)
        if values:
            found["mean"] = sum(values, Decimal(0)) / len(values)
            found["availability"] = "AVAILABLE"
        elif any(found["exclusions"].values()):
            found["availability"] = "EXCLUDED_OR_INCOMPLETE"
        members = found.pop("_members")
        found["member_models"] = [
            {"model_code": code, "model_name": name}
            for code, name in sorted(members.items())
        ]
        for field, counter in (("models", "_models"), ("colors", "_colors"), ("locations", "_locations")):
            counts = found.pop(counter)
            found[field] = [{"key": key, "included_count": n} for key, n in sorted(counts.items())]
        result.append(found)
    # Plant order is applied by the service (repository constant): no plant literal here.
    result.sort(key=lambda s: (s["family_key"], s["metric"], s["orient"]))
    return result
