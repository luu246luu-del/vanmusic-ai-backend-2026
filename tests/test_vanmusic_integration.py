"""Kiểm thử bộ tích hợp VanMusic: hợp đồng API, không lộ khóa trong frontend, các file bắt buộc."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VM = ROOT / "integrations" / "vanmusic"
REQUIRED = ["README_VANMUSIC_INTEGRATION.md", "VANMUSIC_PATCH_GUIDE.md", "vanmusic-predictor.css", "vanmusic-predictor.js",
            "vanmusic-api-client.js", "vanmusic-api-client.ts", "vanmusic-section.html", "vanmusic-menu-items.html",
            "vanmusic-mobile-menu-item.html", "vanmusic-config.example.js", "example.html", "api-contract.json",
            "firebase-function-example.js", ".env.example"]


def test_all_integration_files_exist():
    assert [f for f in REQUIRED if not (VM / f).exists()] == []


def test_frontend_contains_no_youtube_api_key():
    pattern = re.compile(r"AIza[0-9A-Za-z_\-]{30,}")
    for f in VM.rglob("*"):
        if f.is_file() and f.suffix in {".js", ".ts", ".html", ".json", ".css", ".md"}:
            text = f.read_text(encoding="utf-8")
            assert not pattern.search(text), f"Có vẻ là YouTube API Key trong {f.name}"
    for f in ["vanmusic-config.example.js", "vanmusic-api-client.js", "vanmusic-predictor.js", "example.html"]:
        assert "YOUTUBE_API_KEY" not in (VM / f).read_text(encoding="utf-8")


def test_config_example_is_exactly_three_keys():
    text = (VM / "vanmusic-config.example.js").read_text(encoding="utf-8")
    for key in ("apiBaseUrl", "integrationKey", "timeoutMs"):
        assert key in text
    assert re.search(r'integrationKey:\s*""', text)


def test_section_and_menu_contract():
    sec = (VM / "vanmusic-section.html").read_text(encoding="utf-8")
    assert "<!-- VANMUSIC AI PREDICTOR START -->" in sec and "<!-- VANMUSIC AI PREDICTOR END -->" in sec
    assert 'id="tab-predictor"' in sec and 'class="page-section"' in sec
    assert "switchTab('predictor', event)" in (VM / "vanmusic-menu-items.html").read_text(encoding="utf-8")
    assert "openMobileSection('predictor')" in (VM / "vanmusic-mobile-menu-item.html").read_text(encoding="utf-8")


def test_all_new_css_classes_are_prefixed():
    css = (VM / "vanmusic-predictor.css").read_text(encoding="utf-8")
    classes = set(re.findall(r"\.([A-Za-z_][\w-]*)", re.sub(r"/\*.*?\*/", "", css, flags=re.S)))
    classes = {c for c in classes if not re.fullmatch(r"\d+", c)}
    assert all(c.startswith("vm-predict-") for c in classes), [c for c in classes if not c.startswith("vm-predict-")]


def test_api_contract_matches_backend_fields():
    
    from src.api.schemas import VanMusicPredictRequest
    contract = json.loads((VM / "api-contract.json").read_text(encoding="utf-8"))
    assert set(contract["request"]["example"]) == set(VanMusicPredictRequest.model_fields)
    assert set(contract["response_success"]["example"]) == {"success", "data", "error", "request_id"}
    assert set(contract["response_error"]["example"]) == {"success", "data", "error", "request_id"}


def test_js_has_required_functions():
    js = (VM / "vanmusic-predictor.js").read_text(encoding="utf-8")
    for fn in ["initializeVanMusicPredictor", "validateVanMusicPredictionForm", "submitVanMusicPrediction",
               "renderVanMusicPrediction", "renderVanMusicPredictionError", "resetVanMusicPrediction",
               "formatViewCountVI", "parseChannelInput", "convertDurationToSeconds", "window.VanMusicPredictor"]:
        assert fn in js, fn
    client = (VM / "vanmusic-api-client.js").read_text(encoding="utf-8")
    assert "predictYouTubeViews" in client and "AbortController" in client and "VanMusicPredictionClient" in client
