import io
import json
from urllib.error import HTTPError

import pytest

from miraaj_api import director
from miraaj_api.director import DirectorError, GeminiProvider, LocalLLMProvider


class JsonResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(
            {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}
        ).encode()


def test_gemini_key_uses_auth_header_not_query_string(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return JsonResponse()

    monkeypatch.setattr(director, "urlopen", fake_urlopen)
    result = GeminiProvider("test-key").generate({"script": "test"}, {"type": "object"})

    request = captured["request"]
    assert request.full_url.endswith("/gemini-3.8-flash:generateContent")
    assert "key=" not in request.full_url
    assert {key.lower(): value for key, value in request.header_items()}[
        "x-goog-api-key"
    ] == "test-key"
    assert result == '{"ok": true}'


def test_http_error_includes_provider_diagnostic_body(monkeypatch):
    error = HTTPError(
        "http://localhost:11434/api/generate",
        500,
        "Internal Server Error",
        {},
        io.BytesIO(b'{"error":"model requires more memory"}'),
    )
    monkeypatch.setattr(director, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))

    with pytest.raises(DirectorError, match="model requires more memory"):
        LocalLLMProvider().generate({}, {"type": "object"})
