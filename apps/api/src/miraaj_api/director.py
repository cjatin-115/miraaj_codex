"""Structured AI Director providers and deterministic default director."""

import json
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[4]
EDIT_PLAN_SCHEMA = json.loads(
    (ROOT / "packages/timeline/edit-plan.schema.json").read_text(encoding="utf-8")
)
SCENE_TYPES = {
    "talking_head",
    "talking_head_zoom",
    "talking_head_overlay",
    "talking_head_split",
    "fullscreen_text",
    "keyword_text",
    "editorial_text",
    "caption",
    "screenshot",
    "browser",
    "code",
    "comparison",
    "statistics",
    "graph",
    "product_card",
    "image_broll",
    "video_broll",
    "diagram",
    "quote",
    "cta",
}


class DirectorError(ValueError):
    pass


class LLMProvider(Protocol):
    def generate(self, context: dict[str, Any], schema: dict, repair: str | None = None) -> str: ...


class LocalLLMProvider:
    def __init__(
        self, url: str = "http://localhost:11434", model: str = "llama3.2", timeout: int = 90
    ):
        self.url, self.model, self.timeout = url.rstrip("/"), model, timeout

    def generate(self, context: dict, schema: dict, repair: str | None = None) -> str:
        prompt = (
            "Create a valid Miraaj EditPlan using only source ranges in the supplied media. Return JSON only.\n"
            + json.dumps(context, ensure_ascii=False)
        )
        if repair:
            prompt += "\nRepair this output to satisfy schema: " + repair
        body = json.dumps(
            {"model": self.model, "prompt": prompt, "format": schema, "stream": False}
        ).encode()
        return _post_json(self.url + "/api/generate", body, self.timeout).get("response", "")


class GeminiProvider:
    def __init__(self, api_key: str, model: str = "gemini-3.8-flash", timeout: int = 90):
        if not api_key:
            raise DirectorError("GEMINI_API_KEY is required for the Gemini provider.")
        self.api_key, self.model, self.timeout = api_key, model, timeout

    def generate(self, context: dict, schema: dict, repair: str | None = None) -> str:
        prompt = (
            "Create a valid Miraaj EditPlan. Use only supplied source time ranges; do not invent footage. Context: "
            + json.dumps(context, ensure_ascii=False)
        )
        if repair:
            prompt += " Repair the previous output using these validation errors: " + repair
        body = json.dumps(
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseJsonSchema": schema,
                },
            }
        ).encode()
        return (
            _post_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                body,
                self.timeout,
                headers={"x-goog-api-key": self.api_key},
            )
            .get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )


def _post_json(url: str, body: bytes, timeout: int, headers: dict[str, str] | None = None) -> dict:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(url, data=body, headers=request_headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as error:
        detail = error.read(2048).decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise DirectorError(
            f"LLM provider request failed: HTTP {error.code} {error.reason}{suffix}"
        ) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise DirectorError(f"LLM provider request failed: {error}") from error


class MockDirector:
    """Deterministic director: uses actual speech/footage ranges, never generates assets."""

    def generate(self, context: dict[str, Any]) -> dict:
        video = context.get("video_metadata") or {}
        source_duration = float(video.get("duration_seconds") or 0)
        if source_duration <= 0:
            raise DirectorError("Source footage duration is missing or invalid.")
        requested = float(context.get("target_duration") or source_duration)
        words = (context.get("transcript") or {}).get("words") or []
        valid_words = [
            w
            for w in words
            if isinstance(w.get("start"), (int, float))
            and isinstance(w.get("end"), (int, float))
            and w["end"] > w["start"]
            and w["start"] < source_duration
        ]
        # Prefer contiguous speech chunks; absent transcription, retain the full actual recording.
        intervals: list[tuple[float, float, str]] = []
        if valid_words:
            budget = min(source_duration, requested)
            kept = [w for w in valid_words if w["start"] < budget]
            for i in range(0, len(kept), 7):
                chunk = kept[i : i + 7]
                if not chunk:
                    continue
                start, end = (
                    max(0, float(chunk[0]["start"])),
                    min(source_duration, float(chunk[-1]["end"])),
                )
                if end - start >= 0.2:
                    intervals.append(
                        (start, end, " ".join(w.get("word", "").strip() for w in chunk).strip())
                    )
        else:
            end = min(source_duration, requested)
            if end > 0:
                intervals = [(0, end, "")]
        if not intervals:
            raise DirectorError("No usable source speech or footage fits the selected duration.")
        scenes, cursor = [], 0.0
        for idx, (start, end, text) in enumerate(intervals):
            duration = end - start
            kind = "talking_head_zoom" if idx and idx % 4 == 3 else "talking_head"
            scene = {
                "id": f"scene_{idx + 1:03d}",
                "type": kind,
                "source_start": round(start, 3),
                "source_end": round(end, 3),
                "timeline_start": round(cursor, 3),
                "duration": round(duration, 3),
                "layer": "base",
                "channel": "video",
                "crop": {
                    "mode": "close" if kind.endswith("zoom") else "fit",
                    "scale": 1.08 if kind.endswith("zoom") else 1.0,
                    "focus_x": 0.5,
                    "focus_y": 0.5,
                },
                "rationale": "Natural source speech segment",
            }
            scenes.append(scene)
            cursor += duration
            if text:
                caption_words = []
                current = ""
                for word in text.split():
                    candidate = (current + " " + word).strip()
                    if len(candidate) > 26 and current:
                        caption_words.append(current)
                        current = word
                    else:
                        current = candidate
                if current:
                    caption_words.append(current)
                chunk_words = [
                    w
                    for w in valid_words
                    if start <= float(w["start"])
                    and float(w["end"]) <= end
                    and w.get("word", "").strip()
                ]
                word_cursor = 0
                for cap_idx, caption in enumerate(caption_words):
                    words_in_caption = caption.split()
                    cap_start = (
                        float(chunk_words[word_cursor]["start"])
                        if word_cursor < len(chunk_words)
                        else start
                    )
                    word_cursor += len(words_in_caption)
                    cap_end = (
                        float(chunk_words[min(word_cursor - 1, len(chunk_words) - 1)]["end"])
                        if chunk_words
                        else end
                    )
                    cap_duration = max(0.5, min(duration, cap_end - cap_start))
                    scenes.append(
                        {
                            "id": f"caption_{idx + 1:03d}_{cap_idx + 1:02d}",
                            "type": "caption",
                            "source_start": round(cap_start, 3),
                            "source_end": round(cap_end, 3),
                            "timeline_start": round(cursor - duration + (cap_start - start), 3),
                            "duration": round(cap_duration, 3),
                            "layer": "overlay",
                            "channel": "captions",
                            "crop": {"mode": "fit", "scale": 1.0},
                            "text": caption,
                            "rationale": "Synchronized transcript caption",
                        }
                    )
        return {
            "version": 1,
            "duration": round(cursor, 3),
            "style_id": "modern_creator_v1",
            "scenes": scenes,
        }


class AIDirector:
    def __init__(self, provider: LLMProvider | None = None, fallback: MockDirector | None = None):
        self.provider, self.fallback = provider, fallback or MockDirector()

    def create_plan(self, context: dict[str, Any]) -> dict:
        if self.provider is None:
            plan = self.fallback.generate(context)
        else:
            raw = self.provider.generate(context, EDIT_PLAN_SCHEMA)
            try:
                plan = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                plan = None
            errors = _validation_errors(plan)
            if errors:
                raw = self.provider.generate(
                    context, EDIT_PLAN_SCHEMA, repair=f"{errors}\nPrevious output: {raw}"
                )
                try:
                    plan = json.loads(raw)
                except (json.JSONDecodeError, TypeError) as error:
                    raise DirectorError(
                        "Director returned malformed JSON after structured repair."
                    ) from error
        errors = _validation_errors(plan)
        if errors:
            raise DirectorError("Invalid EditPlan after repair: " + "; ".join(errors))
        return plan


def _validation_errors(plan: Any) -> list[str]:
    return [
        f"{'.'.join(map(str, e.absolute_path)) or 'root'}: {e.message}"
        for e in Draft202012Validator(EDIT_PLAN_SCHEMA).iter_errors(plan)
    ]


def configured_director() -> AIDirector:
    from miraaj_api.config import get_settings

    settings = get_settings()
    provider = settings.director_provider.lower()
    if provider == "gemini":
        return AIDirector(GeminiProvider(settings.gemini_api_key, settings.gemini_model))
    if provider == "local":
        return AIDirector(LocalLLMProvider(settings.local_llm_url, settings.local_llm_model))
    if provider == "mock":
        return AIDirector()
    raise DirectorError(f"Unknown DIRECTOR_PROVIDER: {provider}")
