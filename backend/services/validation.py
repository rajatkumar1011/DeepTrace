"""Reading the stored validation runs.

Two artifacts — written by ``scripts/benchmark.py`` and ``scripts/robustness.py``
— are consumed by two different surfaces: ``/api/benchmark`` (which the reviewer
panel renders) and the PDF report. They are read through one loader so the figure
shown on screen and the figure printed in a report can never come from different
logic, only from different renderings of the same file.

Nothing in this module computes a metric. If an artifact is absent, that absence
is returned as a reason string and the command that would produce it — never as a
zero, which would read as a measured result of zero.
"""

import json
import os

from paths import BENCHMARK_DIR

METRICS_FILENAME = "latest.json"
ROBUSTNESS_FILENAME = "robustness.json"

# The commands are part of the payload rather than hard-coded into each surface,
# so a reviewer looking at a "not measured" block is told how to measure it.
METRICS_COMMAND = "python scripts/benchmark.py"
ROBUSTNESS_COMMAND = "python scripts/robustness.py"

METRICS_ABSENT = (
    "No labelled evaluation has been run in this environment. Run scripts/benchmark.py "
    "against a labelled dataset to produce precision, recall, F1 and false-positive rate. "
    "DeepTrace does not ship pre-computed accuracy figures."
)
ROBUSTNESS_ABSENT = (
    "No robustness evaluation has been run in this environment. Run scripts/robustness.py "
    "to measure how far scores move under compression, messaging re-upload and "
    "screen-recording degradation. It needs no labelled data, only media and ffmpeg."
)

BOUNDARY = (
    "Labelled metrics say how often the detector is right on a dataset. Robustness says "
    "how much its score moves when the same file is degraded. Neither is a claim about a "
    "specific case, and neither is produced by anything other than running the real "
    "pipeline on this machine."
)


def _load(path: str, absent_reason: str) -> dict:
    """Read one stored run. The returned ``available`` flag is the loader's own.

    ``available`` deliberately overrides anything in the file: it means "a stored
    run was found and parsed here", which is a fact about this machine that only
    the loader can establish.
    """
    if not os.path.isfile(path):
        return {"available": False, "reason": absent_reason}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as error:
        return {"available": False,
                "reason": f"The stored file could not be read: {error}"}
    if not isinstance(payload, dict):
        return {"available": False,
                "reason": "The stored file is not a validation record and was ignored."}
    return {**payload, "available": True}


def load_metrics() -> dict:
    """The last labelled evaluation, or an honest statement that there is none."""
    return _load(os.path.join(BENCHMARK_DIR, METRICS_FILENAME), METRICS_ABSENT)


def load_robustness() -> dict:
    """The last paired degradation run, or an honest statement that there is none."""
    return _load(os.path.join(BENCHMARK_DIR, ROBUSTNESS_FILENAME), ROBUSTNESS_ABSENT)
