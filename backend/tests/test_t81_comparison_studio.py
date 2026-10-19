"""T81 API calculations, real PostgreSQL, fixture writes always rolled back."""
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import text

from app.domain.boxplot import box_stats
from app.api.deps import active_measurement_scope
from app.repositories.measurements import MeasurementFilter
from tests.test_t79_comparison import data, MODEL, OTHER_MODEL, ok  # noqa: F401


def preview(data, **changes):
    body = dict(domain="WAVESCAN", model=MODEL, metric="cf", months=["2003-06", "2003-07", "2003-08"])
    plant = changes.pop("plant", data["plant"])
    return data["client"].post(f"/api/v1/plants/{plant}/comparison/monthly-preview", json={**body, **changes})


def visuals(data, ids=None, **changes):
    plant = changes.pop("plant", data["plant"])
    return data["client"].get(f"/api/v1/plants/{plant}/comparison/vehicle-visuals",
        params=dict(model=changes.pop("model", MODEL), vehicle_id=ids or [data["ws"]["newer"]], **changes))


@pytest.fixture
def studio(data):
    c = data["conn"]
    c.execute(text("RESET ROLE"))
    for domain in ("WAVESCAN", "FILMTHICKNESS"):
        for month, count, value in ((6, 1, '40'), (7, 9, '60')):
            load = c.execute(text("INSERT INTO load_batch(source_file,source_sheet,plant_code,file_hash,raw_store_key,status,domain) "
                "VALUES ('t81.xlsx','Synthetic',:p,:hash,'unused','COMMITTED',:domain) RETURNING load_id"),
                {"p":data["plant"],"hash": uuid.uuid4().hex*2,"domain":domain}).scalar_one()
            for i in range(count):
                params = dict(p=data["plant"],m=MODEL,day=f'2003-{month:02}-03',load=load,row=i+1,value=value)
                if domain == "WAVESCAN":
                    c.execute(text("INSERT INTO wavescan(measured_date,plant,model,color,serial_no,checkzone,tolerance_group,cf,du,wa,wb,wc,wd,we,load_id,source_sheet,source_row,src_zone_text) "
                        "VALUES (:day,:p,:m,'Arctic White','T81','1HOOD','Horizontal',:value,:value,0,NULL,1.2300,2,3,:load,'Synthetic',:row,'Original hood')"),params)
                else:
                    c.execute(text("INSERT INTO filmthickness(measured_date,plant,model,color,src_location_text,point_code,layer_code,thickness,logical_vehicle_id,load_id,source_sheet,source_row) "
                        "VALUES (:day,:p,:m,'Arctic White','001HOOD','001HOOD','CLEAR',:value,:vid,:load,'Synthetic',:row)"),{**params,"vid":f't81-{month}-{i}'})
    c.execute(text("SET LOCAL ROLE app_rw"))
    return data


@pytest.mark.parametrize('domain,metric,boxkey', [('WAVESCAN','cf','wavescan_boxes'),('FILMTHICKNESS','clear','film_boxes')])
def test_equal_month_weighting_gaps_and_overview_parity(studio,domain,metric,boxkey):
    b=ok(preview(studio,domain=domain,metric=metric,months=['2003-07','2003-08','2003-06']))
    assert b['months']==['2003-07','2003-08','2003-06']
    assert [m['month'] for m in b['month_boxes']]==b['months']
    h=next(g for g in b['group_means'] if g['color']=='Arctic White' and g['orientation']=='H')
    assert h['mean']=='50' and h['contributing_month_count']==2
    assert h['contributing_months']==['2003-07','2003-06'] and h['missing_months']==['2003-08']
    assert [m['n'] for m in h['monthly']]==[9,0,1]
    v=next(g for g in b['group_means'] if g['orientation']=='V')
    assert v['mean'] is None and v['contributing_month_count']==0
    assert b['month_boxes'][1][boxkey]==[]
    path='wavescan' if domain=='WAVESCAN' else 'filmthickness'
    for mb in b['month_boxes']:
        existing=ok(studio['client'].get(f"/api/v1/plants/{studio['plant']}/{path}/overview",params={'month':mb['month'],('model' if domain=='WAVESCAN' else 'models'):MODEL}))['boxes']
        if domain=='FILMTHICKNESS':existing=[box for box in existing if box['layer_code']=='CLEAR']
        assert mb[boxkey]==existing
    one=ok(preview(studio,domain=domain,metric=metric,months=['2003-06']))
    assert one['group_means'][0]['mean']=='40'
    overlap=ok(preview(studio,domain=domain,metric=metric,months=['2003-07','2003-06']))
    assert overlap['group_means'][0]['mean']=='50'
    if domain=='FILMTHICKNESS':
        assert b['profiles']==[]
        missing=ok(preview(studio,domain=domain,metric='primer',months=['2003-06']))
        assert len(missing['group_means'])==2 and all(g['mean'] is None for g in missing['group_means'])


def test_profiles_catalogue_duplicates_zero_and_unaligned(studio):
    b=ok(preview(studio))
    profiles=b['profiles']
    assert [(p['point_no'],p['code']) for p in profiles]==sorted((p['point_no'],p['code']) for p in profiles)
    p=next(p for p in profiles if p['code']=='1HOOD')
    assert [m['metric'] for m in p['metrics']]==['du','wa','wb','wc','wd','we']
    assert p['metrics'][0]['mean']=='50' and [m['n'] for m in p['metrics'][0]['monthly']]==[1,9,0]
    assert p['metrics'][1]['mean']=='0'
    assert p['metrics'][2]['mean'] is None
    null=next(p for p in profiles if p['code']=='2HOOD')
    assert null['orientation']=='H' and all(m['mean'] is None for m in null['metrics'])
    old=ok(preview(studio,months=['2002-07']))
    assert old['unaligned_reading_count']==[{'month':'2002-07','n':4}]
    assert all(p['code']!='RRHOOD' for p in old['profiles'])


def test_vehicle_boxes_raw_traces_and_caller_order(studio):
    ids=[studio['ws']['newer'],studio['ws']['older']]
    b=ok(visuals(studio,ids))
    assert [c['vehicle_id'] for c in b['columns']]==ids
    assert [v['vehicle_id'] for v in b['vehicles']]==ids
    for v in b['vehicles']:
        assert [x['orientation'] for x in v['cf_boxes']]==['H','V']
        assert v['cf_boxes'][0]['n']==2 and v['cf_boxes'][1]=={'orientation':'V','n':0,'stats':None}
        location=next(p for p in v['locations'] if p['code']=='1HOOD')
        assert len(location['traces'])==2
        traces=location['traces']
        assert [r['measurement_id'] for r in traces]==sorted(r['measurement_id'] for r in traces)
        expected=box_stats([Decimal(t['cf']) for t in traces])
        for k,val in v['cf_boxes'][0]['stats'].items():
            assert val==([format(x,'f') for x in expected.outliers] if k=='outliers' else format(getattr(expected,k),'f'))
        # T94 (D-94-4): panel_label is the stored position (the long
        # name), never the file's own 'plant label N' spelling.
        assert all(t['du'] is None and t['panel_label'] and not t['panel_label'].startswith('plant label') and t['source_row'] and t['load_id'] for t in traces)
        assert v['unaligned_locations'][0]['checkzone']=='RRHOOD'
        assert all(p['traces']==[] for p in v['locations'] if p['code']!='1HOOD')


@pytest.mark.parametrize('changes',[{'months':[]},{'months':['2003-06','2003-06']},{'months':['2003-13']},{'months':['2003-6']},{'months':['0000-01']},{'model':OTHER_MODEL},{'metric':'clear'},{'domain':'FILMTHICKNESS','metric':'cf'},{'model':''}])
def test_invalid_monthly_request(studio,changes):
    assert preview(studio,**changes).status_code==422


def test_plants_id_errors_scope_and_read_only(studio):
    c=studio['conn']
    def counts():return [c.execute(text(f'SELECT count(*) FROM {t}')).scalar_one() for t in ('wavescan','filmthickness','load_batch','audit_event','cf_standard','film_standard')]
    before=counts()
    assert preview(studio,plant='NO-SUCH-PLANT').status_code==404
    empty=ok(preview(studio,plant=studio['empty'],model='Valid syntax'))
    assert empty['group_means']==empty['profiles']==[]
    assert all(x['wavescan_boxes']==x['film_boxes']==[] for x in empty['month_boxes'])
    assert preview(studio,plant=studio['active_empty']).status_code==422
    for ids in ([studio['ws']['newer']]*2,[f'{i:064x}' for i in range(9)],['bad']):
        assert visuals(studio,ids).status_code==422
    for ids in ([studio['film']['newer']],[studio['ws']['retired']],[studio['ws']['dup']],[studio['ws']['pending']],['0'*64]):
        assert visuals(studio,ids).status_code==404
    assert visuals(studio,plant='NO-SUCH-PLANT').status_code==404
    assert visuals(studio,plant=studio['empty']).status_code==404
    assert visuals(studio,model=OTHER_MODEL).status_code==404
    for role in ('viewer','engineer','admin'):
        studio['client'].app.state.settings.auth_dev_bypass_roles_raw=role
        assert preview(studio).status_code==visuals(studio).status_code==200
    studio['client'].app.dependency_overrides[active_measurement_scope]=lambda:MeasurementFilter(plant_scope=['FVL'])
    assert preview(studio).status_code==422 and visuals(studio).status_code==404
    studio['client'].app.dependency_overrides.pop(active_measurement_scope)
    assert counts()==before
    studio['client'].app.state.settings.auth_dev_bypass=False
    assert preview(studio).status_code==visuals(studio).status_code==401


def test_vehicle_single_many_outliers_and_raw_parameters(studio):
    c=studio['conn']
    c.execute(text('RESET ROLE'))
    load=c.execute(text("INSERT INTO load_batch(source_file,source_sheet,plant_code,file_hash,raw_store_key,status,domain) "
        "VALUES ('T81 exact.xlsx','Exact',:p,:hash,'unused','COMMITTED','WAVESCAN') RETURNING load_id"),
        {'p':studio['plant'],'hash':uuid.uuid4().hex*2}).scalar_one()
    vertical=c.execute(text("SELECT zone_code FROM ref_plant_ws_point WHERE plant_code=:p AND model_code=:m AND tolerance_group='Vertical' AND retired_at IS NULL ORDER BY point_no LIMIT 1"), {'p':studio['plant'],'m':MODEL}).scalar_one()
    for row,(zone,tol,cf) in enumerate([('1HOOD','Horizontal','0'),*[(vertical,'Vertical',v) for v in ('10','10','10','10','100')]],1):
        c.execute(text("INSERT INTO wavescan(measured_date,plant,model,color,serial_no,checkzone,tolerance_group,cf,du,wa,wb,wc,wd,we,load_id,source_sheet,source_row,src_zone_text) "
            "VALUES ('2004-01-01',:p,:m,'Arctic White','Exact',:zone,:tol,:cf,1.234567890123456789,0,NULL,2.3000,4,5,:load,'Exact',:row,'Original panel')"),
            dict(p=studio['plant'],m=MODEL,load=load,zone=zone,tol=tol,cf=cf,row=row))
    c.execute(text('SET LOCAL ROLE app_rw'))
    picker=ok(studio['client'].get(f"/api/v1/plants/{studio['plant']}/comparison/vehicles",params={'domain':'WAVESCAN','month':'2004-01','model':MODEL}))
    vid=picker['items'][0]['vehicle_id']
    v=ok(visuals(studio,[vid]))['vehicles'][0]
    h,vbox=v['cf_boxes']
    assert h['n']==1 and all(h['stats'][k]=='0' for k in ('mean','box_min','q1','median','q3','box_max','whisker_lo','whisker_hi'))
    assert vbox['n']==5 and vbox['stats']['outliers']==['100']
    assert vbox['stats']['mean']=='28'
    t=next(p for p in v['locations'] if p['code']=='1HOOD')['traces'][0]
    assert {k:t[k] for k in ('cf','du','wa','wb','wc','wd','we')}==dict(cf='0',du='1.234567890123456789',wa='0',wb=None,wc='2.3000',wd='4',we='5')
    # T94 (D-94-4): panel_label is the stored checkzone, not the file's
    # 'Original panel' spelling, which src_zone_text still keeps.
    assert {k:t[k] for k in ('source_file','source_sheet','source_row','load_id')}==dict(source_file='T81 exact.xlsx',source_sheet='Exact',source_row=1,load_id=load)
    assert t['panel_label'] != 'Original panel' and t['panel_label']
    p=ok(preview(studio,months=['2004-01']))
    groups={(g['color'],g['orientation']):g for g in p['group_means']}
    assert groups['Arctic White','H']['mean']=='0' and groups['Arctic White','V']['mean']=='28'


def test_colours_are_separate_and_unlimited_gaps(studio):
    b=ok(preview(studio,months=['2002-07']))
    assert [(g['color'],g['orientation']) for g in b['group_means']]==[('Arctic White','H'),('Arctic White','V'),('Traction Green','H'),('Traction Green','V')]
    assert [g['monthly'][0]['n'] for g in b['group_means']]==[9,0,3,0]
    months=[f'2005-{m:02}' for m in range(1,13)]
    gaps=ok(preview(studio,months=months))
    assert gaps['months']==months and len(gaps['month_boxes'])==12
    assert gaps['group_means']==gaps['profiles']==[]


@pytest.mark.parametrize('unproved',[None,'unproved'])
def test_unproved_catalogue_orientation_excluded_from_boxes(studio,monkeypatch,unproved):
    from app.repositories import comparison as repo
    original=repo.ws_catalogue
    # The DB currently forbids null WaveScan catalogue orientation. Exercise
    # the consumer's required defensive behavior at that repository seam.
    def catalogue(*args):
        return [{**p,'orientation':unproved if p['code']=='1HOOD' else p['orientation']} for p in original(*args)]
    monkeypatch.setattr(repo,'ws_catalogue',catalogue)
    vehicle=ok(visuals(studio))['vehicles'][0]
    assert vehicle['cf_boxes']==[dict(orientation=o,n=0,stats=None) for o in ('H','V')]
    hood=next(p for p in vehicle['locations'] if p['code']=='1HOOD')
    assert hood['orientation'] is None and len(hood['traces'])==2
    profile=next(p for p in ok(preview(studio))['profiles'] if p['code']=='1HOOD')
    assert profile['orientation'] is None and profile['metrics'][0]['mean']=='50'


def test_eight_ids_and_wrong_plant(studio):
    c=studio['conn']
    c.execute(text('RESET ROLE'))
    for i in range(3):
        load=c.execute(text("INSERT INTO load_batch(source_file,source_sheet,plant_code,file_hash,raw_store_key,status,domain) "
            "VALUES ('Eight.xlsx','Eight',:p,:hash,'unused','COMMITTED','WAVESCAN') RETURNING load_id"),
            {'p':studio['plant'],'hash':uuid.uuid4().hex*2}).scalar_one()
        c.execute(text("INSERT INTO wavescan(measured_date,plant,model,color,serial_no,checkzone,tolerance_group,cf,load_id,source_sheet,source_row) "
            "VALUES ('2002-07-03',:p,:m,'Arctic White',:serial,'1HOOD','Horizontal',0,:load,'Eight',1)"),
            dict(p=studio['plant'],m=MODEL,serial=f'Eight{i}',load=load))
    c.execute(text('SET LOCAL ROLE app_rw'))
    ids=[studio['ws'][k] for k in ('newer','older','tie','blank','same_serial_other_load')]
    picker=ok(studio['client'].get(f"/api/v1/plants/{studio['plant']}/comparison/vehicles",params={'domain':'WAVESCAN','month':'2002-07','model':MODEL}))
    ids.extend(v['vehicle_id'] for v in picker['items'] if (v['serial_no'] or '').startswith('Eight'))
    assert len(ids)==8
    # Valid IDs from another plant cannot be silently returned.
    assert visuals(studio,ids,plant='FVL').status_code==404
    assert [v['vehicle_id'] for v in ok(visuals(studio,ids))['vehicles']]==ids


def test_generated_t81_contract_examples_and_decimal_strings():
    import json
    from pathlib import Path
    from app.schemas.comparison import ComparisonMonthlyPreviewIn,ComparisonMonthlyPreviewOut
    root=Path(__file__).resolve().parents[1]
    assert (root/'openapi.json').read_bytes()==(root.parent/'docs/openapi.json').read_bytes()
    spec=json.loads((root/'openapi.json').read_bytes())
    post=spec['paths']['/api/v1/plants/{plant_code}/comparison/monthly-preview']['post']
    for e in post['requestBody']['content']['application/json']['examples'].values():
        ComparisonMonthlyPreviewIn.model_validate(e['value'])
    for e in post['responses']['200']['content']['application/json']['examples'].values():
        out=ComparisonMonthlyPreviewOut.model_validate(e['value']).model_dump(mode='json')
        assert out['group_means'][0]['mean']=='50'
    assert spec['components']['schemas']['ComparisonUngradedStats']['properties']['mean']['type']=='string'


# T85: FTM's Film uploads were in T85's Clear list, so the FILMTHICKNESS
# case below found no month to ask about and stopped at `assert month`. The
# claim -- "the Studio's boxes are the overview's boxes, unchanged" -- is
# about the read, so the month is made here. It goes into `data`'s own
# transaction, which is rolled back, so nothing survives the test.
@pytest.fixture
def ftm_film_month(data):
    c = data["conn"]
    c.execute(text("RESET ROLE"))
    points = c.execute(text(
        "SELECT point_code FROM ref_plant_film_point "
        " WHERE plant_code='FTM' AND model_code=:m AND retired_at IS NULL "
        " ORDER BY point_no LIMIT 4"), {"m": MODEL}).scalars().all()
    assert points, "FTM has no live Film points for this model"
    load = c.execute(text(
        "INSERT INTO load_batch(source_file,source_sheet,plant_code,file_hash,"
        "raw_store_key,status,domain) VALUES ('t85-ftm-film.xlsx','Synthetic','FTM',"
        ":hash,'unused','COMMITTED','FILMTHICKNESS') RETURNING load_id"),
        {"hash": uuid.uuid4().hex * 2}).scalar_one()
    row = 0
    for car in range(2):
        for point in points:
            row += 1
            c.execute(text(
                "INSERT INTO filmthickness(measured_date,plant,model,color,"
                "src_location_text,point_code,layer_code,thickness,logical_vehicle_id,"
                "load_id,source_sheet,source_row) VALUES ('2003-09-03','FTM',:m,"
                "'Desert Island Blue',:pt,:pt,'CLEAR',:v,:vid,:load,'Synthetic',:row)"),
                {"m": MODEL, "pt": point, "v": 40 + row, "vid": f"t85-ftm-{car}",
                 "load": load, "row": row})
    c.execute(text("SET LOCAL ROLE app_rw"))
    return data


@pytest.mark.parametrize('domain,metric,path,boxkey',[('WAVESCAN','cf','wavescan','wavescan_boxes'),('FILMTHICKNESS','clear','filmthickness','film_boxes')])
def test_existing_standard_and_status_boxes_unchanged(ftm_film_month,data,domain,metric,path,boxkey):  # T85
    picker=ok(data['client'].get('/api/v1/plants/FTM/comparison/vehicles',params={'domain':domain}))
    month=picker['default_month']
    assert month and picker['model_options']
    model=picker['model_options'][0]
    original=ok(data['client'].get(f'/api/v1/plants/FTM/{path}/overview',params={'month':month,('model' if domain=='WAVESCAN' else 'models'):model}))['boxes']
    if domain=='FILMTHICKNESS':original=[b for b in original if b['layer_code']=='CLEAR']
    result=ok(preview(data,plant='ftm',domain=domain,metric=metric,model=model,months=[month]))
    assert result['plant_code']=='FTM'
    assert result['month_boxes'][0][boxkey]==original
    assert original and any(b['status'] is not None for b in original)

