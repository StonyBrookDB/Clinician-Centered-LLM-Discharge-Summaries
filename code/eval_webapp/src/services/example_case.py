"""Publication build: legacy import shim with no example encounters."""

from __future__ import annotations


EXAMPLE_ENCOUNTER_NUMBER = -999999
EXAMPLE_ENCOUNTER_NUMBERS: set[int] = set()


def get_example_encounter_number() -> int:
    return EXAMPLE_ENCOUNTER_NUMBER


def is_example_encounter(encounter_number: int | str) -> bool:
    return False


def is_example_read_only(encounter_number: int | str) -> bool:
    return False


def get_example_case_root():
    raise RuntimeError("Separate example encounters are not included in the publication build.")


def get_example_case_assets_dir(encounter_number: int | str = EXAMPLE_ENCOUNTER_NUMBER):
    raise RuntimeError("Separate example encounters are not included in the publication build.")


def get_example_case_fixture_path():
    raise RuntimeError("Separate example encounters are not included in the publication build.")
