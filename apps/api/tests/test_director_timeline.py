import json

import pytest
from jsonschema import Draft202012Validator

from miraaj_api.director import AIDirector, DirectorError
from miraaj_api.timeline_builder import TimelineBuilder, TimelineValidationError

STYLE = {"safe_area": {"top": 160, "bottom": 260, "horizontal": 72}, "captions": {"font_size": 64}}


def context(duration=8, words=None):
    return {
        "script": "A clear, useful story.",
        "target_duration": duration,
        "video_metadata": {"duration_seconds": 8, "width": 1080, "height": 1920},
        "transcript": {"words": words or []},
    }


def test_mock_director_builds_serializable_renderer_timeline():
    director = AIDirector()
    plan = director.create_plan(context())
    assert plan["scenes"][0]["type"] == "talking_head"
    assert plan["duration"] == 8
    timeline = TimelineBuilder().build(plan, 8, STYLE)
    schema = json.loads(
        (
            __import__("pathlib").Path(__file__).resolve().parents[3]
            / "packages/timeline/timeline.schema.json"
        ).read_text()
    )
    Draft202012Validator(schema).validate(timeline)
    assert json.loads(json.dumps(timeline))["fps"] == 30


def test_target_duration_changes_cut_length():
    director = AIDirector()
    short = director.create_plan(context(3))
    long = director.create_plan(context(7))
    assert short["duration"] == 3
    assert long["duration"] == 7


class RepairProvider:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.repairs = 0

    def generate(self, context, schema, repair=None):
        if repair:
            self.repairs += 1
        return next(self.outputs)


def test_invalid_provider_json_gets_one_structured_repair():
    plan = AIDirector().create_plan(context())
    provider = RepairProvider(["{bad json", json.dumps(plan)])
    assert AIDirector(provider).create_plan(context()) == plan
    assert provider.repairs == 1


def test_invalid_scene_type_fails_after_repair():
    plan = AIDirector().create_plan(context())
    plan["scenes"][0]["type"] = "run_code"
    provider = RepairProvider([json.dumps(plan), json.dumps(plan)])
    with pytest.raises(DirectorError, match="Invalid EditPlan"):
        AIDirector(provider).create_plan(context())


def test_missing_source_and_duration_mismatch_fail_safely():
    with pytest.raises(DirectorError, match="duration"):
        AIDirector().create_plan({"video_metadata": {}, "target_duration": 5})
    plan = AIDirector().create_plan(context())
    plan["duration"] = 7
    with pytest.raises(TimelineValidationError, match="extends beyond|does not match"):
        TimelineBuilder().build(plan, 8, STYLE)


def test_illegal_overlap_caption_overflow_and_missing_asset_rejected():
    plan = AIDirector().create_plan(context())
    plan["scenes"].append(
        {
            "id": "overlap",
            "type": "talking_head",
            "source_start": 1,
            "source_end": 2,
            "timeline_start": 1,
            "duration": 1,
            "layer": "base",
            "channel": "video",
            "crop": {"mode": "fit", "scale": 1},
        }
    )
    with pytest.raises(TimelineValidationError, match="overlap"):
        TimelineBuilder().build(plan, 8, STYLE)
    plan = AIDirector().create_plan(context())
    plan["scenes"].append(
        {
            "id": "caption",
            "type": "caption",
            "source_start": 0,
            "source_end": 1,
            "timeline_start": 0,
            "duration": 1,
            "layer": "overlay",
            "channel": "captions",
            "crop": {"mode": "fit", "scale": 1},
            "text": "This caption is far too long to fit on a single caption line and should fail validation.",
        }
    )
    with pytest.raises(TimelineValidationError, match="overflows"):
        TimelineBuilder().build(plan, 8, STYLE)
    plan = AIDirector().create_plan(context())
    plan["scenes"][0]["type"] = "screenshot"
    plan["scenes"][0]["asset_request"] = {"type": "screenshot", "data": {"asset_id": "missing"}}
    with pytest.raises(TimelineValidationError, match="unavailable"):
        TimelineBuilder().build(plan, 8, STYLE)


def test_transcript_caption_plan_uses_overlay_channel():
    words = [
        {"word": word, "start": i * 0.45, "end": i * 0.45 + 0.35}
        for i, word in enumerate(
            [
                "Build",
                "a",
                "real",
                "timeline",
                "from",
                "the",
                "actual",
                "source",
                "without",
                "stretching",
                "the",
                "video",
            ]
        )
    ]
    plan = AIDirector().create_plan(context(8, words))
    timeline = TimelineBuilder().build(plan, 8, STYLE)
    assert any(
        scene["type"] == "caption" and scene["layer"] == "overlay" for scene in timeline["scenes"]
    )
