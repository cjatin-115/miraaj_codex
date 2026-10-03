# Miraaj V1 architecture

The API owns projects, queued jobs, a separate `ProjectAnalysis` record, and a durable job outbox. The API analyzes script text immediately and commits the media job with its outbox record. The video worker publishes pending records to Redis, consumes them, updates job/project state, and runs `MediaPipeline` outside the request.

`MediaPipeline` preserves the original upload, uses FFprobe for source metadata, and asks FFmpeg for a 720-pixel-wide proxy, mono 16 kHz WAV, and at most 24 evenly spaced frames. OpenCV samples face position and image-histogram changes. Audio metrics use local WAV samples; faster-whisper runs on CPU with word timestamps. A failed local transcription is recorded while the remaining media analysis can still complete. Video output artifacts are keyed by project ID, and cache manifests are keyed by source-video SHA-256. Script analysis has an independent content-hash cache.

`ScriptAnalyzer` is deterministic and local, returning statistics, likely hooks, visual-moment cues, emphasis words, and duration estimates. The target-duration endpoint persists the user's chosen value and reports when it falls outside the natural script range. No duration choice silently expands or stretches the script.

Future pipeline stages should write validated `EditPlan` and `Timeline` JSON; the renderer consumes those declarative records and never executes model-generated code.

The local storage boundary is `StorageProvider`. `LocalStorageProvider` writes uploaded source files beneath `storage/projects/<project-id>/`. Database and Redis connections are configured independently through environment variables. Redis is currently health-checked and ready to back a worker queue in Part 2.

The timeline schema and `modern_creator_v1` style preset are separate packages so the API, director, and Remotion renderer can share the contract without duplicating visual values.
