"""Deterministic EditPlan validation and renderer-ready timeline conversion."""

from copy import deepcopy

from miraaj_api.director import _validation_errors

FPS = 30


class TimelineValidationError(ValueError):
    pass


class TimelineBuilder:
    def build(
        self,
        plan: dict,
        source_duration: float,
        style: dict | None = None,
        face_boxes: list | None = None,
        available_assets: set[str] | dict[str, dict] | None = None,
    ) -> dict:
        if source_duration <= 0:
            raise TimelineValidationError("Source footage is missing or has no duration.")
        errs = _validation_errors(plan)
        if errs:
            raise TimelineValidationError("Invalid EditPlan: " + "; ".join(errs))
        scenes = deepcopy(plan["scenes"])
        duration = float(plan["duration"])
        frame = 1 / FPS
        if abs(duration - round(duration * FPS) / FPS) > frame:
            raise TimelineValidationError("Plan duration is not aligned to the 30 fps timeline.")
        stylesafe = (style or {}).get("safe_area", {"top": 160, "bottom": 260, "horizontal": 72})
        caps = (style or {}).get("captions", {})
        channels = {}
        base = []
        for s in scenes:
            if s["source_end"] > source_duration + frame or s["source_start"] < 0:
                raise TimelineValidationError(f"{s['id']} exceeds source footage bounds.")
            if abs((s["source_end"] - s["source_start"]) - s["duration"]) > frame:
                raise TimelineValidationError(f"{s['id']} source range and duration disagree.")
            if s["timeline_start"] + s["duration"] > duration + frame:
                raise TimelineValidationError(f"{s['id']} extends beyond total duration.")
            start, end = (
                round(s["timeline_start"] * FPS) / FPS,
                round((s["timeline_start"] + s["duration"]) * FPS) / FPS,
            )
            s["timeline_start"], s["duration"] = start, round(end - start, 3)
            if s.get("layer", "base") == "base":
                base.append(s)
            channel = s.get("channel", "video" if s.get("layer", "base") == "base" else "overlay")
            channels.setdefault(channel, []).append(s)
            if s["type"] == "caption":
                text = s.get("text", "")
                maxchars = 28
                maxlines = 2
                lines = text.splitlines() or [text]
                if len(lines) > maxlines or any(len(line) > maxchars for line in lines):
                    raise TimelineValidationError(
                        f"{s['id']} caption overflows the style line limits."
                    )
                if s["duration"] < 0.5 or len(text) / s["duration"] > 24:
                    raise TimelineValidationError(f"{s['id']} caption is too brief to read.")
                s["layout"] = {
                    "x": stylesafe["horizontal"],
                    "y": 1920 - stylesafe["bottom"],
                    "width": 1080 - 2 * stylesafe["horizontal"],
                    "max_lines": maxlines,
                    "font_size": caps.get("font_size", 64),
                }
            if s["type"] in {"screenshot", "image_broll", "video_broll"}:
                asset = s.get("asset_request", {}).get("data", {}).get("asset_id")
                allowed_ids = (
                    set(available_assets)
                    if isinstance(available_assets, dict)
                    else (available_assets or set())
                )
                if not asset or asset not in allowed_ids:
                    raise TimelineValidationError(f"{s['id']} references an unavailable asset.")
                if isinstance(available_assets, dict):
                    asset_kind = available_assets[asset].get("kind")
                    expected_kind = "video" if s["type"] == "video_broll" else "image"
                    if asset_kind != expected_kind:
                        raise TimelineValidationError(
                            f"{s['id']} needs an uploaded {expected_kind} asset."
                        )
                if s["type"] == "video_broll" and isinstance(available_assets, dict):
                    asset_duration = float(
                        available_assets[asset].get("metadata", {}).get("duration_seconds") or 0
                    )
                    if asset_duration + frame < s["duration"]:
                        raise TimelineValidationError(
                            f"{s['id']} is longer than its uploaded b-roll asset."
                        )
            if "asset_request" in s and s["asset_request"]["type"] not in {
                "statistics",
                "comparison",
                "graph",
                "screenshot",
                "image_broll",
                "video_broll",
            }:
                raise TimelineValidationError(f"{s['id']} has an unsupported asset request.")
            if face_boxes and s.get("layer", "base") == "base":
                box = next(
                    (
                        b
                        for b in face_boxes
                        if s["source_start"] <= b.get("time", -1) <= s["source_end"]
                        and b.get("face_bbox")
                    ),
                    None,
                )
                if box:
                    b = box["face_bbox"]
                    cx = b["x"] + b["width"] / 2
                    cy = b["y"] + b["height"] / 2
                    if b["width"] * s["crop"]["scale"] > 1 or b["height"] * s["crop"]["scale"] > 1:
                        raise TimelineValidationError(f"{s['id']} crop cuts off detected face.")
                    s["crop"]["focus_x"] = round(min(1, max(0, cx)), 3)
                    s["crop"]["focus_y"] = round(min(1, max(0, cy)), 3)
        for channel, group in channels.items():
            group.sort(key=lambda x: x["timeline_start"])
            for prev, cur in zip(group, group[1:]):
                overlap = prev["timeline_start"] + prev["duration"] - cur["timeline_start"]
                if overlap > frame:
                    raise TimelineValidationError(
                        f"Illegal overlap on channel {channel}: {prev['id']} and {cur['id']}."
                    )
                if overlap > 0:
                    cur["timeline_start"] = round(cur["timeline_start"] + overlap, 3)
                    if cur.get("layer", "base") == "base":
                        cur["source_start"] = round(cur["source_start"] + overlap, 3)
                    cur["duration"] = round(cur["duration"] - overlap, 3)
        base.sort(key=lambda s: s["timeline_start"])
        cursor = 0.0
        for s in base:
            if abs(s["timeline_start"] - cursor) > frame:
                raise TimelineValidationError(
                    "Base footage has a gap or overlap; timeline must be continuous."
                )
            cursor = s["timeline_start"] + s["duration"]
        if abs(cursor - duration) > frame:
            raise TimelineValidationError(
                f"Base scene duration {cursor:.3f}s does not match plan duration {duration:.3f}s."
            )
        scenes.sort(
            key=lambda s: (
                s["timeline_start"],
                0 if s.get("layer", "base") == "base" else 1,
                s.get("channel", ""),
            )
        )
        renderer_scenes = []
        for scene in scenes:
            output = {key: value for key, value in scene.items() if key != "timeline_start"}
            output["start"] = scene["timeline_start"]
            renderer_scenes.append(output)
        return {
            "version": 1,
            "width": 1080,
            "height": 1920,
            "fps": FPS,
            "duration": round(duration, 3),
            "style_id": plan.get("style_id", "modern_creator_v1"),
            "scenes": renderer_scenes,
        }
