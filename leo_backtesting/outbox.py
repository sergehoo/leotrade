from core.outbox import register_outbox_handler
from leo_backtesting.event_topics import BACKTEST_RUN_REQUESTED


@register_outbox_handler(BACKTEST_RUN_REQUESTED)
def enqueue_backtest_run(event):
    from leo_backtesting.tasks import run_backtest_task

    run_backtest_task.apply_async(
        args=(int(event.payload["backtest_run_id"]),),
        task_id=f"outbox-{event.event_id}",
    )
