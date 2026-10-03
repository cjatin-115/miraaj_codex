import math
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

WORD_RE = re.compile(r"\b[\w]+(?:['’][\w]+)?\b", re.UNICODE)
SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "because",
    "been",
    "being",
    "could",
    "does",
    "from",
    "have",
    "into",
    "just",
    "more",
    "most",
    "only",
    "other",
    "over",
    "same",
    "some",
    "such",
    "than",
    "that",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "through",
    "very",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
    "your",
    "you",
    "are",
    "and",
    "for",
    "the",
    "was",
    "will",
    "not",
    "but",
    "its",
    "our",
    "out",
    "can",
    "how",
    "why",
    "who",
    "has",
    "had",
    "all",
    "one",
    "two",
}
HOOK_MARKERS = ("imagine", "what if", "have you ever", "here's why", "here is why", "the truth")


class ScriptAnalyzer:
    def analyze(self, script: str) -> dict:
        text = script.strip()
        if not text:
            raise ValueError("Script cannot be empty.")
        words = WORD_RE.findall(text)
        sentences = [part.strip() for part in SENTENCE_RE.findall(text) if part.strip()]
        paragraphs = [part for part in re.split(r"\n\s*\n", text) if part.strip()]
        count = len(words)
        min_wpm, max_wpm, recommended_wpm = 125, 165, 145
        minimum = max(1, math.floor(count / max_wpm * 60))
        maximum = max(minimum, math.ceil(count / min_wpm * 60))
        recommended = max(minimum, min(maximum, round(count / recommended_wpm * 60)))
        # Estimates are less stable for very short copy; longer scripts provide more evidence.
        first_sentence = sentences[0] if sentences else text
        lowered = text.casefold()
        hooks = (
            [first_sentence]
            if any(marker in lowered for marker in HOOK_MARKERS) or first_sentence.endswith("?")
            else []
        )
        if not hooks:
            hooks = [first_sentence]
        important = [
            sentence
            for sentence in sentences
            if re.search(
                r"\d|\b(?:must|never|always|only|because|means|important|key)\b|!", sentence, re.I
            )
        ]
        if not important:
            important = sentences[: min(3, len(sentences))]
        frequencies = Counter(
            word.casefold()
            for word in words
            if len(word) >= 4 and word.casefold() not in STOP_WORDS
        )
        emphasis = [word for word, _ in frequencies.most_common(8)]
        candidates = []
        for index, sentence in enumerate(sentences):
            visual_cue = re.search(
                r"\b(percent|%|data|chart|graph|compare|versus|vs\.?|steps?|first|second|example|imagine|look at)\b|\d",
                sentence,
                re.I,
            )
            if visual_cue:
                candidates.append(
                    {"sentence_index": index, "text": sentence, "visual_hint": visual_cue.group(0)}
                )
        return {
            "word_count": count,
            "sentence_count": len(sentences),
            "paragraph_count": len(paragraphs),
            "estimated_speaking_duration_seconds": recommended,
            "speaking_rate_wpm": recommended_wpm,
            "likely_hooks": hooks[:3],
            "important_statements": important[:8],
            "candidate_visual_moments": candidates[:12],
            "candidate_emphasis_words": emphasis,
        }


def analyze_script_cached(script: str, cache_root: Path) -> dict:
    text = script.strip()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cache_file = cache_root / "scripts" / f"{digest}.json"
    if cache_file.is_file():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    result = ScriptAnalyzer().analyze(text)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def estimate_duration(script_analysis: dict) -> dict:
    words = int(script_analysis["word_count"])
    if words < 1:
        raise ValueError("Cannot estimate duration for an empty script.")
    minimum = max(1, math.floor(words / 165 * 60))
    maximum = max(minimum, math.ceil(words / 125 * 60))
    recommended = max(minimum, min(maximum, round(words / 145 * 60)))
    confidence = round(min(0.9, 0.48 + min(words, 500) / 1200), 2)
    return {
        "estimated_min_duration": minimum,
        "estimated_max_duration": maximum,
        "recommended_duration": recommended,
        "confidence": confidence,
    }


def assess_duration_target(estimate: dict, target: float) -> dict:
    high = float(estimate["estimated_max_duration"])
    low = float(estimate["estimated_min_duration"])
    if target > high * 1.15:
        status = "script_shorter_than_target"
        message = f"This script naturally supports about {low}–{high} seconds. Reaching {target:g} seconds would require adding content."
    elif target < low * 0.75:
        status = "target_shorter_than_script"
        message = f"This script naturally supports about {low}–{high} seconds; {target:g} seconds may require cutting content."
    else:
        status = "fits"
        message = None
    return {
        "status": status,
        "message": message,
        "target_duration": target,
        "script_expansion_available": False,
    }
