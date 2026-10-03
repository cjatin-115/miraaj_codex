# Miraaj

Miraaj is a local-first personal video studio for turning a script and talking-head recording into an edited vertical short. Its V1 pipeline accepts a project, analyzes the script and recording, builds a deterministic edit plan, renders with Remotion, and validates the finished MP4.

## Current pipeline

1. Upload is stored unchanged as `<project-id>_source.<ext>`.
2. The API persists the project, script analysis, media job, and a durable database outbox record. The worker publishes pending outbox jobs to Redis and consumes them.
3. The local worker uses FFprobe for metadata, FFmpeg for a proxy/audio/representative frames, OpenCV for framing and scene-change samples, and faster-whisper for word-timestamped local transcription.
4. Video analysis artifacts are cached by SHA-256 of the original video; script analysis is cached by a separate script-content hash. Re-analysis reuses video results and copies project-named artifacts into the new project directory.
5. The web page shows video and script analysis, the estimated range, warnings for targets that need content changes, and lets the user save the selected target before opening its planning summary.
6. The deterministic AI Director and `TimelineBuilder` turn the recording and word timestamps into a schema-validated, frame-aligned edit timeline. Uploaded image/video assets are validated and must exist before the timeline can reference them.
7. A queued worker copies the original recording and referenced assets into the Remotion renderer, composes each scene from timeline JSON, and renders H.264/AAC MP4. The worker persists actual rendering and encoding progress, then decodes and checks the finished video before marking it complete. Original camera audio is preserved with volume and short fades.

The renderer uses reusable Remotion components for talking-head layouts, word-timed captions, text, browser/code/graph/comparison/product visuals, and scene transitions. Text and graphics render at the selected output resolution. The 4K profile outputs native 2160x3840 graphics; camera pixels are never described as native 4K if the source is lower resolution.

## Requirements

- Node.js 20 or newer
- Python 3.11 or newer
- Docker Desktop with Compose
- FFmpeg and FFprobe on `PATH` for analysis, validation and preprocessing; Remotion uses its pinned compositor dependencies
- PostgreSQL and Redis (started with Compose below)
- Optional Python media dependencies: OpenCV, NumPy, faster-whisper

The first faster-whisper run downloads the configured model (`WHISPER_MODEL`, default `base`) into its local model cache. Inference runs on CPU using int8. Set `WHISPER_MODEL=tiny` to reduce download size and memory use, or install a compatible CUDA/PyTorch stack separately for GPU transcription. The default `LLM_PROVIDER=local` uses Ollama and generates real model plans. Set `LLM_PROVIDER=gemini` with a Gemini API key for hosted plans; the configured Gemini model defaults to `gemini-3.8-flash`. Explicitly set `LLM_PROVIDER=mock` only for deterministic provider tests and offline pipeline checks. Image and video scenes use deterministic native components; no image-generation key is required.

## Start locally

From the repository root:

```powershell
Copy-Item .env.example .env
docker compose up -d postgres redis
```

Install API dependencies and run the API:

```powershell
cd apps/api
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,media]"
cd ../..
python -m uvicorn miraaj_api.main:app --reload --app-dir apps/api/src
```

In a second terminal, run the worker:

```powershell
python workers/video-worker/main.py
```

In a third terminal, run the web app:

```powershell
npm install
npm run dev:web
```

Open http://localhost:3000. API docs are at http://localhost:8000/docs and health is at http://localhost:8000/health. The worker must be running to complete analysis, planning, and rendering. Configure `DATABASE_URL`, `REDIS_URL`, `STORAGE_PATH`, `RENDER_OUTPUT_PATH`, `MAX_UPLOAD_MB`, `WHISPER_MODEL`, `LLM_PROVIDER`, `LLM_MODEL`, and `NEXT_PUBLIC_API_URL` in `.env`. `STORAGE_PATH` holds uploads and analysis/cache data; `RENDER_OUTPUT_PATH` holds validated MP4 output. Gemini additionally requires `GEMINI_API_KEY` and can use `GEMINI_MODEL`; local mode requires a separately installed and running Ollama server at `LOCAL_LLM_URL`.

## API

- `GET /health` — PostgreSQL, Redis, FFmpeg, and FFprobe readiness
- `POST /api/projects` — multipart `name`, `script_text`, `video`; persists script/duration analysis and queues video analysis
- `GET /api/projects` and `GET /api/projects/{project_id}` — project state
- `GET /api/projects/{project_id}/analysis` — script, media, audio, transcript, and duration analysis
- `POST /api/projects/{project_id}/analysis/retry` — requeue a failed media analysis
- `POST /api/projects/{project_id}/scenes/{scene_id}/regenerate` — regenerate one scene through the configured LLM while locking its source range, timing, and base-scene component type to protect speaker audio; the complete timeline is revalidated before saving
- `PUT /api/projects/{project_id}/target-duration` — save a positive target in seconds (up to 600)
- `POST /api/projects/{project_id}/assets` / `GET /api/projects/{project_id}/assets` — add and inspect validated visual assets
- `POST /api/projects/{project_id}/renders` — queue a `vertical_1080` or `vertical_4k` render
- `GET /api/projects/{project_id}/renders/latest` / `GET /api/renders/{render_id}` — inspect persisted render progress
- `GET /api/renders/{render_id}/file` — download the validated MP4

The API creates tables on startup for this personal V1. Analysis and director plans are kept in separate tables so the existing project/job columns remain stable. A database outbox makes project and director jobs durable while Redis is temporarily unavailable.

## AI Director and timeline

When media analysis is ready, continue from the duration selection screen to queue a Director job. By default the worker calls Ollama; it produces schema-validated EditPlan JSON and runs it through the deterministic `TimelineBuilder`. The planning page then shows the estimated and selected duration, scene list, visual density, talking-head segment count, and inspectable JSON. From there, request a render to queue the renderer worker; progress moves through queued, processing, rendering, encoding, quality check, and completed/failed. Configure `LLM_PROVIDER=gemini` (`GEMINI_API_KEY` and `GEMINI_MODEL`) for hosted plans. `MockDirector` is explicitly available only when selected for tests or offline pipeline checks.

Missing Gemini credentials or provider/network errors fail the plan job with a visible error. Invalid model JSON gets one schema-guided repair attempt, then fails safely. `STORAGE_ROOT`, `WHISPER_MODEL_SIZE`, `DIRECTOR_PROVIDER`, and `LOCAL_LLM_MODEL` remain accepted as compatibility aliases, but the `.env.example` uses the current setting names. The mock provider is for tests/offline mode and does not stand in for a live AI provider.

## Checks

```powershell
npm run test:web
npm run typecheck
npm run typecheck:renderer
npm run lint
npm --workspace apps/web run build
cd apps/api
python -m pytest tests
python -m ruff check src tests ..\..\workers\video-worker\main.py
```

Director/timeline tests use the explicitly requested MockDirector; provider repair tests exercise the provider boundary. Renderer dependencies are pinned in `apps/renderer`; run `npm run typecheck:renderer` to verify its Remotion components. Analysis and render jobs require PostgreSQL and Redis, and a complete user render requires an uploaded recording. Local renderer smoke artifacts are written under `apps/renderer/out` (ignored by Git).
