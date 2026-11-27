from celery import shared_task

from apps.common import tenancy


@shared_task(name="timetracking.stop_runaway_timers")
def stop_runaway_timers() -> int:
    """Beat job: close timers that ran past the company's max_timer_hours."""
    from .services import stop_runaway_timers as run

    with tenancy.platform_context():
        return run()
