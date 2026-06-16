import json

from open_notebook.research import researcher_service as svc


def _job(job_id: str, status: str, timestamp: str) -> svc.ResearchJob:
    return svc.ResearchJob(
        id=job_id,
        query="test query",
        report_type="research_report",
        status=status,
        progress=status,
        created_at=timestamp,
        updated_at=timestamp,
        user_id="m24409",
    )


def test_get_job_refreshes_stale_memory_from_disk(tmp_path, monkeypatch):
    jobs_file = tmp_path / "research_jobs.json"
    monkeypatch.setattr(svc, "_jobs_file", str(jobs_file))
    svc._jobs.clear()

    older = "2026-06-16T10:00:00+00:00"
    newer = "2026-06-16T10:01:00+00:00"
    svc._jobs["job-1"] = _job("job-1", "running", older)
    disk_job = _job("job-1", "completed", newer)
    jobs_file.write_text(
        json.dumps({"job-1": disk_job.model_dump()}),
        encoding="utf-8",
    )

    loaded = svc._get_job("job-1")

    assert loaded is not None
    assert loaded.status == "completed"
    assert svc._jobs["job-1"].status == "completed"


def test_save_jobs_does_not_overwrite_newer_terminal_disk_state(tmp_path, monkeypatch):
    jobs_file = tmp_path / "research_jobs.json"
    monkeypatch.setattr(svc, "_jobs_file", str(jobs_file))
    svc._jobs.clear()

    older = "2026-06-16T10:00:00+00:00"
    newer = "2026-06-16T10:01:00+00:00"
    disk_job = _job("job-1", "completed", newer)
    jobs_file.write_text(
        json.dumps({"job-1": disk_job.model_dump()}),
        encoding="utf-8",
    )
    svc._jobs["job-1"] = _job("job-1", "running", older)

    svc._save_jobs()

    data = json.loads(jobs_file.read_text(encoding="utf-8"))
    assert data["job-1"]["status"] == "completed"


def test_get_job_marks_stale_active_job_failed(tmp_path, monkeypatch):
    jobs_file = tmp_path / "research_jobs.json"
    monkeypatch.setattr(svc, "_jobs_file", str(jobs_file))
    monkeypatch.setattr(svc, "RESEARCH_JOB_STALE_SECONDS", 1)
    svc._jobs.clear()

    stale_time = "2020-01-01T00:00:00+00:00"
    disk_job = _job("job-1", "running", stale_time)
    jobs_file.write_text(
        json.dumps({"job-1": disk_job.model_dump()}),
        encoding="utf-8",
    )

    loaded = svc._get_job("job-1")

    assert loaded is not None
    assert loaded.status == "failed"
    assert "timed out" in (loaded.error or "")


def test_running_job_persist_survives_poll_disk_refresh(tmp_path, monkeypatch):
    jobs_file = tmp_path / "research_jobs.json"
    monkeypatch.setattr(svc, "_jobs_file", str(jobs_file))
    # Disable the stale-job watchdog so the fixed past timestamps below are not
    # interpreted as "stalled" relative to the real wall clock — this test is
    # about persist ordering, not the staleness heuristic.
    monkeypatch.setattr(svc, "RESEARCH_JOB_STALE_SECONDS", 10**9)
    svc._jobs.clear()
    svc._running_jobs.clear()

    started = "2026-06-16T10:00:00+00:00"
    live_job = _job("job-1", "running", started)
    svc._jobs["job-1"] = live_job
    svc._running_jobs["job-1"] = live_job
    svc._persist_job(live_job)

    loaded = svc._get_job("job-1")
    assert loaded is live_job

    # Simulate the background task advancing after a poll. The live object must
    # remain authoritative, otherwise _save_jobs would write the stale snapshot.
    live_job.status = "completed"
    live_job.progress = "Concluído"
    live_job.progress_pct = 100
    live_job.updated_at = "2026-06-16T10:02:00+00:00"
    svc._persist_job(live_job)

    data = json.loads(jobs_file.read_text(encoding="utf-8"))
    assert data["job-1"]["status"] == "completed"
    assert data["job-1"]["progress"] == "Concluído"
