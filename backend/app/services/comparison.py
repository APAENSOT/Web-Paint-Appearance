"""T79 Comparison use cases. No writes, workbook reads, or grading."""
import re
from collections import defaultdict
from decimal import Decimal
from app.domain.boxplot import box_stats
from app.domain.film_overview import color_sequence
from app.domain.film_standards import effective_rule
from app.repositories import film_standards as standards_repo
from app.services import overview as ws_overview, film_overview

from dataclasses import asdict

from app.domain.history import month_date_bounds, week_of
from app.repositories import comparison as repo
from app.repositories.measurements import ACTIVE_VIEW
from app.services.filmthickness import _complete
from app.services.history import HistoryError, resolve_plant

WS_METRICS = frozenset(("lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we", "b"))
FILM_METRICS = frozenset(("ecoat", "primer", "base", "clear"))


def _source(domain):
    return "v_wavescan_active" if domain == "WAVESCAN" else "filmthickness_active"


def _candidate(vehicle, domain):
    if domain == "WAVESCAN":
        result = asdict(vehicle)
        result.pop("row_count")
        result.pop("car_key")  # RO16: in the id, not in the response
        result.pop("car_label", None)  # D-RO17-17: History and the review only
        result.pop("first_source_row", None)  # RO17-FIX: an order key only
        result["incomplete"] = result.pop("incomplete_set")
    else:
        v = _complete(vehicle)
        result = {key: v[key] for key in ("measured_date", "model", "color", "serial_no",
                  "identity_complete", "expected_point_count", "incomplete", "job_nos", "load_ids", "source_files",
                  "date_is_month_only")}
        result.update(vehicle_id=v["logical_vehicle_id"], point_count=v["mapped_point_count"],
                      week=week_of(v["measured_date"], v["date_is_month_only"]))
    return {**result, "domain": domain}


def vehicles(conn, plant_code, *, plant_scope, domain, months, model, colors, periods, q, limit, offset):
    plant = resolve_plant(conn, plant_code)
    code = plant["plant_code"]
    available = repo.months(conn, code, plant_scope, domain) if plant["is_active"] else []
    default = available[0] if available else None
    selected = list(dict.fromkeys(months)) if months else ([default] if default else [])
    try:
        bounds = [month_date_bounds(m) for m in selected]
    except ValueError as exc:
        raise HistoryError(422, str(exc)) from exc
    for period in periods or []:
        if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])-W[1-5]", period) or period[:7] not in selected:
            raise HistoryError(422, "period must be YYYY-MM-Wn (1..5) in an effective month")
    opts = sorted({m for b in bounds for m in repo.models(conn, code, plant_scope, domain, b)}) if plant["is_active"] else []
    if available and model is not None and model not in opts:
        raise HistoryError(422, "model must be offered in at least one effective month")
    candidates = [_candidate(v, domain) for b in bounds
                  for v in repo.vehicles(conn, code, plant_scope, domain, bounds=b, model=model)] if model and model in opts else []
    color_opts = sorted({v["color"] for v in candidates if v["color"] is not None})
    weeks = sorted({(v["measured_date"].strftime("%Y-%m"), v["week"]) for v in candidates}, reverse=True)
    search = (q or "").strip().casefold()
    found = [v for v in candidates
             if (not colors or v["color"] in colors)
             and (not periods or f"{v['measured_date']:%Y-%m}-W{v['week']}" in periods)
             and (not search or any(search in value.casefold() for value in
                  [v["serial_no"] or "", *(v.get("job_nos") or [])]))]
    def order(v):
        identity = v["serial_no"] or next(iter(v.get("job_nos") or []), None)
        return (-v["measured_date"].toordinal(), identity is None, identity or "", v["vehicle_id"])
    found.sort(key=order)
    items = found[offset:offset + limit]
    return {"plant_code": code, "plant_is_active": bool(plant["is_active"]), "domain": domain,
            "default_month": default, "selected_months": selected, "available_months": available,
            "model_options": opts, "color_options": color_opts,
            "week_options": [{"month": m, "week": w} for m, w in weeks], "items": items,
            "page": {"limit": limit, "offset": offset, "total": len(found), "returned": len(items)},
            "active_data_source": _source(domain)}


def points(conn, plant_code, *, plant_scope, domain, model, metric, vehicle_ids):
    if metric not in (WS_METRICS if domain == "WAVESCAN" else FILM_METRICS):
        raise HistoryError(422, "metric does not belong to the selected domain")
    if not 1 <= len(vehicle_ids) <= 8 or len(set(vehicle_ids)) != len(vehicle_ids):
        raise HistoryError(422, "vehicle_id requires 1..8 distinct IDs in caller order")
    plant = resolve_plant(conn, plant_code)
    code = plant["plant_code"]
    found = repo.vehicles(conn, code, plant_scope, domain, model=model) if plant["is_active"] else []
    by_id = {(_candidate(v, domain)["vehicle_id"]): v for v in found}
    if any(vid not in by_id for vid in vehicle_ids):
        raise HistoryError(404, "A requested vehicle has no active facts for this plant, domain and model")
    columns = [_candidate(by_id[vid], domain) for vid in vehicle_ids]
    unaligned = []
    readings = {}
    if domain == "WAVESCAN":
        catalogue = repo.ws_catalogue(conn, code, model)
        codes = {p["code"] for p in catalogue}
        for vid in vehicle_ids:
            for row in sorted(repo.ws_points(conn, code, plant_scope, by_id[vid]), key=lambda r: r["measurement_id"]):
                if row[metric] is None:
                    continue
                reading = {key: row[key] for key in ("measurement_id", "panel_label", "source_file",
                           "source_sheet", "source_row", "load_id", "src_zone_text")}
                reading["value"] = row[metric]
                if row["checkzone"] in codes:
                    readings.setdefault((vid, row["checkzone"]), []).append(reading)
                else:
                    unaligned.append({"vehicle_id": vid, "checkzone": row["checkzone"], "reading": reading})
        # T114 (D-114-4): a retired point's readings stay here, tagged.
        retired = repo.ws_retired_codes(conn, code, model)
        for item in unaligned:
            item["retired"] = item["checkzone"] in retired
        unaligned.sort(key=lambda p: (p["checkzone"], p["reading"]["measurement_id"]))
    else:
        grids = {vid: repo.film_grid(conn, code, model, vid) for vid in vehicle_ids}
        catalogue = [{"point_no": p["point_no"], "code": p["point_code"], "orientation": p["orientation"]}
                     for p in grids[vehicle_ids[0]]]
        for vid, grid in grids.items():
            for row in grid:
                if row["layers"][metric] is not None:
                    readings[(vid, row["point_code"])] = [{"value": row["layers"][metric],
                        **{key: row[key] for key in ("src_location_text", "load_id", "source_row")}}]
    locations = [{**p, "cells": [{"vehicle_id": vid,
                  "missing": not readings.get((vid, p["code"])),
                  "readings": readings.get((vid, p["code"]), [])} for vid in vehicle_ids]} for p in catalogue]
    return {"plant_code": code, "domain": domain, "model": model, "metric": metric, "columns": columns,
            "locations": locations, "unaligned_locations": unaligned, "active_data_source": _source(domain)}

# T81 calculated reads. Existing T79 reads remain unchanged.
PROFILE_METRICS = ('du', 'wa', 'wb', 'wc', 'wd', 'we')
TRACE_FIELDS = ('measurement_id', 'panel_label', 'src_zone_text', 'source_file', 'source_sheet', 'source_row', 'load_id', 'cf', *PROFILE_METRICS)


def _orientation(value):
    # Reuse Overview's proved orientation translation; never derive from code.
    return {'Horizontal': 'H', 'Vertical': 'V'}.get(ws_overview._axis(value))


def _mean(values):
    return sum(values, Decimal(0)) / Decimal(len(values)) if values else None


def _mean_summary(monthly):
    contributing = [m['month'] for m in monthly if m['mean'] is not None]
    return dict(monthly=monthly, mean=_mean([Decimal(m['mean']) for m in monthly if m['mean'] is not None]),
                contributing_months=contributing, missing_months=[m['month'] for m in monthly if m['mean'] is None],
                contributing_month_count=len(contributing))


def _color_order(conn, code, domain, rows):
    meta = {}
    for row in rows:
        color = row['color']
        meta[color] = dict(color_name=color, family_order=row['display_order'],
                           family_code=row.get('family_code'), family_name=row.get('family_name'))
    if domain == 'WAVESCAN':
        return sorted(meta, key=lambda c: (meta[c]['family_order'] if meta[c]['family_order'] is not None else 99, c))
    rules = standards_repo.latest(conn, code)['rules']
    sequence = color_sequence(meta.values(), {c: {o: effective_rule(rules, layer_code='BASE', color_name=c, orient=o)
                                             for o in ('H', 'V')} for c in meta})
    return [c['color_name'] for c in sequence]


def monthly_preview(conn, plant_code, *, plant_scope, domain, model, metric, months):
    if metric not in ({'cf'} if domain == 'WAVESCAN' else FILM_METRICS):
        raise HistoryError(422, 'metric does not belong to the selected domain')
    if not months or len(set(months)) != len(months):
        raise HistoryError(422, 'months must be nonempty and distinct')
    try:
        bounds = [month_date_bounds(m) for m in months]
    except ValueError as exc:
        raise HistoryError(422, str(exc)) from exc
    plant = resolve_plant(conn, plant_code)
    code = plant['plant_code']
    if plant['is_active'] and model not in repo.monthly_models(conn, code, plant_scope, domain):
        raise HistoryError(422, 'model must have active facts at this plant/domain')
    result = dict(plant_code=code, domain=domain, model=model, metric=metric, months=months,
                  month_boxes=[], group_means=[], profiles=[], unaligned_reading_count=[], active_data_source=_source(domain))
    rows_by_month, boxes_by_month = {}, {}
    for month, bound in zip(months, bounds):
        if not plant['is_active']:
            rows, boxes = [], []
        elif domain == 'WAVESCAN':
            rows = repo.ws_month_readings(conn, code, plant_scope, model, bound)
            # T114 (D-114-3): Comparison keeps every reading, counted or not.
            boxes = ws_overview.overview(conn, code, plant_scope=plant_scope, month=month, models=[model], colors=None,
                                         view=ACTIVE_VIEW)['boxes']
        else:
            rows = repo.film_month_readings(conn, code, plant_scope, model, bound)
            boxes = [b for b in film_overview.overview(conn, code, plant_scope=plant_scope, month=month, models=[model], colors=None)['boxes']
                     if b['layer_code'] == metric.upper()]
        rows_by_month[month] = rows
        boxes_by_month[month] = {(b['color_name'], _orientation(b['orient'])): b for b in boxes}
        result['month_boxes'].append(dict(month=month, wavescan_boxes=boxes if domain == 'WAVESCAN' else [],
                                         film_boxes=boxes if domain == 'FILMTHICKNESS' else []))
    all_rows = [r for rows in rows_by_month.values() for r in rows]
    colors = _color_order(conn, code, domain, all_rows) if all_rows else []
    for color in colors:
        for orient in ('H', 'V'):
            monthly = []
            for month in months:
                box = boxes_by_month[month].get((color, orient))
                monthly.append(dict(month=month, mean=box['mean'] if box else None, n=box['n'] if box else 0))
            result['group_means'].append(dict(color=color, orientation=orient, metric=metric,
                layer_code=None if domain == 'WAVESCAN' else metric.upper(), **_mean_summary(monthly)))
    catalogue = repo.ws_catalogue(conn, code, model) if domain == 'WAVESCAN' and plant['is_active'] else []
    codes = {p['code'] for p in catalogue}
    samples = defaultdict(list)
    for month, rows in rows_by_month.items():
        unaligned = 0
        if domain == 'WAVESCAN':
            for row in rows:
                if row['checkzone'] not in codes:
                    unaligned += 1
                    continue
                for param in PROFILE_METRICS:
                    if row[param] is not None:
                        samples[(month, row['color'], row['checkzone'], param)].append(Decimal(row[param]))
        result['unaligned_reading_count'].append(dict(month=month, n=unaligned))
    for color in colors if domain == 'WAVESCAN' else []:
        for location in catalogue:
            metrics = []
            for param in PROFILE_METRICS:
                monthly = []
                for month in months:
                    values = samples[(month, color, location['code'], param)]
                    monthly.append(dict(month=month, mean=_mean(values), n=len(values)))
                metrics.append(dict(metric=param, **_mean_summary(monthly)))
            result['profiles'].append(dict(color=color, **{k: location[k] for k in ('point_no', 'code')},
                orientation=_orientation(location['orientation']), metrics=metrics))
    return result


def vehicle_visuals(conn, plant_code, *, plant_scope, model, vehicle_ids):
    if not 1 <= len(vehicle_ids) <= 8 or len(set(vehicle_ids)) != len(vehicle_ids):
        raise HistoryError(422, 'vehicle_id requires 1..8 distinct IDs in caller order')
    plant = resolve_plant(conn, plant_code)
    code = plant['plant_code']
    found = repo.vehicles(conn, code, plant_scope, 'WAVESCAN', model=model) if plant['is_active'] else []
    by_id = {_candidate(v, 'WAVESCAN')['vehicle_id']: v for v in found}
    if any(vid not in by_id for vid in vehicle_ids):
        raise HistoryError(404, 'Every vehicle_id must have active WaveScan facts at this plant/model')
    catalogue = repo.ws_catalogue(conn, code, model)
    by_code = {p['code']: p for p in catalogue}
    visuals = []
    for vid in vehicle_ids:
        traces = defaultdict(list)
        samples = {'H': [], 'V': []}
        unaligned = []
        for row in sorted(repo.ws_points(conn, code, plant_scope, by_id[vid]), key=lambda r: r['measurement_id']):
            trace = {k: row[k] for k in TRACE_FIELDS}
            location = by_code.get(row['checkzone'])
            if location is None:
                unaligned.append(dict(checkzone=row['checkzone'], trace=trace))
                continue
            traces[row['checkzone']].append(trace)
            orient = _orientation(location['orientation'])
            if orient is not None and row['cf'] is not None:
                samples[orient].append(Decimal(row['cf']))
        boxes = []
        for orient in ('H', 'V'):
            stats = asdict(box_stats(samples[orient])) if samples[orient] else None
            if stats is not None:
                stats.pop('n')
                stats['outliers'] = list(stats['outliers'])
            boxes.append(dict(orientation=orient, n=len(samples[orient]), stats=stats))
        visuals.append(dict(vehicle_id=vid, cf_boxes=boxes,
            locations=[dict(point_no=p['point_no'], code=p['code'], orientation=_orientation(p['orientation']),
                            traces=traces[p['code']]) for p in catalogue],
            unaligned_locations=sorted(unaligned, key=lambda r: (r['checkzone'], r['trace']['measurement_id']))))
    return dict(plant_code=code, model=model, columns=[_candidate(by_id[vid], 'WAVESCAN') for vid in vehicle_ids],
                vehicles=visuals, active_data_source='v_wavescan_active')
