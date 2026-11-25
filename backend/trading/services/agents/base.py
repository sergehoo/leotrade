from __future__ import annotations

from django.utils import timezone

from trading.models import AgentRun


class BaseAgentService:
    agent_type = None

    @classmethod
    def start_run(cls, input_payload=None, user=None, market_scan_run=None):
        return AgentRun.objects.create(
            agent_type=cls.agent_type,
            status="RUNNING",
            user=user,
            market_scan_run=market_scan_run,
            input_payload=input_payload or {},
            started_at=timezone.now(),
        )

    @classmethod
    def finish_run(cls, run: AgentRun, output_payload=None, notes="", error_message="", success=True):
        finished = timezone.now()
        run.finished_at = finished
        run.runtime_ms = int((finished - run.started_at).total_seconds() * 1000)
        run.status = "SUCCEEDED" if success else "FAILED"
        run.output_payload = output_payload or {}
        run.notes = notes
        run.error_message = error_message
        run.save(update_fields=[
            "finished_at", "runtime_ms", "status",
            "output_payload", "notes", "error_message", "updated_at"
        ])
        return run