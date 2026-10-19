"""T79 raw Comparison contracts; domain identities and precision are preserved."""
from datetime import date
from typing import Literal

from pydantic import Field
from typing import Annotated
from pydantic import StringConstraints, model_validator
from app.domain.history import month_date_bounds
from app.schemas.overview import OverviewBox
from app.schemas.film_overview import FilmOverviewBox


from app.schemas.common import MeasureValue, PageInfo, StrictModel

ComparisonDomain = Literal["WAVESCAN", "FILMTHICKNESS"]
ComparisonMetric = Literal["lw", "sw", "cf", "doi", "du", "wa", "wb", "wc", "wd", "we", "b",
                           "ecoat", "primer", "base", "clear"]


class ComparisonCandidate(StrictModel):
    """HistoryVehicleSetOut mappings for WaveScan; FilmVehicleOut mappings for Film.

    No synthetic serial or merged WaveScan loads. Film provenance can span loads.
    """
    vehicle_id: str = Field(description="WaveScan History vehicle_id: SHA-256 of load_id|date|model|color|serial. Film logical_vehicle_id: plant|date|model|color|VIN, else job, else blank, hashed without load_id. IDs never cross domains.")
    domain: ComparisonDomain = Field(description="The single measurement domain owning this ID.")
    measured_date: date = Field(description="Stored measured date, never upload date.")
    week: int = Field(ge=0, le=5, description="History measured_week for both domains: days 1-7, 8-14, 15-21, 22-28, 29-end; 0 = day not recorded (RO18 B4).")
    date_is_month_only: bool = Field(default=False, description="RO18 (B4): the sheet had no date; measured_date is the 1st of a named month. Show '<Month YYYY> - day not recorded'.")
    model: str | None = Field(description="Existing domain vehicle model code; no inferred model.")
    color: str | None = Field(description="Exact colour name returned by the active view.")
    serial_no: str | None = Field(description="History serial_no or Film VIN; null stays null, never fabricated from a source row.")
    identity_complete: bool = Field(description="Current History identity_complete: date/model/colour present, serial may be blank (T39). Film identity_complete is true if VIN or job_nos exists. Neither domain fabricates a serial.")
    point_count: int = Field(description="History point_count (how many of expected_point_count's points the car has an active reading on; T114-FIX); Film mapped_point_count (distinct active point codes across loads), independent of selected metric.")
    expected_point_count: int | None = Field(description="History expected_point_count: the live, non-extra points of this plant's Wave Scan list for the model (ref_model.expected_zone_count when the plant has no list for it; T114-FIX); Film expected_point_count from the live plant/model gold catalogue, null if absent.")
    incomplete: bool = Field(description="History incomplete_set (identity incomplete or point count differs); Film incomplete (expected count absent or differs). No grade.")
    load_id: int | None = Field(default=None, description="WaveScan History load_id, part of its identity; null for Film.")
    source_file: str | None = Field(default=None, description="WaveScan History source_file; null for Film, whose files are in source_files.")
    source_sheet: str | None = Field(default=None, description="WaveScan History source_sheet; null for Film.")
    job_nos: list[str] | None = Field(default=None, description="Film job_nos: distinct sorted Job Numbers; null for WaveScan.")
    load_ids: list[int] | None = Field(default=None, description="Film load_ids: contributing active loads ascending; provenance only. Null for WaveScan.")
    source_files: list[str] | None = Field(default=None, description="Film source_files in load_ids order, preserving multi-load provenance. Null for WaveScan.")


class ComparisonWeekOption(StrictModel):
    month: str = Field(description="Measured calendar month YYYY-MM; periods are scoped by month.")
    week: int = Field(ge=0, le=5, description="Existing History measured_week band, 1..5; 0 = day not recorded (RO18 B4).")


class ComparisonVehiclesOut(StrictModel):
    plant_code: str = Field(description="Resolved canonical plant code (approved aliases supported).")
    plant_is_active: bool = Field(description="ref_plant.is_active; a known inactive plant has empty options and items.")
    domain: ComparisonDomain = Field(description="Required single domain; options and identities come only from its active facts.")
    default_month: str | None = Field(description="Newest measured month with active domain facts, or null.")
    selected_months: list[str] = Field(description="Effective measured months, deduplicated in caller order; omitted month uses default_month, or [] when none.")
    available_months: list[str] = Field(description="All measured months with active domain facts at this plant, newest first.")
    model_options: list[str] = Field(description="Code-sorted union of models with active facts over effective months, ignoring color, period, and q.")
    color_options: list[str] = Field(description="Name-sorted union of active colours over effective months and selected model, ignoring color, period, q. Empty without model.")
    week_options: list[ComparisonWeekOption] = Field(description="Only month/week pairs with active facts for the selected model; month DESC, week DESC. Ignores color, period, q. Empty without model.")
    items: list[ComparisonCandidate] = Field(description="Active sets matching all filters; empty until model selected. Order: measured_date DESC, then serial_no ASC (Film falls back to first lexical job_nos), null identity last, then domain vehicle_id ASC. WaveScan loads never merge.")
    page: PageInfo = Field(description="total is the matching vehicle count before limit/offset; default limit=50, offset=0.")
    active_data_source: Literal["v_wavescan_active", "filmthickness_active"] = Field(description="Existing domain active view; excludes review, duplicate and superseded facts.")


class ComparisonReading(StrictModel):
    value: MeasureValue = Field(description="Nonnull exact stored NUMERIC as a decimal string, full precision including trailing zeros; no rounding, averaging, status, or limits.")
    measurement_id: int | None = Field(default=None, description="WaveScan active measurement row ID; distinct duplicate-checkzone rows remain distinct. Null for Film.")
    panel_label: str | None = Field(default=None, description="WaveScan panel as History shows it -- the stored position, the long name (T94 D-94-4); null for Film.")
    source_file: str | None = Field(default=None, description="WaveScan load_batch.source_file; null for Film.")
    source_sheet: str | None = Field(default=None, description="WaveScan stored source_sheet; null for Film.")
    source_row: int | None = Field(description="Stored domain source row, nullable provenance stays nullable.")
    load_id: int | None = Field(description="Stored contributing load for this exact reading, nullable provenance stays nullable.")
    src_location_text: str | None = Field(default=None, description="Film original location spelling from the selected point-grid row; null for WaveScan.")
    src_zone_text: str | None = Field(default=None, description="D-RO17-16: the plant's own raw label of this WaveScan reading (wavescan.src_zone_text), as written in the file; null for Film or when not stored.")


class ComparisonCell(StrictModel):
    vehicle_id: str = Field(description="ID of the corresponding column, in caller order.")
    missing: bool = Field(description="True exactly when readings=[]: no active nonnull value of the selected metric at this catalogue location. Never substitutes zero.")
    readings: list[ComparisonReading] = Field(description="Every distinct nonnull WaveScan measurement row ordered by measurement_id, including repeated checkzones; Film zero or one selected-layer value under existing point-grid membership (earliest load/source row wins whole).")


class ComparisonLocation(StrictModel):
    point_no: int = Field(description="Live plant/model catalogue point_no; walk/display order, never inferred from source rows.")
    code: str = Field(description="WaveScan ref_plant_ws_point.zone_code; Film ref_plant_film_point.point_code.")
    orientation: str | None = Field(description="WaveScan catalogue tolerance_group as stored (Horizontal/Vertical); Film catalogue orientation H/V, nullable where unproved.")
    counted: bool | None = Field(default=None, description="T114: WaveScan point's latest ws_point_setting.counted (no row = counted). False keeps its readings here and off the dashboard. Null for Film.")
    is_extra: bool | None = Field(default=None, description="T114: WaveScan point beyond the plant's standard list (D-114-5). Null for Film.")
    cells: list[ComparisonCell] = Field(description="Exactly one cell per requested vehicle, in columns/caller order, including missing slots.")


class ComparisonUnalignedLocation(StrictModel):
    vehicle_id: str = Field(description="Requested WaveScan vehicle owning this historical row.")
    checkzone: str = Field(description="Stored WaveScan checkzone absent from the current live plant/model catalogue; never guessed onto a slot.")
    reading: ComparisonReading = Field(description="Exact nonnull selected metric with original source labels and row identity; one entry per measurement row.")
    retired: bool = Field(default=False, description="T114: checkzone is a retired point of this plant/model list (D-114-4). The reading stays; it left the dashboard.")


class ComparisonPointsOut(StrictModel):
    plant_code: str = Field(description="Resolved canonical plant code.")
    domain: ComparisonDomain = Field(description="One domain; all requested IDs must belong to it.")
    model: str = Field(description="One model; every requested vehicle must have active facts for this plant/domain/model, else 404.")
    metric: ComparisonMetric = Field(description="WaveScan: lw, sw, cf, doi, du, wa, wb, wc, wd, we, b. Film: ecoat, primer, base, clear. A metric from another domain is 422.")
    columns: list[ComparisonCandidate] = Field(description="1..8 distinct active vehicles with common identity/date/colour/completeness and domain provenance, in exact vehicle_id request order; absent or wrong plant/domain/model is 404, never omitted.")
    locations: list[ComparisonLocation] = Field(description="Full live plant/model catalogue, including slots missed by every selected vehicle; point_no ASC then code ASC. No selected value is represented by missing=true and readings=[].")
    unaligned_locations: list[ComparisonUnalignedLocation] = Field(description="WaveScan nonnull historical rows outside the live catalogue, listed separately after catalogue locations, checkzone ASC then measurement_id ASC. Never a missing catalogue slot. Film always [].")
    active_data_source: Literal["v_wavescan_active", "filmthickness_active"] = Field(description="Domain's existing active-fact view; no review rows, grades or thresholds.")

# T81 calculated read contracts. Reused monthly boxes keep their existing DTOs.
ComparisonSelectedMetric = Literal['cf', 'ecoat', 'primer', 'base', 'clear']
ComparisonOrientation = Literal['H', 'V']
ComparisonMonth = Annotated[str, StringConstraints(pattern=r'^[0-9]{4}-(0[1-9]|1[0-2])$')]


class ComparisonMonthlyPreviewIn(StrictModel):
    """Temporary read only: no group name, saved group, audit, file or session write."""
    domain: ComparisonDomain = Field(description='Single active-fact domain; never combined.')
    model: str = Field(min_length=1, max_length=64, description='Exact model with active facts at this plant/domain across any measured month. Another plant/domain is invalid (422); known inactive plant returns empty results.')
    metric: ComparisonSelectedMetric = Field(description='WaveScan cf only; Film ecoat, primer, base or clear only. Wrong-domain metric is 422.')
    months: list[ComparisonMonth] = Field(min_length=1, description='Distinct valid measured_date YYYY-MM tokens in caller order, with no selection cap. Missing months remain explicit gaps; duplicate/malformed tokens are 422.')

    @model_validator(mode='after')
    def validate_selection(self):
        allowed = {'cf'} if self.domain == 'WAVESCAN' else {'ecoat', 'primer', 'base', 'clear'}
        if self.metric not in allowed:
            raise ValueError('metric does not belong to the selected domain')
        if len(set(self.months)) != len(self.months):
            raise ValueError('months must be distinct')
        for month in self.months:
            month_date_bounds(month)
        return self


class ComparisonMonthlyMean(StrictModel):
    month: str = Field(description='Requested measured_date month, in caller order, including gaps.')
    mean: MeasureValue | None = Field(description='Decimal sum / nonnull reading count for this month and exact series; null if n=0. Zero is a reading.')
    n: int = Field(ge=0, description='Contributing nonnull active source readings, not vehicles or months; distinct duplicate measurement rows count separately. For group series this is the reused Overview box n.')


class ComparisonMeanSummary(StrictModel):
    monthly: list[ComparisonMonthlyMean] = Field(description='Exactly every requested month in caller order; absent series has mean=null and n=0.')
    mean: MeasureValue | None = Field(description='Decimal arithmetic sum of nonnull monthly means / contributing month count. Each month weighs once, regardless of reading n; 40 from one and 60 from nine yield 50. None yields null, never zero. No float arithmetic or rounding.')
    contributing_months: list[str] = Field(description='Months whose monthly mean is nonnull, in caller order.')
    missing_months: list[str] = Field(description='Remaining requested months in caller order; together with contributing_months partitions the request.')
    contributing_month_count: int = Field(ge=0, description='Count of nonnull monthly means, each weighted once in group mean.')


class ComparisonGroupMean(ComparisonMeanSummary):
    """Separate colour/orientation/metric series: a group has no box, grade,
    status, standard or target because only monthly means are averaged.
    """
    color: str = Field(description='Exact active colour; never averaged with another colour. WaveScan family display order (null=99), then name; Film existing Base H/V ladder, family order null last, then name. Each colour includes H then V even if both means are null.')
    orientation: ComparisonOrientation = Field(description='Normalized H or V, H before V per colour. Unproved orientation is excluded, never guessed.')
    metric: ComparisonSelectedMetric = Field(description='Selected domain metric only; no cross-layer aggregation.')
    layer_code: Literal['ECOAT', 'PRIMER', 'BASE', 'CLEAR'] | None = Field(description='Film selected layer; null for WaveScan CF.')


class ComparisonProfileMetric(ComparisonMeanSummary):
    metric: Literal['du', 'wa', 'wb', 'wc', 'wd', 'we'] = Field(description='Exactly six entries per location in du, wa, wb, wc, wd, we order. Monthly mean uses all nonnull aligned v_wavescan_active readings for this exact month/model/colour/location/metric, preserving distinct duplicate rows.')


class ComparisonMonthlyProfile(StrictModel):
    color: str = Field(description='One exact active colour, in the same colour order as group_means; no cross-colour mean.')
    point_no: int = Field(description='Live plant/model catalogue walk order; locations point_no ASC then code ASC within each colour.')
    code: str = Field(description='Exact live ref_plant_ws_point.zone_code. Full catalogue including all-missing rows; historical unaligned zones excluded.')
    orientation: ComparisonOrientation | None = Field(description='Catalogue Horizontal/H -> H, Vertical/V -> V; unknown/null remains null, never inferred from code or source.')
    metrics: list[ComparisonProfileMetric] = Field(description='Exactly du, wa, wb, wc, wd, we in that order, each with all caller months and an equal-month mean. Null parameter/month stays missing, literal zero contributes.')


class ComparisonMonthBoxes(StrictModel):
    month: str = Field(description='Exactly one item per requested month in caller order, including an all-missing month.')
    wavescan_boxes: list[OverviewBox] = Field(description='Unchanged full-population WaveScan Overview boxes for this month/model from v_wavescan_active: same samples, quartiles, outliers, mean, status and standards and model/H-before-V/family-display-order/colour order. Empty for Film; never regraded or averaged.')
    film_boxes: list[FilmOverviewBox] = Field(description='Unchanged Film Overview boxes from filmthickness_active for selected month/model/layer only, same full samples, standards/status/outliers and layer/model/H-before-V/Base-ladder colour order. Empty for WaveScan.')


class ComparisonUnalignedMonthCount(StrictModel):
    month: str = Field(description='Requested measured month in caller order.')
    n: int = Field(ge=0, description='Number of active WaveScan source measurement rows for this model/month outside the live catalogue, independent of metric nulls. Excluded from profile means with no guessed orientation. Film zero.')


class ComparisonMonthlyPreviewOut(StrictModel):
    plant_code: str = Field(description='Canonical plant code after approved alias resolution; unknown plant 404, inactive plant empty results.')
    domain: ComparisonDomain = Field(description='Single requested domain, never combined.')
    model: str = Field(description='Exact requested model; active plant requires active domain facts at this plant.')
    metric: ComparisonSelectedMetric = Field(description='cf for WaveScan, selected Film layer metric otherwise.')
    months: list[str] = Field(description='All requested months in caller order, with gaps retained.')
    month_boxes: list[ComparisonMonthBoxes] = Field(description='One unchanged domain Overview calculation per requested month; other-domain list empty.')
    group_means: list[ComparisonGroupMean] = Field(description='Every active colour in selected model/months x H then V x selected metric, even no selected metric in either orientation. Equal-month mean only: no group box, quartiles, whiskers, status, standard or target because those cannot be averaged.')
    profiles: list[ComparisonMonthlyProfile] = Field(description='WaveScan colours in domain order x full live catalogue point_no ASC/code ASC; six metrics du->we. Film exactly []. Monthly values are Decimal reading means, group values equal-month means.')
    unaligned_reading_count: list[ComparisonUnalignedMonthCount] = Field(description='Exactly one row count per requested month in caller order; historical unaligned WaveScan source rows do not enter profiles. Film zero.')
    active_data_source: Literal['v_wavescan_active', 'filmthickness_active'] = Field(description='Existing active view for the requested domain; no review, duplicate-flagged or superseded facts. POST performs SELECT only, saves no group/audit/file/session.')


class ComparisonUngradedStats(StrictModel):
    """Existing box_stats: linear quartiles at (n-1)*p; Tukey 1.5 IQR
    inlier whiskers; sorted outliers. Decimal arithmetic, never graded.
    """
    box_min: MeasureValue = Field(description='Minimum CF of the full cross-location sample.')
    q1: MeasureValue = Field(description='Linear 25th percentile from box_stats.')
    median: MeasureValue = Field(description='Linear 50th percentile from box_stats.')
    q3: MeasureValue = Field(description='Linear 75th percentile from box_stats.')
    box_max: MeasureValue = Field(description='Maximum CF of the full sample.')
    whisker_lo: MeasureValue = Field(description='Lowest reading inside Tukey q1 - 1.5 IQR fence.')
    whisker_hi: MeasureValue = Field(description='Highest reading inside Tukey q3 + 1.5 IQR fence.')
    outliers: list[MeasureValue] = Field(description='Every reading outside Tukey 1.5 IQR fences, sorted ascending; duplicates preserved.')
    mean: MeasureValue = Field(description='Decimal sum / reading n across current-catalogue locations of this orientation and vehicle. No monthly weighting, grade, status, standard or target.')


class ComparisonUngradedBox(StrictModel):
    orientation: ComparisonOrientation = Field(description='Exactly H then V. Unknown/null catalogue orientation and unaligned rows excluded.')
    n: int = Field(ge=0, description='Every nonnull CF active measurement row at an aligned catalogue location of this orientation, duplicates counted; no cap.')
    stats: ComparisonUngradedStats | None = Field(description='box_stats over this cross-location CF sample; n=0 null, n=1 existing degenerate result (draw a point). No grade/standard/status fields.')


class ComparisonRawTrace(StrictModel):
    measurement_id: int = Field(description='v_wavescan_active row identity; each distinct duplicate row remains separate, measurement_id ASC within location.')
    panel_label: str | None = Field(description='The panel as History shows it -- the stored position, the long name (T94 D-94-4); never the rough spelling, never guessed.')
    src_zone_text: str | None = Field(default=None, description="D-RO17-16: the plant's own raw label of this reading (wavescan.src_zone_text), as written in the file; null when not stored.")
    source_file: str | None = Field(description='Original load_batch.source_file.')
    source_sheet: str | None = Field(description='Stored source sheet.')
    source_row: int | None = Field(description='Stored source row; together with location and measurement_id identifies the raw line.')
    load_id: int | None = Field(description='Original contributing load; part of T79 WaveScan vehicle-set identity.')
    cf: MeasureValue | None = Field(description='Exact stored CF decimal string, null missing and zero a reading; no averaging.')
    du: MeasureValue | None = Field(description='Exact stored DU decimal string; null missing, zero a reading.')
    wa: MeasureValue | None = Field(description='Exact stored WA decimal string; null missing, zero a reading.')
    wb: MeasureValue | None = Field(description='Exact stored WB decimal string; null missing, zero a reading.')
    wc: MeasureValue | None = Field(description='Exact stored WC decimal string; null missing, zero a reading.')
    wd: MeasureValue | None = Field(description='Exact stored WD decimal string; null missing, zero a reading.')
    we: MeasureValue | None = Field(description='Exact stored WE decimal string; null missing, zero a reading.')


class ComparisonVisualLocation(StrictModel):
    point_no: int = Field(description='Live catalogue point_no ASC, then code ASC.')
    code: str = Field(description='Exact live plant/model zone code, including all-missing rows.')
    orientation: ComparisonOrientation | None = Field(description='Catalogue H/Horizontal -> H, V/Vertical -> V; unknown/null stays null.')
    traces: list[ComparisonRawTrace] = Field(description='Every raw active source row at this location, measurement_id ASC, even all parameters null; no duplicate collapse or location mean. No readings -> [].')


class ComparisonVisualUnaligned(StrictModel):
    checkzone: str = Field(description='Stored historical zone outside live catalogue; order checkzone ASC then trace measurement_id ASC. No guessed orientation.')
    trace: ComparisonRawTrace = Field(description='Full raw source row, including nullable CF and six DU-WE parameters; excluded from H/V boxes and profile lines.')


class ComparisonVehicleVisual(StrictModel):
    vehicle_id: str = Field(description='Requested T79 WaveScan vehicle-set ID including load identity; caller order.')
    cf_boxes: list[ComparisonUngradedBox] = Field(description='Exactly H then V ungraded CF cross-location distributions, box_stats linear quartiles and Tukey 1.5 IQR whiskers. Null/unproved and historical unaligned rows excluded.')
    locations: list[ComparisonVisualLocation] = Field(description='Full live plant/model catalogue point_no ASC, code ASC, even all-missing rows; raw traces measurement_id ASC.')
    unaligned_locations: list[ComparisonVisualUnaligned] = Field(description='Every historical row outside live catalogue, checkzone ASC then measurement_id ASC; no inferred orientation.')


class ComparisonVehicleVisualsOut(StrictModel):
    plant_code: str = Field(description='Canonical plant after approved alias resolution; unknown plant 404.')
    model: str = Field(description='Exact requested WaveScan model; any ID in another model/plant/domain or absent active facts is 404, never silently omitted.')
    columns: list[ComparisonCandidate] = Field(description='T79 WaveScan identities/provenance, 1..8 distinct IDs in caller order including load identity.')
    vehicles: list[ComparisonVehicleVisual] = Field(description='Exactly one visual per requested ID, in caller order. Film is not accepted; its T80 matrix remains the vehicle read.')
    active_data_source: Literal['v_wavescan_active'] = Field(description='Existing WaveScan active view only. No persistence, workbook reads, status, standard, or source-fact mutation.')

# Illustrative complete contracts: each model lane and domain remains separate.
MONTHLY_REQUEST_EXAMPLES = {
    'WaveScan': {'summary': 'CF and DU-WE over arbitrary ordered measured months', 'value': dict(domain='WAVESCAN', model='P703 DBL RANGER', metric='cf', months=['2026-06', '2026-07'])},
    'Film': {'summary': 'Clear layer over the same ordered months', 'value': dict(domain='FILMTHICKNESS', model='P703 DBL RANGER', metric='clear', months=['2026-06', '2026-07'])},
}


def _monthly_example(domain, metric):
    months = ['2026-06', '2026-07']
    common = dict(color='Arctic White', metric=metric, layer_code=None if domain=='WAVESCAN' else 'CLEAR')
    groups = []
    for orient in ('H', 'V'):
        groups.append(dict(**common, orientation=orient,
            monthly=[dict(month=m, mean=v if orient=='H' else None, n=n if orient=='H' else 0) for m,v,n in zip(months,['40','60'],[1,9])],
            mean='50' if orient=='H' else None, contributing_months=months if orient=='H' else [],
            missing_months=[] if orient=='H' else months, contributing_month_count=2 if orient=='H' else 0))
    month_boxes = []
    for month, value, n in zip(months, ['40','60'], [1,9]):
        box = dict(model_code='P703 DBL RANGER',color_name='Arctic White',n=n,
            **{key:value for key in ('box_min','q1','median','q3','box_max','whisker_lo','whisker_hi','mean')}, outliers=[],family_code=None,status=None)
        if domain=='WAVESCAN':
            box.update(orient='Horizontal',ford=None,minimum=None,below_minimum=[])
        else:
            box.update(orient='H',layer_code='CLEAR',vehicles=n,lo=None,hi=None,target=None,standard_scope='NONE',
                family_name=None,family_order=None,color_rank=1,lo_label=None,hi_label=None,target_label=None,out_of_spec=[])
        month_boxes.append(dict(month=month,wavescan_boxes=[box] if domain=='WAVESCAN' else [],film_boxes=[box] if domain!='WAVESCAN' else []))
    profiles = []
    if domain=='WAVESCAN':
        metrics=[]
        for param in ('du','wa','wb','wc','wd','we'):
            metrics.append(dict(metric=param,monthly=[dict(month=m,mean=None,n=0) for m in months],mean=None,
                contributing_months=[],missing_months=months,contributing_month_count=0))
        profiles=[dict(color='Arctic White',point_no=1,code='1HOOD',orientation='H',metrics=metrics)]
    return dict(plant_code='FVL',domain=domain,model='P703 DBL RANGER',metric=metric,months=months,
        month_boxes=month_boxes,group_means=groups,profiles=profiles,
        unaligned_reading_count=[dict(month=m,n=0) for m in months],active_data_source='v_wavescan_active' if domain=='WAVESCAN' else 'filmthickness_active')


MONTHLY_RESPONSE_EXAMPLES = {name: {'summary': '40 (n=1), 60 (n=9) -> equal-month 50; Vertical missing',
    'value': _monthly_example(domain, metric)} for name,domain,metric in (('WaveScan','WAVESCAN','cf'),('Film','FILMTHICKNESS','clear'))}
