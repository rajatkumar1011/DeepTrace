"""The validation-artifact loader.

These assertions exist because of one rule the project cannot break: DeepTrace
must never present a number it did not measure. Both surfaces that report
accuracy — /api/benchmark and the PDF report — read through this loader, so the
absence path is the one that has to be provably honest. A loader that returned an
empty metrics dict instead of a reason would let a renderer print 0.000 where
"not measured" belongs, and nothing downstream could tell the difference.
"""

import json
import os

import pytest

from services import validation


@pytest.fixture
def benchmark_dir(tmp_path, monkeypatch):
    """Point the loader at an empty throwaway directory."""
    monkeypatch.setattr(validation, "BENCHMARK_DIR", str(tmp_path))
    return tmp_path


def _write(directory, name, payload):
    path = os.path.join(str(directory), name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


def test_absent_metrics_report_a_reason_and_no_figures(benchmark_dir):
    result = validation.load_metrics()

    assert result["available"] is False
    assert "scripts/benchmark.py" in result["reason"]
    # The absence must not be dressed up as an empty result: a caller that
    # reached for a metric here has to find nothing at all, not a zero.
    assert "manipulation_detection" not in result
    assert "operating_point" not in result


def test_absent_robustness_reports_a_reason_and_no_figures(benchmark_dir):
    result = validation.load_robustness()

    assert result["available"] is False
    assert "scripts/robustness.py" in result["reason"]
    assert "visual" not in result
    assert "audio" not in result


def test_stored_run_is_returned_verbatim(benchmark_dir):
    _write(benchmark_dir, validation.METRICS_FILENAME,
           {"generated_at_utc": "2026-01-01T00:00:00+00:00",
            "manipulation_detection": {"evaluated": 24}})

    result = validation.load_metrics()

    assert result["available"] is True
    assert result["generated_at_utc"] == "2026-01-01T00:00:00+00:00"
    assert result["manipulation_detection"]["evaluated"] == 24


def test_unreadable_file_is_reported_not_raised(benchmark_dir):
    path = os.path.join(str(benchmark_dir), validation.ROBUSTNESS_FILENAME)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{not json")

    result = validation.load_robustness()

    assert result["available"] is False
    assert "could not be read" in result["reason"]


def test_non_object_payload_is_refused(benchmark_dir):
    _write(benchmark_dir, validation.METRICS_FILENAME, [1, 2, 3])

    result = validation.load_metrics()

    assert result["available"] is False
    assert "not a validation record" in result["reason"]


def test_file_cannot_claim_its_own_availability(benchmark_dir):
    """``available`` describes this machine, so the loader's verdict wins.

    A stored artifact carrying ``available: false`` would otherwise make a run
    that is present on disk report itself as missing, and one carrying
    ``available: true`` would survive a future change to the absence path.
    """
    _write(benchmark_dir, validation.METRICS_FILENAME,
           {"available": False, "manipulation_detection": {"evaluated": 7}})

    result = validation.load_metrics()

    assert result["available"] is True
    assert result["manipulation_detection"]["evaluated"] == 7


def test_the_two_runs_are_independent(benchmark_dir):
    """One harness having run says nothing about the other."""
    _write(benchmark_dir, validation.ROBUSTNESS_FILENAME, {"threshold": 0.5})

    assert validation.load_robustness()["available"] is True
    assert validation.load_metrics()["available"] is False


def test_boundary_text_separates_the_two_claims():
    """The boundary sentence is the one piece of copy both surfaces must share."""
    assert "how often the detector is right" in validation.BOUNDARY
    assert "how much its score moves" in validation.BOUNDARY


def test_harness_commands_name_an_interpreter_not_bare_python():
    """§34: the printed command must not be able to produce a fallback figure.

    Both commands are shown to a reviewer as "how to produce it", including in the
    PDF report. On a machine that also carries a system Python on the PATH, bare
    ``python`` resolves to the interpreter without the detection models, and the
    harness then measures a lightweight heuristic — a complete, plausible and
    meaningless result. Printing that command would be an instruction to produce
    exactly the number this section exists to rule out.
    """
    for command in (validation.METRICS_COMMAND, validation.ROBUSTNESS_COMMAND):
        assert not command.startswith("python ")
        # Either a repository-relative interpreter, or a placeholder saying which
        # one is meant — never a guess and never the PATH default.
        assert command.startswith("backend/venv/") or command.startswith("<")


def test_harness_commands_do_not_leak_an_absolute_path(monkeypatch):
    """§24: an API response and a PDF must not carry the operator's directory layout.

    The interpreter is derived from the running process, so on a machine whose
    Python lives outside the repository the honest answer is to describe it rather
    than name it. Reloading the module under a patched ``sys.executable`` is what
    exercises that branch, since the command is computed at import time.
    """
    import importlib
    import sys

    monkeypatch.setattr(sys, "executable", r"C:\Users\someone\AppData\Python\python.exe")
    reloaded = importlib.reload(validation)
    try:
        assert "someone" not in reloaded.METRICS_COMMAND
        assert "AppData" not in reloaded.METRICS_COMMAND
        assert reloaded.METRICS_COMMAND.startswith("<this backend's own interpreter>")
    finally:
        # Restore the real module state for every test that runs after this one.
        monkeypatch.undo()
        importlib.reload(validation)


def test_interpreter_note_states_what_a_wrong_run_does():
    """The note must describe the two harnesses' actual behaviour, not a wish.

    ``benchmark.py`` exits non-zero on a fallback; ``robustness.py`` publishes the
    fallback in its own caveats instead. Wording that promised the same behaviour
    from both would be a claim the code does not honour.
    """
    assert "exits" in validation.INTERPRETER_NOTE
    assert "caveats" in validation.INTERPRETER_NOTE
    assert "`python`" in validation.INTERPRETER_NOTE
<<<<<<< Updated upstream


def test_harness_commands_are_offered_as_one_payload():
    """Both surfaces must read the command, not compose their own.

    The UI previously hard-coded ``backend/venv/Scripts/python.exe`` into four
    "not measured" blocks. On a machine whose environment lives elsewhere that
    instruction is wrong, and following it on an interpreter without the models
    produces a fallback figure that looks like a measurement. Shipping the command
    in the payload is what makes one definition serve both renderings.
    """
    commands = validation.harness_commands()

    assert set(commands) == {"metrics_command", "robustness_command",
                             "fetch_command", "interpreter_note"}
    assert commands["metrics_command"] == validation.METRICS_COMMAND
    assert commands["robustness_command"] == validation.ROBUSTNESS_COMMAND
    assert commands["fetch_command"] == validation.FETCH_COMMAND
    assert commands["interpreter_note"] == validation.INTERPRETER_NOTE
    for key in ("metrics_command", "robustness_command", "fetch_command"):
        assert not commands[key].startswith("python ")
=======
>>>>>>> Stashed changes
