"""T28 -- safe P703 zone/model evidence pack.

Pure domain tests, no database, no Excel file. Deterministic normalisation
plus the flags task brief §4.2 requires the evidence pack to be able to
raise. Ported verbatim from `.superpowers/sdd/2026-09-21-wavescan-p703-
completion/task-1-brief.md` Step 1 (`AGENTS.md` rule 4: this is the spec's
own literal test text, not retyped from memory).
"""

from app.domain.references import normalise_alias
from app.domain.zone_audit import (
    FLAG_DUP_RAW,
    FLAG_FVL_ROOF,
    FLAG_FVL_TGATE,
    FLAG_NOT_32,
    FLAG_SAP_TAILGATE,
    FLAG_TWO_CANDIDATES,
    build_walk,
    forbidden_keys_present,
    sha256_bytes,
)


def test_normalise_matches_cleaner_key():
    assert normalise_alias("  25TGATE  ") == "25tgate"


def test_sap_tailgate_wording_is_flagged():
    walk = build_walk(
        ["01RHS Hood Rr28", "17LHS TG Top12", "18LHS TG Bottom12", "20RHS TG Top15"]
        + [f"z{i}" for i in range(28)]
    )
    assert FLAG_SAP_TAILGATE in walk["flags"] or any(
        FLAG_SAP_TAILGATE in row["flags"] for row in walk["labels"]
    )


def test_fvl_roof_and_tgate_are_flagged():
    labels = [f"{i}HOOD" for i in range(1, 11)] + ["11ROOF", "12X", "13X", "14ROOF"]
    labels += [f"p{i}" for i in range(15, 25)] + ["25TGATE"] + [f"q{i}" for i in range(26, 33)]
    walk = build_walk(labels)
    flags = walk["flags"] + [f for row in walk["labels"] for f in row["flags"]]
    assert FLAG_FVL_ROOF in flags
    assert FLAG_FVL_TGATE in flags


def test_duplicate_normalised_label_is_flagged():
    walk = build_walk(["1HOOD", "1hood"] + [f"n{i}" for i in range(30)])
    assert FLAG_DUP_RAW in walk["flags"]
    assert walk["unique_normalised_count"] != 32 or FLAG_DUP_RAW in walk["flags"]


def test_non_32_walk_is_flagged():
    walk = build_walk([f"z{i}" for i in range(31)])
    assert FLAG_NOT_32 in walk["flags"]
    assert walk["unique_normalised_count"] == 31


def test_two_raw_labels_for_one_candidate_flag():
    walk = build_walk(["LT Tailgate", "LT Tailagte"] + [f"z{i}" for i in range(30)])
    assert FLAG_TWO_CANDIDATES in walk["flags"] or any(
        FLAG_TWO_CANDIDATES in row["flags"] for row in walk["labels"]
    )


def test_hash_is_64_hex_and_artifacts_forbid_secrets():
    digest = sha256_bytes(b"fixture-only")
    assert len(digest) == 64 and digest == digest.lower()
    sample = {"serial_no": "ABC", "cf": 12.3, "named_owner": "Pat"}
    assert forbidden_keys_present(sample) is True
