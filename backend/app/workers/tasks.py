import app.workers.broker  # noqa: F401  (registra o broker)
import dramatiq

from app.services.ingest import run_ingest


@dramatiq.actor(queue_name="ingest", max_retries=0)
def ingest_asset(job_id: str) -> None:
    run_ingest(job_id)


@dramatiq.actor(queue_name="transcribe", max_retries=0, time_limit=4 * 3600 * 1000)
def transcribe_asset(job_id: str) -> None:
    from app.services.transcription import run_transcribe
    run_transcribe(job_id)


@dramatiq.actor(queue_name="analyze", max_retries=0)
def analyze_project(job_id: str) -> None:
    from app.services.analysis import run_analysis
    run_analysis(job_id)


@dramatiq.actor(queue_name="render", max_retries=0, time_limit=6 * 3600 * 1000)
def render_timeline(job_id: str) -> None:
    from app.services.render import run_render
    run_render(job_id)
