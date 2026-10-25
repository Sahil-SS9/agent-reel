"""V10 (25/10/26): image-source mapping, proven with recorded request/response shapes."""

import base64
import json
from pathlib import Path

import pytest

from canon.providers import SOURCES, check_source, fill_workflow, load_workflow, make_generator
from canon.render import RenderError

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class Fake:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        status, payload = self.replies.pop(0)
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload).encode()
        return status, payload


@pytest.fixture
def ref(tmp_path):
    path = tmp_path / "sheet.png"
    path.write_bytes(PNG)
    return path


def test_openai_edit_with_references(tmp_path, ref):
    fake = Fake([(200, {"data": [{"b64_json": base64.b64encode(PNG).decode()}]})])
    gen = make_generator("openai", out_dir=tmp_path, env={"OPENAI_API_KEY": "k"}, transport=fake)
    out = gen("a panel", [ref], "landscape")
    method, url, headers, body = fake.calls[0]
    assert url.endswith("/v1/images/edits") and headers["Authorization"] == "Bearer k"
    assert b'name="image[]"' in body and b"1536x1024" in body and b"gpt-image-1" in body
    assert out.read_bytes() == PNG


def test_openai_without_references_uses_generations(tmp_path):
    fake = Fake([(200, {"data": [{"b64_json": base64.b64encode(PNG).decode()}]})])
    make_generator("openai", out_dir=tmp_path, env={"OPENAI_API_KEY": "k"}, transport=fake)("p", [], "square")
    assert fake.calls[0][1].endswith("/v1/images/generations")
    assert json.loads(fake.calls[0][3])["size"] == "1024x1024"


def test_gemini_inline_references_and_aspect(tmp_path, ref):
    reply = {"candidates": [{"content": {"parts": [{"text": "ok"}, {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(PNG).decode()}}]}}]}
    fake = Fake([(200, reply)])
    out = make_generator("gemini", out_dir=tmp_path, env={"GEMINI_API_KEY": "g"}, transport=fake)("p", [ref, ref], "portrait")
    body = json.loads(fake.calls[0][3])
    assert "gemini-2.5-flash-image:generateContent" in fake.calls[0][1]
    assert fake.calls[0][2]["x-goog-api-key"] == "g"
    assert len(body["contents"][0]["parts"]) == 3
    assert body["generationConfig"]["imageConfig"]["aspectRatio"] == "2:3"
    assert out.read_bytes() == PNG


def test_gemini_blocked_prompt_is_a_clear_error(tmp_path):
    fake = Fake([(200, {"promptFeedback": {"blockReason": "SAFETY"}})])
    with pytest.raises(RenderError, match="SAFETY"):
        make_generator("gemini", out_dir=tmp_path, env={"GEMINI_API_KEY": "g"}, transport=fake)("p", [], "square")


def test_fal_queue_flow_uses_edit_endpoint_with_refs(tmp_path, ref):
    fake = Fake([
        (200, {"status_url": "https://q/s", "response_url": "https://q/r"}),
        (200, {"status": "IN_PROGRESS"}),
        (200, {"status": "COMPLETED"}),
        (200, {"images": [{"url": "https://cdn/img.png"}]}),
        (200, PNG),
    ])
    gen = make_generator("fal", out_dir=tmp_path, model="fal-ai/nano-banana-pro", env={"FAL_KEY": "f"}, transport=fake)
    out = gen("p", [ref], "landscape")
    assert fake.calls[0][1] == "https://queue.fal.run/fal-ai/nano-banana-pro/edit"
    body = json.loads(fake.calls[0][3])
    assert body["image_urls"][0].startswith("data:image/png;base64,") and body["aspect_ratio"] == "3:2"
    assert fake.calls[0][2]["Authorization"] == "Key f"
    assert out.read_bytes() == PNG


def test_fal_flux_uses_image_size(tmp_path):
    fake = Fake([(200, {"status_url": "s", "response_url": "r"}), (200, {"status": "COMPLETED"}),
                 (200, {"images": [{"url": "data:image/png;base64," + base64.b64encode(PNG).decode()}]})])
    make_generator("fal", out_dir=tmp_path, env={"FAL_KEY": "f"}, transport=fake)("p", [], "square")
    body = json.loads(fake.calls[0][3])
    assert fake.calls[0][1].endswith("fal-ai/flux-2-pro") and body["image_size"] == "square_hd"


def test_http_errors_and_missing_keys(tmp_path):
    with pytest.raises(RenderError, match="OPENAI_API_KEY"):
        make_generator("openai", out_dir=tmp_path, env={})("p", [], "square")
    fake = Fake([(503, b"busy")])
    with pytest.raises(RenderError) as err:
        make_generator("gemini", out_dir=tmp_path, env={"GEMINI_API_KEY": "g"}, transport=fake)("p", [], "square")
    assert err.value.transient
    with pytest.raises(RenderError, match="unknown image source"):
        make_generator("nope", out_dir=tmp_path)


def test_comfy_workflow_fill_drops_unused_reference_slots():
    graph = fill_workflow(load_workflow("qwen-image-edit-2511"), prompt="P", width=1536, height=1024, images=["a.png"], seed=7)
    assert graph["11"]["inputs"]["image"] == "a.png"
    assert "12" not in graph and "22" not in graph and "13" not in graph
    assert "image2" not in graph["6"]["inputs"] and graph["6"]["inputs"]["image1"] == ["21", 0]
    assert graph["6"]["inputs"]["prompt"] == "P" and graph["8"]["inputs"]["width"] == 1536
    assert graph["9"]["inputs"]["seed"] == 7
    assert all("_optional_inputs" not in n for n in graph.values())
    no_refs = fill_workflow(load_workflow("qwen-image-edit-2511"), prompt="P", width=1, height=1, images=[], seed=1)
    assert "6" in no_refs and "image1" not in no_refs["6"]["inputs"]


def test_comfy_flow_upload_prompt_history_view(tmp_path, ref):
    fake = Fake([
        (200, {"name": "reel-x.png"}),
        (200, {"prompt_id": "abc", "node_errors": {}}),
        (200, {}),
        (200, {"abc": {"status": {"completed": True}, "outputs": {"14": {"images": [{"filename": "o.png", "subfolder": "", "type": "output"}]}}}}),
        (200, PNG),
    ])
    import canon.providers as providers

    out = providers.comfyui_generator(out_dir=tmp_path, transport=fake, sleep=lambda s: None)("p", [ref], "landscape")
    assert fake.calls[0][1].endswith("/upload/image")
    submitted = json.loads(fake.calls[1][3])["prompt"]
    assert submitted["11"]["inputs"]["image"] == "reel-x.png"
    assert "filename=o.png" in fake.calls[4][1]
    assert out.read_bytes() == PNG


def test_comfy_node_errors_are_reported(tmp_path):
    import canon.providers as providers

    fake = Fake([(200, {"prompt_id": "x", "node_errors": {"9": "bad"}})])
    with pytest.raises(RenderError, match="rejected"):
        providers.comfyui_generator(out_dir=tmp_path, transport=fake)("p", [], "square")


def test_check_source_never_generates():
    report = check_source("fal", env={})
    assert not report["ready"] and "FAL_KEY" in report["problem"]
    nodes = {n: {} for n in ["UNETLoader", "CLIPLoader", "VAELoader", "ModelSamplingAuraFlow", "CFGNorm", "LoadImage",
                             "ImageScaleToTotalPixels", "TextEncodeQwenImageEditPlus", "EmptySD3LatentImage",
                             "KSampler", "VAEDecode", "SaveImage"]}
    fake = Fake([(200, nodes)])
    report = check_source("comfyui", transport=fake)
    assert report["ready"] and fake.calls[0][0] == "GET" and fake.calls[0][1].endswith("/object_info")
    fake = Fake([(200, {"UNETLoader": {}})])
    assert "missing nodes" in check_source("comfyui", transport=fake)["problem"]


def test_every_source_declares_status_honestly():
    assert {s.status for s in SOURCES.values()} <= {"tested", "mapped", "unsupported"}
    assert SOURCES["host"].status == "tested"


def test_out_of_credit_is_not_retried(tmp_path):
    fake = Fake([(429, b'{"error": {"message": "You have no credits remaining", "type": "insufficient_quota"}}')])
    with pytest.raises(RenderError) as err:
        make_generator("openai", out_dir=tmp_path, env={"OPENAI_API_KEY": "k"}, transport=fake)("p", [], "square")
    assert not err.value.transient and "no credit" in str(err.value)
    busy = Fake([(429, b"rate limited, slow down")])
    with pytest.raises(RenderError) as err:
        make_generator("openai", out_dir=tmp_path, env={"OPENAI_API_KEY": "k"}, transport=busy)("p", [], "square")
    assert err.value.transient
