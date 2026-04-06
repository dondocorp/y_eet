"""
Terminal reporter — uses Rich for structured, readable output.

Produces:
  1. Live progress bar + real-time RPS counter during the run
  2. Per-endpoint summary table at end of run
  3. Mesh validation results table
  4. Pass/fail evaluation panel
  5. JSON report file
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn, Progress, SpinnerColumn, TaskID,
    TextColumn, TimeElapsedColumn, TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

from .evaluator import EvaluationResult, Verdict
from .mesh import MeshCheckResult, CheckStatus
from .metrics import MetricsCollector

console = Console()


class Reporter:

    def __init__(self, duration_seconds: int, json_path: str = "report.json") -> None:
        self._duration = duration_seconds
        self._json_path = json_path
        self._start_time = time.monotonic()
        self._progress: Optional[Progress] = None
        self._task_id: Optional[TaskID] = None

    # ── Live progress ─────────────────────────────────────────────────────────

    def start_progress(self) -> None:
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            TextColumn("{task.fields[rps]:.1f} rps"),
            console=console,
            transient=False,
        )
        self._task_id = self._progress.add_task(
            "Generating traffic", total=self._duration, rps=0.0
        )
        self._progress.start()

    def update_progress(self, elapsed: float, rps: float) -> None:
        if self._progress and self._task_id is not None:
            self._progress.update(
                self._task_id,
                completed=min(elapsed, self._duration),
                rps=rps,
            )

    def stop_progress(self) -> None:
        if self._progress:
            self._progress.stop()

    # ── Summary tables ────────────────────────────────────────────────────────

    def print_summary(
        self,
        metrics: MetricsCollector,
        mesh_results: Optional[list[MeshCheckResult]] = None,
        evaluation: Optional[EvaluationResult] = None,
    ) -> None:
        snap = metrics.snapshot()

        console.print()
        console.rule("[bold]Yeet Platform — Synthetic Traffic Report", style="blue")

        # ── Endpoint metrics table ────────────────────────────────────────────
        table = Table(
            title=f"Endpoint Metrics  ({metrics.total()} total requests, {metrics.rps:.1f} rps avg)",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Endpoint", style="dim", min_width=36)
        table.add_column("Reqs", justify="right")
        table.add_column("Success%", justify="right")
        table.add_column("p50ms", justify="right")
        table.add_column("p95ms", justify="right")
        table.add_column("p99ms", justify="right")
        table.add_column("Timeouts", justify="right")
        table.add_column("Retried", justify="right")
        table.add_column("Idem Hits", justify="right")
        table.add_column("Via Istio%", justify="right")

        for ep_name in sorted(snap.keys()):
            em = snap[ep_name]
            sr = em.success_rate
            color = "green" if sr >= 0.99 else "yellow" if sr >= 0.95 else "red"
            table.add_row(
                ep_name,
                str(em.total),
                f"[{color}]{sr:.1%}[/{color}]",
                f"{em.latency.p50:.0f}",
                f"{em.latency.p95:.0f}",
                f"{em.latency.p99:.0f}",
                str(em.timeout),
                f"{em.retried}",
                str(em.idempotency_hits),
                f"{em.via_istio / em.total * 100:.0f}%" if em.total else "-",
            )
        console.print(table)

        # ── Status code breakdown ─────────────────────────────────────────────
        sc_table = Table(title="Status Code Distribution", box=box.SIMPLE)
        sc_table.add_column("Endpoint", style="dim")
        sc_table.add_column("2xx", justify="right", style="green")
        sc_table.add_column("4xx", justify="right", style="yellow")
        sc_table.add_column("5xx", justify="right", style="red")
        sc_table.add_column("Timeout/Conn", justify="right", style="magenta")

        for ep_name in sorted(snap.keys()):
            em = snap[ep_name]
            sc_table.add_row(
                ep_name,
                str(em.success),
                str(em.client_error),
                str(em.server_error),
                str(em.timeout),
            )
        console.print(sc_table)

        # ── Canary distribution ───────────────────────────────────────────────
        all_canary: dict[str, int] = {}
        for em in snap.values():
            for v, cnt in em.canary_hits.items():
                all_canary[v] = all_canary.get(v, 0) + cnt
        if all_canary:
            total_canary = sum(all_canary.values())
            c_table = Table(title="Canary Version Distribution", box=box.SIMPLE)
            c_table.add_column("Version")
            c_table.add_column("Requests", justify="right")
            c_table.add_column("Weight", justify="right")
            for v, cnt in sorted(all_canary.items(), key=lambda x: -x[1]):
                c_table.add_row(v, str(cnt), f"{cnt/total_canary:.1%}")
            console.print(c_table)

        # ── Mesh validation results ───────────────────────────────────────────
        if mesh_results:
            m_table = Table(title="Mesh Validation Results", box=box.ROUNDED)
            m_table.add_column("Check", style="dim")
            m_table.add_column("Status", justify="center")
            m_table.add_column("Message")

            status_styles = {
                CheckStatus.PASS: "green",
                CheckStatus.WARN: "yellow",
                CheckStatus.FAIL: "red",
                CheckStatus.SKIP: "dim",
            }
            for mr in mesh_results:
                style = status_styles.get(mr.status, "white")
                m_table.add_row(
                    mr.name.replace("_", " ").title(),
                    f"[{style}]{mr.status.value}[/{style}]",
                    mr.message,
                )
            console.print(m_table)

        # ── Pass/fail evaluation ──────────────────────────────────────────────
        if evaluation:
            self._print_evaluation(evaluation)

    def _print_evaluation(self, ev: EvaluationResult) -> None:
        style_map = {
            Verdict.PASS: "bold green",
            Verdict.WARN: "bold yellow",
            Verdict.FAIL: "bold red",
            Verdict.INSUFFICIENT_DATA: "dim",
        }
        style = style_map.get(ev.verdict, "white")

        ev_table = Table(box=box.MINIMAL_DOUBLE_HEAD, show_header=True, header_style="bold")
        ev_table.add_column("Check", min_width=40)
        ev_table.add_column("Verdict", justify="center")
        ev_table.add_column("Detail")

        v_styles = {
            Verdict.PASS: "green", Verdict.WARN: "yellow",
            Verdict.FAIL: "red", Verdict.INSUFFICIENT_DATA: "dim",
        }
        for c in ev.checks:
            vs = v_styles.get(c.verdict, "white")
            detail = c.message
            if c.observed is not None and c.threshold is not None:
                detail = f"{detail}  ({c.observed:.2f}{c.unit} / {c.threshold:.2f}{c.unit})"
            ev_table.add_row(
                c.name,
                f"[{vs}]{c.verdict.value}[/{vs}]",
                detail,
            )

        summary_text = (
            f"[{style}]{ev.verdict.value}[/{style}]  "
            f"confidence={ev.confidence:.0f}%  "
            f"exit_code={ev.exit_code}  "
            f"fails={len(ev.fails())}  warns={len(ev.warns())}"
        )
        console.print(Panel(
            ev_table,
            title=f"[bold]Evaluation: {summary_text}",
            border_style=style,
        ))

    # ── JSON report ───────────────────────────────────────────────────────────

    def write_json_report(
        self,
        metrics: MetricsCollector,
        mesh_results: Optional[list[MeshCheckResult]] = None,
        evaluation: Optional[EvaluationResult] = None,
        chaos_results: Optional[list] = None,
    ) -> None:
        snap = metrics.snapshot()
        report = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_seconds": metrics.elapsed_seconds,
            "total_requests": metrics.total(),
            "rps_average": round(metrics.rps, 2),
            "global_error_rate_pct": round(metrics.global_error_rate() * 100, 2),
            "global_p99_ms": round(metrics.global_p99(), 1),
            "endpoints": {},
            "mesh": [],
            "chaos": [],
            "evaluation": {},
        }

        for ep_name, em in snap.items():
            report["endpoints"][ep_name] = {
                "total": em.total,
                "success_rate_pct": round(em.success_rate * 100, 2),
                "error_rate_pct": round(em.error_rate * 100, 2),
                "p50_ms": round(em.latency.p50, 1),
                "p95_ms": round(em.latency.p95, 1),
                "p99_ms": round(em.latency.p99, 1),
                "timeouts": em.timeout,
                "retried": em.retried,
                "avg_attempt_count": round(em.avg_attempt_count, 3),
                "idempotency_hits": em.idempotency_hits,
                "auth_failures": em.auth_failures,
                "via_istio_pct": round(em.via_istio / em.total * 100, 1) if em.total else 0,
                "status_codes": dict(em.status_codes),
                "canary_distribution": dict(em.canary_hits),
                "trace_propagation_rate_pct": round(em.trace_propagation_rate * 100, 1),
            }

        if mesh_results:
            report["mesh"] = [
                {"check": mr.name, "status": mr.status.value, "message": mr.message,
                 "details": mr.details}
                for mr in mesh_results
            ]

        if chaos_results:
            report["chaos"] = [
                {"scenario": cr.scenario, "passed": cr.passed,
                 "expected": cr.expected_status, "got": cr.status_code, "note": cr.note}
                for cr in chaos_results
            ]

        if evaluation:
            report["evaluation"] = evaluation.as_dict()

        path = Path(self._json_path)
        path.write_text(json.dumps(report, indent=2))
        console.print(f"\n[dim]JSON report written to {path.resolve()}[/dim]")
