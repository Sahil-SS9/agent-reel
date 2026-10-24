"""M2 P3: renderer retry, cache, budget; host adapter parsing."""

from __future__ import annotations

import json
from pathlib import Path

from adapters.hermes.images import host_generator
from canon.panel_prompt import PanelRequest
from canon.render import PanelRenderer, RenderError, write_render_manifest


def _req(tmp_path, panel_id="p1", prompt="a panel"):
    ref = tmp_path / "ref.jpg"
    if not ref.exists():
        ref.write_bytes(b"sheet")
    return PanelRequest(panel_id=panel_id, prompt=prompt, references=(ref,), cast=("Sahil",),
                        positions={"Sahil": "LEFT"}, aspect="landscape")


class FakeGen:
    def __init__(self, tmp_path, fail=()):
        self.tmp_path = tmp_path
        self.fail = list(fail)
        self.calls = 0

    def __call__(self, prompt, refs, aspect):
        self.calls += 1
        if self.fail:
            kind = self.fail.pop(0)
            raise RenderError(kind, transient=kind.startswith("503"))
        out = self.tmp_path / f"gen-{self.calls}.png"
        out.write_bytes(f"img {prompt}".encode())
        return out


def test_renders_and_caches(tmp_path):
    gen = FakeGen(tmp_path)
    r = PanelRenderer(gen, cache_dir=tmp_path / "cache", sleep=lambda s: None)
    report = r.render([_req(tmp_path)], tmp_path / "out")
    assert report.calls == 1 and (tmp_path / "out" / "p1.png").is_file()
    again = PanelRenderer(gen, cache_dir=tmp_path / "cache", sleep=lambda s: None).render([_req(tmp_path)], tmp_path / "out2")
    assert again.calls == 0 and again.cache_hits == 1 and gen.calls == 1


def test_changed_reference_sheet_misses_the_cache(tmp_path):
    gen = FakeGen(tmp_path)
    PanelRenderer(gen, cache_dir=tmp_path / "cache", sleep=lambda s: None).render([_req(tmp_path)], tmp_path / "o")
    (tmp_path / "ref.jpg").write_bytes(b"new sheet")
    report = PanelRenderer(gen, cache_dir=tmp_path / "cache", sleep=lambda s: None).render([_req(tmp_path)], tmp_path / "o")
    assert report.calls == 1


def test_transient_failure_is_retried_with_backoff(tmp_path):
    slept = []
    gen = FakeGen(tmp_path, fail=["503 Service Unavailable"])
    report = PanelRenderer(gen, cache_dir=tmp_path / "c", sleep=slept.append, backoff_s=2).render([_req(tmp_path)], tmp_path / "o")
    assert report.retries == 1 and slept == [2] and "p1" in report.rendered


def test_permanent_failure_is_not_retried(tmp_path):
    gen = FakeGen(tmp_path, fail=["content policy"])
    report = PanelRenderer(gen, cache_dir=tmp_path / "c", sleep=lambda s: None).render([_req(tmp_path)], tmp_path / "o")
    assert report.calls == 1 and report.failures and not report.rendered


def test_budget_stops_new_calls(tmp_path):
    gen = FakeGen(tmp_path)
    reqs = [_req(tmp_path, f"p{i}", f"prompt {i}") for i in range(3)]
    report = PanelRenderer(gen, cache_dir=tmp_path / "c", budget=2, sleep=lambda s: None).render(reqs, tmp_path / "o")
    assert report.calls == 2 and len(report.rendered) == 2
    assert any("budget" in f for f in report.failures)


def test_manifest_records_requests(tmp_path):
    gen = FakeGen(tmp_path)
    reqs = [_req(tmp_path)]
    report = PanelRenderer(gen, cache_dir=tmp_path / "c", sleep=lambda s: None).render(reqs, tmp_path / "o")
    write_render_manifest(tmp_path / "m.json", reqs, report)
    data = json.loads((tmp_path / "m.json").read_text())
    assert data["requests"][0]["positions"] == {"Sahil": "LEFT"}


def test_host_generator_parses_success_and_errors(tmp_path):
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    seen = {}

    def ok(name, args):
        seen.update(args)
        return json.dumps({"success": True, "image": str(img)})

    assert host_generator(ok)("p", [tmp_path / "r.jpg"], "landscape") == img
    assert seen["reference_image_urls"] == [str(tmp_path / "r.jpg")]

    def busy(name, args):
        return json.dumps({"success": False, "error": "503 upstream overloaded"})

    try:
        host_generator(busy)("p", [], "landscape")
    except RenderError as exc:
        assert exc.transient
    else:
        raise AssertionError("expected RenderError")
