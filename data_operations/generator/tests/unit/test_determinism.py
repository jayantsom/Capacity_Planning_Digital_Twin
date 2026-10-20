"""Fast checks for process-independent generator identities."""

import subprocess
import sys

from data_operations.generator.rules.determinism import stable_id, stable_seed


def test_sha_seed_is_repeatable() -> None:
    """The same business key always produces the same seed."""
    assert stable_seed(42, "ERV_STK", "RAN-AAU-3564-001") == stable_seed(
        42, "ERV_STK", "RAN-AAU-3564-001"
    )
    assert stable_seed(43, "ERV_STK", "RAN-AAU-3564-001") != stable_seed(
        42, "ERV_STK", "RAN-AAU-3564-001"
    )


def test_sha_seed_matches_a_separate_process() -> None:
    """Python hash randomization cannot alter generated seeds."""
    script = (
        "from data_operations.generator.rules.determinism import stable_seed;"
        "print(stable_seed(42,'site','product','test'))"
    )
    observed = subprocess.check_output([sys.executable, "-c", script], text=True).strip()
    assert observed == str(stable_seed(42, "site", "product", "test"))


def test_stable_id_keeps_a_readable_namespace() -> None:
    assert stable_id("event", "site", "product").startswith("event-")
