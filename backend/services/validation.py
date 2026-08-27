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
import sys

from paths import BENCHMARK_DIR, repo_relative

METRICS_FILENAME = "latest.json"
ROBUSTNESS_FILENAME = "robustness.json"

# The commands are part of the payload rather than hard-coded into each surface,
# so a reviewer looking at a "not measured" block is told how to measure it.
#
# They name an interpreter rather than bare ``python`` on purpose. The harness
# only measures the real detector on an interpreter that has this backend's model
# dependencies installed; on a machine that also has a system Python on PATH,
# bare ``python`` resolves to that one instead, the harness falls back to a
# lightweight heuristic, and the run finishes in seconds with complete, plausible
# and meaningless figures. Printing that command in a report would be an
# instruction to produce exactly the number this section exists to rule out.
#
# The interpreter is derived from the process actually serving this request,
# which is the one a reviewer needs, and passed through ``repo_relative`` so an
# absolute filesystem path is never printed into an API response or a PDF. That
# helper returns None for an interpreter installed outside the repository, where
# it cannot be named without leaking the operator's directory layout; that case
# is described instead of named.
_INTERPRETER = repo_relative(sys.executable) or "<this backend's own interpreter>"

METRICS_COMMAND = f"{_INTERPRETER} scripts/benchmark.py"
ROBUSTNESS_COMMAND = f"{_INTERPRETER} scripts/robustness.py"
FETCH_COMMAND = f"{_INTERPRETER} scripts/fetch_eval_data.py"

INTERPRETER_NOTE = (
    "Run from the repository root, and with that interpreter rather than whatever `python` "
    "resolves to on the PATH: only the backend's own environment has the detection models "
    "installed. Run elsewhere, the accuracy harness refuses to write figures at all and exits "
    "non-zero, and the robustness harness states in its own caveats that the scores came from a "
    "heuristic fallback — so a run on the wrong interpreter is visible rather than silent."
)

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


def harness_commands() -> dict:
    """How to produce these figures, for whichever surface is rendering them.

    The commands are computed here rather than written into each surface because
    they encode a correctness condition, not a convenience: run on the wrong
    interpreter, the harness measures a heuristic fallback instead of the real
    detector. A UI that hard-coded its own copy of the path would keep printing
    ``backend/venv/...`` on a machine whose environment lives somewhere else, and
    a reviewer following that instruction would produce a number that looks like a
    measurement and is not one. One definition, rendered in both places.
    """
    return {
        "metrics_command": METRICS_COMMAND,
        "robustness_command": ROBUSTNESS_COMMAND,
        "fetch_command": FETCH_COMMAND,
        "interpreter_note": INTERPRETER_NOTE,
    }
