import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp"))

from server import DesignContext, handle_get_board_spec


def test_git_only_mode(tmp_path):
    ctx = DesignContext(workspace_dir=str(tmp_path))
    ctx.config = {"design_system": {"provider": "git_only"}}

    res = handle_get_board_spec(ctx, {"file_id": "file1", "board_id": "board1"})
    assert res["supported"] is False
    assert res["provider"] == "git_only"


def test_penpot_revision_caching_and_force_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("PENPOT_ACCESS_TOKEN", "fake_token_123")
    cache_dir = tmp_path / "cache"

    ctx = DesignContext(workspace_dir=str(tmp_path))
    ctx.config = {
        "design_system": {
            "provider": "penpot",
            "penpot": {
                "base_url": "http://mock-penpot:9001",
                "cache_dir": str(cache_dir),
                "on_unavailable": "skip",
            },
        }
    }

    mock_file_response = json.dumps(
        {
            "rev": "rev_abc123",
            "id": "file1",
            "name": "DesignSystem",
            "pages": [
                {
                    "id": "board1",
                    "name": "ButtonBoard",
                    "x": 100.0,
                    "y": 200.0,
                    "width": 800.0,
                    "height": 600.0,
                    "tokens": ["color.brand.primary"],
                }
            ],
        }
    ).encode("utf-8")

    mock_png_bytes = b"\x89PNG\r\n\x1a\nfake_image_bytes"

    exporter_call_count = 0

    def mock_urlopen(req, timeout=4.0):
        nonlocal exporter_call_count
        url = req.full_url
        mock_resp = MagicMock()
        mock_enter = MagicMock()
        mock_resp.__enter__.return_value = mock_enter
        if "get-file" in url:
            mock_enter.status = 200
            mock_enter.read.return_value = mock_file_response
            return mock_resp
        elif "export-object" in url:
            exporter_call_count += 1
            mock_enter.status = 200
            mock_enter.read.return_value = mock_png_bytes
            return mock_resp
        raise ValueError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        # 1. First fetch -> cached = False, exporter called
        res1 = handle_get_board_spec(ctx, {"file_id": "file1", "board_id": "board1"})
        assert res1["supported"] is True
        assert res1["reachable"] is True
        assert res1["cached"] is False
        assert res1["rev"] == "rev_abc123"
        assert res1["geometry"] == {"x": 100.0, "y": 200.0, "width": 800.0, "height": 600.0}
        assert exporter_call_count == 1
        assert res1["reference_png_path"] is not None
        assert os.path.isfile(os.path.join(tmp_path, res1["reference_png_path"]))

        # 2. Second fetch with same rev -> cached = True, exporter NOT called again
        res2 = handle_get_board_spec(ctx, {"file_id": "file1", "board_id": "board1"})
        assert res2["cached"] is True
        assert exporter_call_count == 1

        # 3. Third fetch with force_refresh = True -> cached = False, exporter called again
        res3 = handle_get_board_spec(ctx, {"file_id": "file1", "board_id": "board1", "force_refresh": True})
        assert res3["cached"] is False
        assert exporter_call_count == 2


def test_penpot_unreachable_skip_and_block(tmp_path, monkeypatch):
    monkeypatch.setenv("PENPOT_ACCESS_TOKEN", "fake_token_123")

    ctx = DesignContext(workspace_dir=str(tmp_path))

    # on_unavailable = skip
    ctx.config = {
        "design_system": {
            "provider": "penpot",
            "penpot": {
                "base_url": "http://invalid-penpot:9001",
                "on_unavailable": "skip",
            },
        }
    }

    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        res_skip = handle_get_board_spec(ctx, {"file_id": "file1"})
        assert res_skip["reachable"] is False
        assert res_skip["on_unavailable"] == "skip"
        assert "warning" in res_skip

    # on_unavailable = block
    ctx.config["design_system"]["penpot"]["on_unavailable"] = "block"
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        res_block = handle_get_board_spec(ctx, {"file_id": "file1"})
        assert res_block["reachable"] is False
        assert res_block["on_unavailable"] == "block"
        assert "error" in res_block
