"""Monthly inspection reads; point means reuse Overview status rules, with no writes."""
from collections import Counter, defaultdict
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
from app.domain.boxplot import box_stats
from app.domain.history import month_date_bounds
from app.repositories import comparison as repo, monthly_detail as refs
from app.services import comparison, color_appearance, point_profiles
from app.services import history as history_service
from app.services import overview as ws_overview, film_overview
from app.repositories import overview as overview_repo, color_appearance as color_repo, film_standards as film_standards_repo, filmthickness as film_repo
from app.domain.film_standards import effective_rule
from app.domain.film_overview import line_labels
from app.domain.grading import film_box_status, status_of
from app.services.history import HistoryError, resolve_plant


def _scope(conn, plant_code, plant_scope):
    plant = resolve_plant(conn, plant_code)
    if plant_scope is not None and plant['plant_code'] not in plant_scope:
        raise HistoryError(403, 'This plant is outside your data scope.')
    return plant


def _month(value):
    try:
        return month_date_bounds(value)
    except ValueError as exc:
        raise HistoryError(422, str(exc)) from exc


def _domain(domain):
    return 'WAVESCAN' if domain == 'wavescan' else 'FILMTHICKNESS'


def _reference_context(conn, plant, domain, model, color, metric):
    catalogue = repo.ws_catalogue(conn, plant, model) if domain == 'wavescan' else film_repo.point_setting(conn, plant, model)
    key = 'code' if domain == 'wavescan' else 'point_code'
    context = dict(domain=domain, metric=metric, key=key, catalogue={p[key]: p for p in catalogue})
    if domain == 'wavescan':
        family = next((c['family_name'] for c in color_repo.plant_colors(conn,plant) if c['color_name']==color),None)
        context['family'] = family
        context['color_standards'] = {(r['color_name'],r['orient']):(Decimal(r['ford']),Decimal(r['min'])) for r in overview_repo.color_standards(conn,plant,[color])}
        context['family_standards'] = {(r['family_name'],r['orient']):(Decimal(r['ford']),Decimal(r['min'])) for r in overview_repo.family_standards(conn,plant,[family] if family else [])}
    else:
        context['rules'] = film_standards_repo.latest(conn,plant)['rules']
    return context


def _point_standard(context, color, point_key, mean=None):
    domain, metric = context['domain'], context['metric']
    point = context['catalogue'].get(point_key)
    orientation = comparison._orientation(point['orientation']) if domain == 'wavescan' and point else point.get('orientation') if point else None
    if orientation not in ('H','V'):
        orientation = None
    result = dict(orientation=orientation,standard_scope='NONE',reference_lines=[],status=None)
    if not orientation:
        return result
    if domain == 'wavescan':
        if metric != 'cf':
            return result
        ford, minimum = ws_overview._targets(color,context['family'],'Horizontal' if orientation=='H' else 'Vertical',context['color_standards'],context['family_standards'])
        if ford is not None:
            result['standard_scope']='COLOR' if (color,orientation) in context['color_standards'] else 'FAMILY'
            result['reference_lines']=[dict(label='Standard',value=ford,kind='standard'),dict(label='Minimum',value=minimum,kind='minimum')]
            result['status'] = status_of(mean, ford, minimum) if mean is not None else None
    else:
        rule = effective_rule(context['rules'],layer_code=metric.upper(),color_name=color,orient=orientation)
        result['standard_scope']=film_overview._scope(rule)
        lo,hi,target = (film_overview._line(rule,k) for k in ('lo','hi','target'))
        labels = line_labels(metric.upper(),lo,hi,target)
        result['reference_lines']=[dict(label=labels[f'{key}_label'],value=value,kind=kind) for key,value,kind in [('lo',lo,'minimum'),('hi',hi,'maximum'),('target',target,'target')] if value is not None and labels[f'{key}_label'] is not None]
        result['status'] = film_box_status(metric.upper(), mean, lo, hi, target) if mean is not None else None
    return result


def reference_lines(conn, plant, domain, model, color, metric, point_key):
    result = _point_standard(_reference_context(conn, plant, domain, model, color, metric), color, point_key)
    result.pop('status')
    return result


def _selected(conn, code, plant_scope, domain, bounds, model, color, active):
    api_domain = _domain(domain)
    if not active:
        vehicles = []
    elif domain == 'wavescan':
        vehicles = history_service._vehicles(conn, code, plant_scope=plant_scope, bounds=bounds, model=model, color=color)
    else:
        vehicles = repo.vehicles(conn, code, plant_scope, api_domain, bounds=bounds, model=model)
    selected = [(v, comparison._candidate(v, api_domain)) for v in vehicles]
    selected = [(v, c) for v, c in selected if c['color'] == color]
    selected.sort(key=lambda pair: (pair[1]['measured_date'], getattr(pair[0], 'first_source_row', 0), pair[1]['vehicle_id']))
    return api_domain, selected


def profiles(conn, plant_code, *, plant_scope, domain, month=None):
    plant = _scope(conn, plant_code, plant_scope)
    code, active = plant['plant_code'], plant['is_active']
    available = repo.months(conn, code, plant_scope, _domain(domain)) if active else []
    selected = month or next(iter(available), None)
    bounds = _month(selected) if selected else None
    colors = {c['color_name']: c for c in color_appearance.read(conn, code)['items']}
    models = set(refs.offered_models(conn, code))
    candidates = repo.vehicles(conn, code, plant_scope, _domain(domain), bounds=bounds) if active and bounds else []
    observed = Counter((comparison._candidate(v, _domain(domain))['model'], comparison._candidate(v, _domain(domain))['color']) for v in candidates)
    pairs = {(m, c) for m in models for c in colors} | {pair for pair in observed if all(pair)}
    items = []
    for model, color in sorted(pairs):
        items.append(dict(profile_id=hashlib.sha256(json.dumps([code, domain, model, color], ensure_ascii=False).encode()).hexdigest(),
                          domain=domain, model_code=model, color_name=color,
                          family_name=colors.get(color, {}).get('family_name'),
                          is_offered=model in models and color in colors, sample_count=observed[(model, color)]))
    return dict(plant_code=code, domain=domain, month=selected, available_months=available, items=items)


def points(conn, plant_code, *, plant_scope, domain, month, model, color, metric, point_key):
    plant = _scope(conn, plant_code, plant_scope)
    code, api_domain = plant['plant_code'], _domain(domain)
    if metric not in (comparison.WS_METRICS if domain == 'wavescan' else comparison.FILM_METRICS):
        raise HistoryError(422, 'Metric does not belong to this measurement domain.')
    bounds = _month(month)
    profile = point_profiles.read(conn, code, model, domain)
    if not any(p['point_key'] == point_key for p in profile['points']):
        raise HistoryError(404, 'Select an exact live Standard point for this model and domain.')
    api_domain, selected = _selected(conn, code, plant_scope, domain, bounds, model, color, plant['is_active'])
    live_codes = {p['point_key'] for p in profile['points']}
    samples, values, unaligned = [], [], 0
    for vehicle, c in selected:
        readings = []
        if domain == 'wavescan':
            for row in repo.ws_points(conn, code, plant_scope, vehicle):
                if row[metric] is None:
                    continue
                if row['checkzone'] not in live_codes:
                    unaligned += 1
                if row['checkzone'] != point_key:
                    continue
                readings.append(dict(value=row[metric], **{key: row[key] for key in
                    ('measurement_id', 'panel_label', 'source_file', 'source_sheet', 'source_row', 'load_id', 'src_zone_text')}))
        else:
            for row in repo.film_grid(conn, code, model, c['vehicle_id']):
                if row['point_code'] not in live_codes and row['layers'][metric] is not None:
                    unaligned += 1
                if row['point_code'] == point_key and row['layers'][metric] is not None:
                    readings.append(dict(value=row['layers'][metric], **{key: row[key] for key in ('load_id', 'source_row', 'src_location_text')}))
        values.extend(Decimal(r['value']) for r in readings)
        samples.append(dict(vehicle_id=c['vehicle_id'], measured_date=c['measured_date'], serial_no=c['serial_no'],
                            car_label=getattr(vehicle, 'car_label', None), job_nos=c.get('job_nos'), readings=readings))
    stats = asdict(box_stats(values)) if values else None
    if stats:
        stats.pop('n')
    standard = _point_standard(_reference_context(conn,code,domain,model,color,metric), color, point_key,
                               stats['mean'] if stats else None)
    return dict(plant_code=code, domain=domain, month=month, model_code=model, color_name=color,
                metric=metric, unit='µm' if domain == 'film' else 'index', point_key=point_key,
                sample_count=len(samples), checked_sample_count=sum(bool(s['readings']) for s in samples),
                reading_count=len(values), box=stats, status=standard.pop('status'), samples=samples, unaligned_reading_count=unaligned,
                active_data_source=comparison._source(api_domain),
                **standard)


def point_statuses(conn, plant_code, *, plant_scope, domain, month, model, color, metric):
    plant = _scope(conn, plant_code, plant_scope)
    code = plant['plant_code']
    if metric not in (comparison.WS_METRICS if domain == 'wavescan' else comparison.FILM_METRICS):
        raise HistoryError(422, 'Metric does not belong to this measurement domain.')
    bounds = _month(month)
    profile = point_profiles.read(conn, code, model, domain)
    live = [p['point_key'] for p in profile['points']]
    live_codes = set(live)
    api_domain, selected = _selected(conn, code, plant_scope, domain, bounds, model, color, plant['is_active'])
    values = defaultdict(list)
    for vehicle, candidate in selected:
        if domain == 'wavescan':
            for row in repo.ws_points(conn, code, plant_scope, vehicle):
                if row['checkzone'] in live_codes and row[metric] is not None:
                    values[row['checkzone']].append(Decimal(row[metric]))
        else:
            for row in repo.film_grid(conn, code, model, candidate['vehicle_id']):
                value = row['layers'][metric]
                if row['point_code'] in live_codes and value is not None:
                    values[row['point_code']].append(Decimal(value))
    context = _reference_context(conn, code, domain, model, color, metric)
    items = []
    for point_key in live:
        point_values = values[point_key]
        mean = box_stats(point_values).mean if point_values else None
        standard = _point_standard(context, color, point_key, mean)
        items.append(dict(point_key=point_key, mean=mean, reading_count=len(point_values), status=standard['status']))
    return dict(plant_code=code, domain=domain, month=month, model_code=model, color_name=color,
                metric=metric, unit='µm' if domain == 'film' else 'index', items=items,
                active_data_source=comparison._source(api_domain))

