"""Uniform progress reporting for the long-running pipeline commands.

``load`` and ``update`` touch the same datasets and used to describe them in
different words, with only one of the two reporting timings or surviving a
failed step. Both now drive a ``Run``: a header, one aligned line per step, and
a summary naming whatever failed.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass

_LABEL_WIDTH = 22


@dataclass
class StepResult:
    """What a step reports back: how much it moved, and how it went.

    ``note`` qualifies the row count, such as the watermark a fetch resumed
    from. ``detail`` replaces the elapsed time in brackets where a step can say
    something more useful, such as splitting fetch from insert.
    """

    rows: int | None = None
    note: str = ""
    detail: str = ""


class Run:
    """One command's progress report, from header to summary.

    A step that raises is reported and recorded, and the next one still runs:
    the datasets are independent, so one unavailable vendor endpoint should not
    abandon the rest. ``finish`` returns the failed labels for the caller to
    turn into an exit status.
    """

    def __init__(self, command: str, scope: str, detail: str = "") -> None:
        """Print the header and start the clock."""
        self.command = command
        self.failed: list[str] = []
        self.completed = 0
        self._started = time.perf_counter()
        parts = [command, scope] + ([detail] if detail else [])
        print(f"=== {' · '.join(parts)} ===\n", flush=True)

    @contextmanager
    def step(self, label: str, action: str):
        """Run one step, printing what it is doing and then what it did."""
        print(f"{label:<{_LABEL_WIDTH}} {action} ...", flush=True)
        result = StepResult()
        started = time.perf_counter()
        try:
            yield result
        except Exception as exc:
            self.failed.append(label)
            print(
                f"{label:<{_LABEL_WIDTH}} FAILED — {type(exc).__name__}: {exc}",
                flush=True,
            )
            return
        self.completed += 1
        elapsed = result.detail or _duration(time.perf_counter() - started)
        moved = "done" if result.rows is None else f"{result.rows:,} rows written"
        note = f" {result.note}" if result.note else ""
        print(f"{label:<{_LABEL_WIDTH}} {moved}{note}  [{elapsed}]", flush=True)

    def finish(self) -> list[str]:
        """Print the summary and return the labels that failed."""
        total = self.completed + len(self.failed)
        summary = (
            f"{self.command} · {self.completed}/{total} complete · "
            f"{_duration(time.perf_counter() - self._started)}"
        )
        if self.failed:
            summary += f" · {len(self.failed)} failed: {', '.join(self.failed)}"
        print(f"\n=== {summary} ===", flush=True)
        return self.failed


def _duration(seconds: float) -> str:
    """Format an elapsed time, dropping precision as it grows."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, seconds = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"
