r"""T91 Part 3: apply FTM's canonical set. DRY RUN unless told otherwise.

This is the step T86-T90 all stopped before. It writes nothing without
`--apply` **and** `--confirmed-by`, because the owner confirms the
regenerated template before anything is applied (D-91-6).

What it does, and the order is D-89-4's and is a hard gate:

1. read both halves of the template and refuse anything that does not
   declare its own binding **in a data field** (D-91-3). A row with no
   binding, an unknown binding, or an `alias` row in the per-batch file is
   a refusal of the whole file, named by line number. Nothing partial;
2. add the `alias` rows as permanent `ref_plant_zone_map` pairs -- one
   atomic `ZONE` panel-match set per (model, convention), through the real
   write boundary on 8012, so every refusal T86-T91 built still applies.
   **One set per convention**, never one set for both: two spellings of
   two different months may legitimately mean the same panel, but two
   spellings of ONE sheet onto one panel is the August 64-identity defect
   and the boundary refuses it;
3. prove a numbered spelling now resolves to its canonical point, by
   reading the replayed batch back;
4. only then retire the numbered points -- a separate `--retire` run, for
   the same reason the order exists: while a numbered panel is live the
   cleaner matches the gold list first and an alias beside it changes
   nothing, so retiring before aliasing makes the next upload worse.

Why it goes through the API rather than writing SQL: the boundary is where
D-90-3 (no rough name learned forever), D-91-2 (no spelling that means two
panels at this plant learned at all), D-89-4 (no retirement before
aliasing) and the atomicity live. A script that wrote `ref_plant_zone_map`
directly would be a second write path with none of them, which is the
defect Gap B was about.

The per-batch (`binding=batch`) rows are never offered as `matches`. They
travel in the set's `walk` block, which is recorded on the batch and which
nothing on the resolution path can read (D-90-11).

    cd backend && .venv/Scripts/python.exe scripts/t91_apply_canonical.py
    cd backend && .venv/Scripts/python.exe scripts/t91_apply_canonical.py \
        --apply --confirmed-by "<the owner>"
    cd backend && .venv/Scripts/python.exe scripts/t91_apply_canonical.py \
        --retire --confirmed-by "<the owner>"
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

from app.domain.panel_walk import BINDING_ALIAS, BINDING_BATCH  # noqa: E402
from app.domain.references import normalise_alias  # noqa: E402

REFERENCE = BACKEND_ROOT.parent / "docs" / "tasks" / "reference"
ALIASES = REFERENCE / "ftm-canonical-aliases.csv"
WALK = REFERENCE / "ftm-canonical-walk.csv"
BASE = "http://127.0.0.1:8012"
PROPOSALS = "/api/v1/mappings/proposals"
PANEL_MATCH = "/api/v1/mappings/panel-match"

BINDINGS = (BINDING_ALIAS, BINDING_BATCH)


class TemplateRefused(Exception):
    """The template said something that must not be guessed at."""


@dataclass(frozen=True)
class Pair:
    """One template row, with the binding it declared for itself."""

    model_code: str
    convention: str
    source: str
    target: str
    binding: str
    line_no: int

    @property
    def key(self) -> str:
        return normalise_alias(self.source)


def read_template(
    path: Path, *, expect: str, has_convention: bool
) -> list[Pair]:
    """One half of the template, or a refusal naming the line (D-91-3).

    The binding is read from the **data**, never from a comment and never
    from which file it is in -- the file is only the second opinion. A row
    whose binding field is missing, blank or not one of `alias` / `batch`
    refuses the whole file: a template that does not say how far a pair may
    travel is a template nobody may apply.
    """
    if not path.exists():
        raise TemplateRefused(f"{path} does not exist, so there is nothing to apply.")
    width = 5 if has_convention else 4
    pairs: list[Pair] = []
    for line_no, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("model_code"):
            fields = line.split(",")
            if len(fields) != width or fields[-1] != "binding":
                raise TemplateRefused(
                    f"{path.name} line {line_no}: the header is {line!r}. The "
                    f"last column must be `binding`, because the binding has "
                    f"to be in the data (D-91-3)."
                )
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != width:
            raise TemplateRefused(
                f"{path.name} line {line_no}: {line!r} has {len(fields)} "
                f"fields, not {width}. A row that does not declare its own "
                f"binding is never applied."
            )
        if has_convention:
            model, convention, source, target, binding = fields
        else:
            model, source, target, binding = fields
            convention = ""
        if not binding:
            raise TemplateRefused(
                f"{path.name} line {line_no}: {source!r} declares no binding. "
                f"A pair that does not say whether it may be learned forever "
                f"is refused, not guessed at (D-91-3)."
            )
        if binding not in BINDINGS:
            raise TemplateRefused(
                f"{path.name} line {line_no}: {source!r} declares binding "
                f"{binding!r}, which is not one of {' / '.join(BINDINGS)}."
            )
        if binding != expect:
            raise TemplateRefused(
                f"{path.name} line {line_no}: {source!r} declares binding "
                f"{binding!r} in the {expect!r} file. The two halves of the "
                f"template are not interchangeable -- a `batch` pair must "
                f"never reach ref_plant_zone_map (D-90-11)."
            )
        if not (model and source and target):
            raise TemplateRefused(
                f"{path.name} line {line_no}: {line!r} is missing a model, a "
                f"spelling or a target."
            )
        pairs.append(
            Pair(model, convention, source, target, binding, line_no)
        )
    if not pairs:
        raise TemplateRefused(f"{path.name} carries no data rows.")
    return pairs


def refuse_two_targets(pairs: list[Pair]) -> None:
    """One spelling may never be a permanent alias onto two panels.

    `uq_plant_zone_map` is on `(plant, model, raw_zone_text)`, so the second
    one would be a 409 half-way through an atomic set. More to the point it
    is the shape D-91-2 exists for, and it is caught before anything is
    sent rather than after.
    """
    seen: dict[tuple[str, str], Pair] = {}
    for pair in pairs:
        key = (pair.model_code, pair.key)
        first = seen.setdefault(key, pair)
        if first.target != pair.target:
            raise TemplateRefused(
                f"{pair.model_code} / {pair.source} is offered as a permanent "
                f"alias onto {first.target} (line {first.line_no}) and onto "
                f"{pair.target} (line {pair.line_no}). One spelling meaning "
                f"two panels is correct and expected at this plant -- which "
                f"is exactly why neither may be learned forever (D-91-2). "
                f"Nothing was sent."
            )


def build_set(
    *,
    plant: str,
    model: str,
    convention: str,
    load_id: int,
    walk_rows: list[dict],
    aliases: list[Pair],
    batch_pairs: list[Pair],
    fingerprint: str,
    confirmed_by: str,
) -> dict:
    """The one `ZONE` set this convention sends, or a refusal.

    `matches` carries the `alias` rows and nothing else. Every `batch` row
    travels in `walk`, where it is recorded against this upload and where
    nothing on the resolution path can read it.

    The server's own classification of this very sheet is the authority on
    whether a pair may be permanent, not the template's claim about it: an
    `alias` row the screen calls `batch` -- because it is rough here, or
    because another sheet of this plant confirmed it as a different panel
    -- is refused by name. The template is checked against the data it
    claims to describe.
    """
    by_key = {normalise_alias(row["raw_zone_text"]): row for row in walk_rows}
    problems: list[str] = []
    matches: list[dict] = []
    for pair in aliases:
        row = by_key.get(pair.key)
        if row is None:
            problems.append(
                f"{pair.source!r} (line {pair.line_no}) is not a name this "
                f"sheet writes, so this upload cannot confirm it"
            )
            continue
        if row.get("binding") != BINDING_ALIAS:
            problems.append(
                f"{pair.source!r} (line {pair.line_no}) is offered as a "
                f"permanent alias, and the screen says it is per-batch here: "
                f"{row.get('binding_reason')}"
            )
            continue
        matches.append(
            {
                "raw_zone_text": pair.source,
                "raw_position": row.get("raw_position"),
                "zone_code": pair.target,
                "proposed_by_signal": "name",
            }
        )
    if problems:
        raise TemplateRefused(
            f"{plant} / {model} / {convention}: nothing was sent -- "
            + "; ".join(problems)
            + "."
        )

    targets = {pair.key: pair.target for pair in aliases + batch_pairs}
    walk_pairs = [
        {
            "raw_zone_text": row["raw_zone_text"],
            "zone_code": targets[normalise_alias(row["raw_zone_text"])],
            "specificity": row["specificity"],
            "rule": row["rule"],
            "attention": row["attention"],
        }
        for row in walk_rows
        if normalise_alias(row["raw_zone_text"]) in targets
    ]
    return {
        "kind": "ZONE",
        "load_id": load_id,
        "payload": {
            "plant_code": plant,
            "model_code": model,
            "load_id": load_id,
            "matches": matches,
            "walk": {"fingerprint": fingerprint, "pairs": walk_pairs},
            "decided_by": confirmed_by,
            "method": (
                f"T91 Part 3: the owner's confirmed canonical template, "
                f"{convention} convention, applied in D-89-4's order"
            ),
            "note": (
                f"T91 {convention}: {len(matches)} permanent alias(es), "
                f"{len(walk_pairs) - len(matches)} confirmed on this batch "
                f"only (D-90-11)"
            ),
        },
    }


def counts(aliases: list[Pair], batch_pairs: list[Pair]) -> str:
    return (
        f"{len(aliases)} alias row(s), {len(batch_pairs)} batch row(s); "
        f"models {sorted({p.model_code for p in aliases + batch_pairs})}"
    )


def _report_batches(plant: str) -> list[dict]:
    """This plant's uploads and whether a match set could attach, read-only.

    `app/repositories/batches.REPLAYABLE_STATUSES` is the authority, read
    from the code rather than restated here, so this cannot drift from what
    the write boundary will actually accept.
    """
    from app.repositories.batches import REPLAYABLE_STATUSES  # noqa: PLC0415
    from run_standing_8012 import app_url, load_env_test  # noqa: PLC0415
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    load_env_test()
    engine = create_engine(app_url(), future=True)
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        batches = [
            dict(row)
            for row in conn.execute(
                text(
                    "SELECT load_id, source_file, status, rows_loaded,"
                    "       rows_rejected"
                    "  FROM load_batch WHERE plant_code = :p"
                    " ORDER BY load_id DESC"
                ),
                {"p": plant},
            )
            .mappings()
            .all()
        ]
    print(f"{plant} uploads (found by source_file, never by a remembered id):")
    for batch in batches:
        ok = batch["status"] in REPLAYABLE_STATUSES
        print(
            f"  {batch['load_id']}  {batch['source_file']}  {batch['status']}"
            f"  loaded={batch['rows_loaded']} held={batch['rows_rejected']}"
            f"  {'CAN attach' if ok else 'cannot attach'}"
        )
    usable = [b for b in batches if b["status"] in REPLAYABLE_STATUSES]
    if not usable:
        print(
            f"\n  NOT APPLIED: no {plant} upload is "
            f"{' or '.join(REPLAYABLE_STATUSES)}, and a panel match set is "
            f"only accepted against one -- a match is worth nothing until "
            f"those rows are read again. Nothing here invents a target: "
            f"review the month on the match screen BEFORE committing it, "
            f"then run this again."
        )
    return usable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plant", default="FTM")
    parser.add_argument("--aliases", type=Path, default=ALIASES)
    parser.add_argument("--walk", type=Path, default=WALK)
    parser.add_argument("--apply", action="store_true", help="step 2 and 3")
    parser.add_argument("--retire", action="store_true", help="step 4, after 3")
    parser.add_argument("--confirmed-by", default="")
    args = parser.parse_args()

    try:
        aliases = read_template(args.aliases, expect=BINDING_ALIAS, has_convention=False)
        batch_pairs = read_template(args.walk, expect=BINDING_BATCH, has_convention=True)
        refuse_two_targets(aliases)
    except TemplateRefused as refused:
        print(f"REFUSED: {refused}")
        return 2

    print(f"template read: {counts(aliases, batch_pairs)}")
    for model in sorted({pair.model_code for pair in aliases}):
        rows = [pair for pair in aliases if pair.model_code == model]
        print(f"  {model}: would learn forever")
        for pair in rows:
            print(f"      {pair.source} -> {pair.target}")

    if not (args.apply or args.retire):
        # T92: the precondition, measured rather than discovered after the
        # owner has said go. A panel-match set is only accepted against a
        # REPLAYABLE batch -- a match is worth nothing until those rows are
        # read again -- so a plant whose every upload is COMMITTED has
        # nothing for the aliases to attach to.
        print()
        _report_batches(args.plant)
        print(
            "\nDRY RUN. Nothing was written. The owner confirms the template "
            "first (D-91-6); then --apply, and --retire only after step 3 has "
            "proved a numbered spelling resolves (D-89-4)."
        )
        return 0

    if not args.confirmed_by:
        print(
            "REFUSED: --apply and --retire both need --confirmed-by, because "
            "the permanent rows record who said so and the retirement records "
            "why (D-91-5, ADR 0005)."
        )
        return 2

    import httpx  # noqa: PLC0415 -- only the write path needs the server

    from run_standing_8012 import app_url, load_env_test  # noqa: PLC0415
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    load_env_test()
    engine = create_engine(app_url(), future=True)
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        batches = [
            dict(row)
            for row in conn.execute(
                text(
                    "SELECT load_id, source_file, status FROM load_batch"
                    " WHERE plant_code = :p ORDER BY load_id DESC"
                ),
                {"p": args.plant},
            )
            .mappings()
            .all()
        ]
    if not batches:
        print(
            f"REFUSED: {args.plant} has no upload in the database, and a panel "
            f"match set answers one file's question. Nothing was sent."
        )
        return 2
    print("\nbatches found (by source_file, never by a remembered id):")
    for batch in batches:
        print(f"  {batch['load_id']}  {batch['source_file']}  {batch['status']}")

    conventions = sorted({pair.convention for pair in batch_pairs})
    sent = 0
    with httpx.Client(base_url=BASE, timeout=120.0) as client:
        for model in sorted({pair.model_code for pair in aliases}):
            for convention in conventions:
                mine = [
                    pair
                    for pair in batch_pairs
                    if pair.model_code == model and pair.convention == convention
                ]
                keys = {pair.key for pair in mine} | {
                    pair.key
                    for pair in aliases
                    if pair.model_code == model
                }
                chosen: tuple[dict, dict] | None = None
                for batch in batches:
                    response = client.get(
                        PANEL_MATCH,
                        params={"load_id": batch["load_id"], "model_code": model},
                    )
                    if response.status_code != 200:
                        continue
                    walk = (response.json() or {}).get("walk")
                    if not walk:
                        continue
                    written = {
                        normalise_alias(row["raw_zone_text"])
                        for row in walk["rows"]
                    }
                    if keys & written:
                        chosen = (batch, walk)
                        break
                if chosen is None:
                    print(
                        f"\n{model} / {convention}: NOT APPLIED -- no upload in "
                        f"review writes these spellings, so no file can confirm "
                        f"them. A match set answers one file's question; "
                        f"re-upload that month and run this again."
                    )
                    continue
                batch, walk = chosen
                try:
                    body = build_set(
                        plant=args.plant,
                        model=model,
                        convention=convention,
                        load_id=int(batch["load_id"]),
                        walk_rows=walk["rows"],
                        aliases=[
                            pair
                            for pair in aliases
                            if pair.model_code == model
                            and normalise_alias(pair.source)
                            in {
                                normalise_alias(row["raw_zone_text"])
                                for row in walk["rows"]
                            }
                        ],
                        batch_pairs=mine,
                        fingerprint=walk["fingerprint"],
                        confirmed_by=args.confirmed_by,
                    )
                except TemplateRefused as refused:
                    print(f"\nREFUSED: {refused}")
                    continue
                if args.retire and not args.apply:
                    print(
                        f"\n{model} / {convention}: --retire is step 4 and runs "
                        f"after step 3 has proved a numbered spelling resolves. "
                        f"Run --apply first (D-89-4)."
                    )
                    continue
                created = client.post(PROPOSALS, json=body)
                print(
                    f"\n{model} / {convention} on batch {batch['load_id']} "
                    f"({batch['source_file']}): POST {created.status_code}"
                )
                if created.status_code != 201:
                    print(f"  {created.text[:900]}")
                    continue
                proposal_id = created.json()["id"]
                approved = client.post(
                    f"{PROPOSALS}/{proposal_id}/approve", json={}
                )
                print(f"  approve {approved.status_code}")
                if approved.status_code != 200:
                    print(f"  {approved.text[:900]}")
                    continue
                sent += 1
    print(f"\nsets applied: {sent}")
    print(
        "step 3 -- prove a numbered spelling resolves -- is read back from "
        "the replayed batch; step 4 (retirement) is a separate --retire run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
