"""Monthly Detail uses full active samples and the existing vehicle membership."""
import pytest
from decimal import Decimal
from sqlalchemy import text
from tests.test_t79_comparison import data, MODEL, PRECISE  # noqa: F401


def get(data, path, domain='wavescan', **query):
    return data['client'].get(f"/api/v1/plants/{data['plant']}/monthly-detail/{path}",
                              params={'domain': domain, **query})


@pytest.mark.parametrize('domain', ['wavescan', 'film'])
def test_gallery_measured_month_and_exact_combinations(data, domain):
    response = get(data, 'profiles', domain)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['month'] == '2002-07'
    assert body['available_months'] == ['2002-07', '2002-06']
    item = next(p for p in body['items'] if p['model_code'] == MODEL and p['color_name'] == 'Arctic White')
    assert item['sample_count'] == 3
    assert len(item['profile_id']) > 0
    assert item['domain'] == domain
    empty = get(data, 'profiles', domain, month='2002-08').json()
    assert all(p['sample_count'] == 0 for p in empty['items'])


def test_point_full_sample_precision_duplicates_labels_and_missing(data):
    query = dict(month='2002-07', model=MODEL, color='Arctic White', metric='cf', point_key='1HOOD')
    response = get(data, 'points', **query)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['sample_count'] == 3
    assert body['checked_sample_count'] == 3
    assert body['reading_count'] == 6  # repeated nonduplicate checkzones are distinct readings
    assert Decimal(body['box']['q1']) == Decimal(PRECISE)
    assert body['samples'][0]['readings'][0]['value'] == PRECISE
    assert len(body['samples']) == 3
    assert sum(len(s['readings']) for s in body['samples']) == 6
    assert len({r['measurement_id'] for s in body['samples'] for r in s['readings']}) == 6
    assert [s['measured_date'] for s in body['samples']] == sorted(s['measured_date'] for s in body['samples'])
    assert body['unaligned_reading_count'] == 3
    missing = get(data, 'points', **{**query, 'metric': 'doi'}).json()
    assert missing['box'] is None and missing['reading_count'] == 0
    assert len(missing['samples']) == 3 and all(not s['readings'] for s in missing['samples'])


def test_point_status_feed_matches_exact_point_mean_without_client_grading(data):
    query = dict(month='2002-07', model=MODEL, color='Arctic White', metric='cf')
    response = get(data, 'point-statuses', **query)
    assert response.status_code == 200, response.text
    body = response.json()
    point = next(item for item in body['items'] if item['point_key'] == '1HOOD')
    exact = get(data, 'points', **query, point_key='1HOOD').json()
    assert point['mean'] == exact['box']['mean']
    assert point['reading_count'] == exact['reading_count'] == 6
    assert point['status'] == exact['status']
    assert [item['point_key'] for item in body['items']][:2] == ['1HOOD', '2HOOD']


def test_point_mean_status_uses_overview_rules_for_wavescan_and_film():
    from app.services.monthly_detail import _point_standard
    wavescan = {
        'domain': 'wavescan', 'metric': 'cf',
        'catalogue': {'P': {'orientation': 'H'}}, 'family': 'Light Solids',
        'color_standards': {('Arctic White', 'H'): (Decimal('65'), Decimal('55'))},
        'family_standards': {},
    }
    assert _point_standard(wavescan, 'Arctic White', 'P', Decimal('54'))['status'] == 'FAIL'
    assert _point_standard(wavescan, 'Arctic White', 'P', Decimal('60'))['status'] == 'WARNING'
    assert _point_standard(wavescan, 'Arctic White', 'P', Decimal('65'))['status'] == 'PASS'

    film = {
        'domain': 'film', 'metric': 'base',
        'catalogue': {'P': {'orientation': 'V'}},
        'rules': [{'created_at': __import__('datetime').datetime(2026, 10, 14), 'id': 1,
                   'layer_code': 'BASE', 'orient': 'V', 'color_name': None,
                   'lo': Decimal('10'), 'hi': Decimal('20'), 'target': None}],
    }
    assert _point_standard(film, 'Arctic White', 'P', Decimal('9'))['status'] == 'FAIL'
    assert _point_standard(film, 'Arctic White', 'P', Decimal('15'))['status'] == 'PASS'
    assert _point_standard(film, 'Arctic White', 'P', Decimal('21'))['status'] == 'OVER'


@pytest.mark.parametrize('domain,metric,key', [('wavescan','cf','1HOOD'), ('film','clear','001HOOD')])
def test_status_feed_uses_same_membership_and_empty_semantics_as_point_chart(data,domain,metric,key):
    query = dict(month='2002-07', model=MODEL, color='Arctic White', metric=metric)
    response = get(data, 'point-statuses', domain, **query)
    assert response.status_code == 200, response.text
    items = {p['point_key']: p for p in response.json()['items']}
    exact = get(data, 'points', domain, **query, point_key=key).json()
    assert items[key]['reading_count'] == exact['reading_count']
    assert items[key]['mean'] == exact['box']['mean']
    assert items[key]['status'] == exact['status']
    empty = get(data, 'point-statuses', domain, **{**query, 'month':'2002-08'}).json()
    assert all(p['mean'] is None and p['status'] is None and p['reading_count']==0 for p in empty['items'])


def test_film_uses_earliest_whole_point_and_domain_membership(data):
    comparison = data['client'].get(f"/api/v1/plants/{data['plant']}/comparison/points", params={
        'domain': 'FILMTHICKNESS', 'model': MODEL, 'metric': 'clear', 'vehicle_id': data['film']['newer']}).json()
    point = next(p for p in comparison['locations'] if p['cells'][0]['readings'])
    response = get(data, 'points', 'film', month='2002-07', model=MODEL, color='Arctic White',
                   metric='clear', point_key=point['code'])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['sample_count'] == 3
    assert all(len(s['readings']) <= 1 for s in body['samples'])
    assert body['active_data_source'] == 'filmthickness_active'
    assert body['unit'] == 'µm'


@pytest.mark.parametrize('query', [dict(metric='clear'), dict(month='bad'), dict(point_key='not-a-point')])
def test_invalid_month_domain_metric_or_point_is_refused(data, query):
    response = get(data, 'points', **{**dict(month='2002-07', model=MODEL, color='Arctic White',
                                            metric='cf', point_key='1HOOD'), **query})
    assert response.status_code in (404, 422)


def test_full_point_sample_is_not_limited_to_comparisons_eight_vehicles(data):
    conn=data['conn']
    conn.execute(text('RESET ROLE'))
    load=conn.execute(text("SELECT min(load_id) FROM wavescan WHERE plant=:p AND measured_date='2002-07-03'"),{'p':data['plant']}).scalar_one()
    for i in range(10):
        conn.execute(text("INSERT INTO wavescan (measured_date,plant,model,color,serial_no,checkzone,tolerance_group,cf,load_id,source_sheet,source_row) "
                          "VALUES ('2002-07-03',:p,:m,'Arctic White',:serial,'1HOOD','Horizontal',0,:load,'Synthetic',:row)"),
                     {'p':data['plant'],'m':MODEL,'serial':f'Monthly-{i}','load':load,'row':100+i})
    conn.execute(text('SET LOCAL ROLE app_rw'))
    body=get(data,'points',month='2002-07',model=MODEL,color='Arctic White',metric='cf',point_key='1HOOD').json()
    assert body['sample_count']==13 and body['checked_sample_count']==13
    assert body['reading_count']==16 and body['box']['box_min']=='0'
    assert len(body['samples'])==13


def test_existing_same_day_car_labels_reach_monthly_samples(data):
    conn=data['conn']; conn.execute(text('RESET ROLE'))
    load=conn.execute(text("SELECT min(load_id) FROM wavescan WHERE plant=:p AND measured_date='2002-07-03'"),{'p':data['plant']}).scalar_one()
    for i in range(2):
        conn.execute(text("INSERT INTO wavescan (measured_date,plant,model,color,serial_no,car_key,checkzone,tolerance_group,cf,load_id,source_sheet,source_row) "
                          "VALUES ('2002-07-03',:p,:m,'Arctic White',NULL,:car,'1HOOD','Horizontal',10,:load,'Synthetic',:row)"),
                     {'p':data['plant'],'m':MODEL,'car':f'{i+1:016x}','load':load,'row':95+i})
    conn.execute(text('SET LOCAL ROLE app_rw'))
    body=get(data,'points',month='2002-07',model=MODEL,color='Arctic White',metric='cf',point_key='1HOOD').json()
    labels={s['car_label'] for s in body['samples'] if s['car_label']}
    assert labels=={'car 1 of 2 that day · from row 95','car 2 of 2 that day · from row 96'}


def test_film_retired_readings_are_counted_as_excluded_not_mapped(data):
    conn=data['conn']; conn.execute(text('RESET ROLE'))
    conn.execute(text("UPDATE ref_plant_film_point SET retired_at=now(),retired_reason='transactional test' "
                      "WHERE plant_code=:p AND model_code=:m AND point_code='001HOOD'"),{'p':data['plant'],'m':MODEL})
    conn.execute(text('SET LOCAL ROLE app_rw'))
    body=get(data,'points','film',month='2002-07',model=MODEL,color='Arctic White',metric='clear',point_key='002HOOD').json()
    assert body['unaligned_reading_count']==3
    assert body['reading_count']==0 and body['box'] is None


def test_point_reference_lines_reuse_cf_color_override_and_do_not_apply_to_doi(data, monkeypatch):
    from app.services import monthly_detail
    from app.repositories import overview, color_appearance
    monkeypatch.setattr(overview,'color_standards',lambda *a:[{'color_name':'Arctic White','orient':'H','ford':Decimal('65.25'),'min':Decimal('55.125')}])
    monkeypatch.setattr(overview,'family_standards',lambda *a:[{'family_name':'Light Solids','orient':'H','ford':Decimal('70'),'min':Decimal('60')}])
    monkeypatch.setattr(color_appearance,'plant_colors',lambda *a:[{'color_name':'Arctic White','family_name':'Light Solids'}])
    ref=monthly_detail.reference_lines(data['conn'],data['plant'],'wavescan',MODEL,'Arctic White','cf','1HOOD')
    assert ref['standard_scope']=='COLOR'
    assert [(l['label'],l['value']) for l in ref['reference_lines']]==[('Standard',Decimal('65.25')),('Minimum',Decimal('55.125'))]
    assert monthly_detail.reference_lines(data['conn'],data['plant'],'wavescan',MODEL,'Arctic White','doi','1HOOD')['reference_lines']==[]


def test_film_point_reference_lines_preserve_clear_semantics_and_orientation(data,monkeypatch):
    from app.services import monthly_detail
    from app.repositories import film_standards
    monkeypatch.setattr(film_standards,'latest',lambda *a:{'rules':[{'created_at':__import__('datetime').datetime(2026,10,14),'id':1,'layer_code':'CLEAR','orient':'H','color_name':None,'lo':Decimal('20.5'),'hi':None,'target':Decimal('35.25')}]})
    ref=monthly_detail.reference_lines(data['conn'],data['plant'],'film',MODEL,'Arctic White','clear','001HOOD')
    assert ref['orientation']=='H' and ref['standard_scope']=='PLANT'
    assert [(l['label'],l['value']) for l in ref['reference_lines']]==[('No point below',Decimal('20.5')),('Minimum requirement',Decimal('35.25'))]


