from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import cv2
import numpy as np

from miraaj_api import database, main
from miraaj_api.models import Job, JobOutbox, ProjectAnalysis, ProjectPlan
from miraaj_api.storage import LocalStorageProvider


def test_project_creation_analysis_and_target_duration_api(monkeypatch, tmp_path: Path):
    video_path = tmp_path / "valid.mp4"
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 24, (64, 64))
    assert writer.isOpened()
    for _ in range(24):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "storage", LocalStorageProvider(tmp_path))

    def override_db():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    main.app.dependency_overrides[database.get_db] = override_db
    try:
        with TestClient(main.app) as client:
            created = client.post(
                "/api/projects",
                data={
                    "name": "Camera notes",
                    "script_text": "Imagine a useful camera. It can help people tell a clearer story.",
                },
                files={"video": ("take.mp4", video_path.read_bytes(), "video/mp4")},
            )
            assert created.status_code == 201, created.text
            project = created.json()
            assert project["analysis"]["script_analysis"]["sentence_count"] == 2
            assert project["analysis"]["status"] == "queued"
            assert project["analysis"]["duration_estimate"]["recommended_duration"] > 0
            assert Path(project["source_video_path"]).read_bytes() == video_path.read_bytes()
            with sessions() as session:
                assert session.scalar(select(JobOutbox)).dispatched_at is None

            project_read = client.get(f"/api/projects/{project['id']}")
            assert project_read.status_code == 200
            assert project_read.json()["script_text"].startswith("Imagine")

            chosen = client.put(
                f"/api/projects/{project['id']}/target-duration", json={"seconds": 70}
            )
            assert chosen.status_code == 200
            assert chosen.json()["target_duration"] == 70
            assert chosen.json()["duration_fit"]["status"] == "script_shorter_than_target"

            fetched = client.get(f"/api/projects/{project['id']}/analysis")
            assert fetched.status_code == 200
            assert fetched.json()["target_duration"] == 70
            planned = client.post(f"/api/projects/{project['id']}/plan")
            assert planned.status_code == 409

            with sessions() as session:
                analysis = session.get(ProjectAnalysis, project["id"])
                analysis.status = "failed"
                analysis.error = "temporary extraction error"
                session.commit()
            retried = client.post(f"/api/projects/{project['id']}/analysis/retry")
            assert retried.status_code == 202, retried.text
            assert retried.json()["analysis"]["status"] == "queued"
            assert retried.json()["analysis"]["error"] is None
            with sessions() as session:
                retry_jobs = session.scalars(
                    select(Job).where(Job.project_id == project["id"], Job.kind == "media_analysis")
                ).all()
                assert len(retry_jobs) == 2
                assert all(job.status == "queued" for job in retry_jobs)
                outboxes = session.scalars(select(JobOutbox)).all()
                assert len(outboxes) == 2

            rejected_retry = client.post(f"/api/projects/{project['id']}/analysis/retry")
            assert rejected_retry.status_code == 409

            class FakeSceneProvider:
                def generate(self, context, schema, repair=None):
                    import json

                    return json.dumps(
                        {
                            "id": "model-changed-id",
                            "type": "talking_head_zoom",
                            "source_start": 99,
                            "source_end": 100,
                            "timeline_start": 40,
                            "duration": 1,
                            "layer": "overlay",
                            "channel": "other",
                            "crop": {"mode": "close", "scale": 1.08},
                            "rationale": "A tighter presentation",
                        }
                    )

            with sessions() as session:
                analysis = session.get(ProjectAnalysis, project["id"])
                analysis.status = "ready"
                analysis.video_metadata = {"duration_seconds": 1}
                analysis.video_analysis = {"face_analysis": {"samples": []}}
                original_scene = {
                    "id": "scene_001",
                    "type": "talking_head",
                    "source_start": 0,
                    "source_end": 1,
                    "timeline_start": 0,
                    "duration": 1,
                    "layer": "base",
                    "channel": "video",
                    "crop": {"mode": "fit", "scale": 1},
                }
                session.add(
                    ProjectPlan(
                        project_id=project["id"],
                        status="ready",
                        provider="gemini",
                        edit_plan={"version": 1, "duration": 1, "scenes": [original_scene]},
                        timeline={"duration": 1, "scenes": [original_scene]},
                    )
                )
                session.commit()
            monkeypatch.setattr(
                main,
                "configured_director",
                lambda: type("Director", (), {"provider": FakeSceneProvider()})(),
            )
            regenerated = client.post(
                f"/api/projects/{project['id']}/scenes/scene_001/regenerate",
                json={"instruction": "Use a closer talking head shot."},
            )
            assert regenerated.status_code == 200, regenerated.text
            regenerated_scene = regenerated.json()["edit_plan"]["scenes"][0]
            assert regenerated_scene["id"] == "scene_001"
            assert regenerated_scene["type"] == "talking_head"
            assert regenerated_scene["crop"]["mode"] == "close"
            assert regenerated_scene["source_start"] == 0
            assert regenerated_scene["source_end"] == 1
            assert regenerated_scene["timeline_start"] == 0
    finally:
        main.app.dependency_overrides.clear()
        database.Base.metadata.drop_all(engine)
        engine.dispose()
