"""RO19 independent measuring order for each plant/model/domain list.

Orders change only append-only reference rows, never point identity or facts.
The dry run calls the single ingest planner with in-memory reference copies.
"""
from __future__ import annotations

from dataclasses import replace

from sqlalchemy import text

from app.domain.film import normalise_location
from app.repositories import audit, batches
from app.repositories import point_walk as repo
from app.repositories import reference
from app.services import point_labels
from app.services.workbooks import WorkbookError, resolve_plant

DOMAINS = {"FILMTHICKNESS": "film", "WAVESCAN": "wavescan"}


def _scope(conn, plant_code, model_code, domain):
    if domain not in DOMAINS:
        raise WorkbookError(422, "Choose FILMTHICKNESS or WAVESCAN.")
    plant = resolve_plant(conn, plant_code)["plant_code"]
    model = str(model_code).strip()
    if not repo.live(conn, plant, model, domain):
        raise WorkbookError(404, f"{plant} has no live {domain} point list for {model}.")
    return plant, model


def read(conn, plant_code, model_code, domain):
    plant, model = _scope(conn, plant_code, model_code, domain)
    latest = repo.latest(conn, plant, model, domain)
    labels = point_labels.current_labels(conn, DOMAINS[domain], plant, model)
    return {
        "plant_code": plant, "model_code": model, "domain": domain,
        "version_id": latest["version_id"] if latest else None,
        "set_by": str(latest["set_by"]) if latest and latest["set_by"] else None,
        "set_at": latest["set_at"] if latest else None,
        "reason": latest["reason"] if latest else None,
        "items": [{**p, "label": labels.get(p["point_code"], p["point_code"])}
                  for p in repo.live(conn, plant, model, domain)],
    }


def _permutation(conn, plant, model, domain, point_codes):
    current = repo.live(conn, plant, model, domain)
    expected = {p["point_code"] for p in current}
    codes = list(point_codes)
    if len(codes) != len(expected) or set(codes) != expected:
        raise WorkbookError(422, "The measuring order must name every live point exactly once. Reload the list; nothing was changed.")
    return codes


def set_order(conn, plant_code, model_code, domain, *, point_codes,
              expected_version_id, reason, actor, correlation_id):
    plant, model = _scope(conn, plant_code, model_code, domain)
    point_labels.lock_list(conn, DOMAINS[domain], plant, model)
    before = read(conn, plant, model, domain)
    if before["version_id"] != expected_version_id:
        raise WorkbookError(409, "The measuring order changed while you were editing. Reload it; nothing was changed.")
    codes = _permutation(conn, plant, model, domain, point_codes)
    if not str(reason).strip():
        raise WorkbookError(422, "Give the reason for changing the measuring order.")
    version = repo.append_version(conn, plant, model, domain, codes, actor=actor, reason=reason)
    audit_id = audit.record(conn, action="catalogue.point_walk.set", entity_type="point_walk_version",
                            entity_id=version, actor_user_id=actor or None,
                            before={"version_id": before["version_id"], "point_codes": [p["point_code"] for p in before["items"]]},
                            after={"plant_code": plant, "model_code": model, "domain": domain,
                                   "point_codes": codes, "reason": reason, "owner_decision": "RO19 D-RO19-1/-2"},
                            correlation_id=correlation_id)
    return {**read(conn, plant, model, domain), "audit_id": audit_id}


def record_membership(conn, plant, model, domain, *, place_after=None, added_code=None,
                      actor=None, reason, correlation_id=None):
    """Snapshot a point add/restore under the same caller's list lock."""
    current = read(conn, plant, model, domain)
    codes = [p["point_code"] for p in current["items"]]
    if added_code is not None:
        codes.remove(added_code)
        if place_after is not None:
            if place_after not in codes:
                raise WorkbookError(422, "Place the new point after a live point of this list. Nothing was changed.")
            codes.insert(codes.index(place_after) + 1, added_code)
        else:
            codes.append(added_code)
    return set_order(conn, plant, model, domain, point_codes=codes,
                     expected_version_id=current["version_id"], reason=reason,
                     actor=actor, correlation_id=correlation_id)


def dry_run(conn, plant_code, model_code, domain, *, point_codes, ingest_service,
            simulate_film_rules=False):
    """Read bytes and plan twice. No locks, inserts, updates or replay calls."""
    from app.repositories import filmthickness as film_repo
    from app.services.ingest import IngestService, _projection_of

    plant, model = _scope(conn, plant_code, model_code, domain)
    codes = _permutation(conn, plant, model, domain, point_codes)
    ref = reference.load_reference_data(conn)
    film = film_repo.load_film_reference(conn)
    scoped = (plant, model)
    film_walk = dict(film.walk)
    film_walk[scoped] = tuple(codes)
    gold = dict(film.plant_catalogue)
    gold[scoped] = {normalise_location(code): code for code in codes}
    settings = dict(film.point_setting)
    if simulate_film_rules and domain == "FILMTHICKNESS":
        orientations = {p["point_code"]: p["orientation"] for p in film_repo.point_setting(conn, plant, model)}
        if any(orientations.get(code) not in ("H", "V") for code in codes):
            raise WorkbookError(422, "Every point needs its own H/V before rules can be simulated.")
        settings[scoped] = {code: (True, orientations[code]) for code in codes}
    simulated = replace(film, walk=film_walk, plant_catalogue=gold, point_setting=settings)
    new_ref = ref
    if domain == "WAVESCAN":
        first = dict(ref.ws_first_point)
        first[scoped] = codes[0]
        new_ref = replace(ref, ws_first_point=first)

    class SimulatedPlanner(IngestService):
        def _plan_film(self, conn, batch, data, ref, film, context):
            return super()._plan_film(conn, batch, data, ref, simulated, context)

    planner = SimulatedPlanner(ingest_service.settings, ingest_service.store)
    ids = conn.execute(text("SELECT load_id FROM load_batch WHERE plant_code=:p AND domain=:d AND rows_in_file>0 ORDER BY load_id"), {"p": plant, "d": domain}).scalars().all()
    stored = changed_sheets = changed_dispositions = changed_ids = 0
    held = []
    for load_id in ids:
        batch = batches.get_batch(conn, int(load_id))
        try:
            # A savepoint per sheet: a SQL error in one sheet's plan must not abort
            # the transaction and turn every later sheet into a false hold.
            with conn.begin_nested():
                data = ingest_service.store.get(batch["raw_store_key"])
                baseline, raw, context = ingest_service._plan(conn, batch, data, ref)
                before = _projection_of(baseline, raw, context)
                relevant = (getattr(getattr(baseline, "model", None), "model", None) == model
                            or any(row.get("canonical", {}).get("model") == model for row in before))
                if not relevant:
                    continue
                stored += 1
                after_plan, after_raw, after_context = planner._plan(conn, batch, data, new_ref)
                after = _projection_of(after_plan, after_raw, after_context)
                b = {row["source_row"]: row for row in before}
                a = {row["source_row"]: row for row in after}
                disposition_diff = id_diff = 0
                for source_row in b.keys() | a.keys():
                    old, new = b.get(source_row, {}), a.get(source_row, {})
                    disposition_diff += old.get("disposition") != new.get("disposition")
                    old_id = (old.get("canonical", {}).get("logical_vehicle_id"), old.get("canonical", {}).get("car_key"))
                    new_id = (new.get("canonical", {}).get("logical_vehicle_id"), new.get("canonical", {}).get("car_key"))
                    id_diff += old_id != new_id
                changed_dispositions += disposition_diff
                changed_ids += id_diff
                changed_sheets += bool(disposition_diff or id_diff or [(r.get("reason"), r.get("detail")) for r in before] != [(r.get("reason"), r.get("detail")) for r in after])
                reasons = sorted({row.get("reason") or "QUARANTINE" for row in after if row.get("disposition") == "QUARANTINE" and row.get("canonical", {}).get("model", model) == model})
                if reasons:
                    held.append({"load_id": load_id, "source_file": batch["source_file"], "source_sheet": batch["source_sheet"], "reasons": reasons})
        except Exception as exc:
            # A planner refusal cannot become a reassuring zero-change count.
            held.append({"load_id": load_id, "source_file": batch["source_file"], "source_sheet": batch["source_sheet"], "reasons": [f"{type(exc).__name__}: {exc}"]})
    return {"stored_sheets": stored, "changed_sheets": changed_sheets,
            "changed_dispositions": changed_dispositions, "changed_vehicle_ids": changed_ids,
            "held_sheets": held}
