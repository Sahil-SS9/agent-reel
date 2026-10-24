"""M2 P6: exports are produced at the promised sizes and the sidecar keeps source ids."""

from __future__ import annotations

import json

from PIL import Image

from canon.export import DISCORD_MAX_BYTES, SOCIAL_SIZES, caption_draft, export_episode

IR = {
    "episode_id": "ev_1",
    "cliffhanger": True,
    "panels": [
        {"id": f"p{i}", "caption": f"Caption {i}.", "caption_source_event_ids": [f"e{i}"],
         "lines": [{"speaker": "Sahil", "text": "Hi.", "source_event_ids": [f"e{i}"]}]}
        for i in range(1, 7)
    ],
}


def test_export_set_sizes_and_sidecar(tmp_path):
    panels = [Image.new("RGB", (768, 512), (40 * i, 80, 120)) for i in range(6)]
    result = export_episode(panels, out_dir=tmp_path, title="Recon audit", ir=IR, style="anime",
                            render_report={"calls": 6}, checks=[{"panel_id": "p1", "passed": True}])
    for name, (size, _cols) in SOCIAL_SIZES.items():
        assert Image.open(result.files[name]).size == size, name
    assert result.files["discord"].stat().st_size <= DISCORD_MAX_BYTES
    side = json.loads(result.files["sidecar"].read_text())
    assert side["panels"][0]["caption_source_event_ids"] == ["e1"]
    assert side["panels"][5]["lines"][0]["source_event_ids"] == ["e6"]
    assert "To be continued" in result.caption_draft
    page = Image.open(result.files["page"])
    assert page.size[1] > page.size[0]  # 2 columns x 3 rows


def test_caption_draft_uses_only_episode_text():
    draft = caption_draft("Title", {"panels": [{"caption": "Only this."}], "cliffhanger": False})
    assert draft == "Title\n\nOnly this.\n\n#HermesAgent"
