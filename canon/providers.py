"""Image sources (owner decisions V9/V10, 25/10/26).

The renderer needs one thing from an image source: ``generate(prompt, references, aspect) -> Path``.
This module maps that call onto each supported source:

- **host** - the harness's own image tool (Hermes ``image_generate``); supplied by the adapter.
- **openai** - GPT Image through the OpenAI Images API (``OPENAI_API_KEY``).
- **gemini** - Nano Banana through the Gemini API (``GEMINI_API_KEY``).
- **fal** - FLUX or Nano Banana through fal.ai (``FAL_KEY``).
- **comfyui** - a local ComfyUI server running an API-format workflow template (free, local).

Each source declares what it can do, so the renderer and the docs can say so plainly: how many
reference sheets it accepts, which aspect ratios it supports, a rough cost, and its test status.

The status is honest. ``tested`` means a real image was made through this mapping on the
owner's rig. ``mapped`` means the request and response shapes are implemented and
unit-tested against recorded shapes, but no real image was made. Anything else is
``unsupported``.

Harness-free: stdlib HTTP through an injectable ``transport``, so tests never touch the
network.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from canon.render import RenderError, is_transient

Generator = Callable[[str, Sequence[Path], str], Path]
#: transport(method, url, headers, body) -> (status, body_bytes)
Transport = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, bytes]]

ASPECT_SIZES = {"landscape": (1536, 1024), "portrait": (1024, 1536), "square": (1024, 1024)}
ASPECT_RATIOS = {"landscape": "3:2", "portrait": "2:3", "square": "1:1"}
WORKFLOWS = Path(__file__).resolve().parents[1] / "assets" / "workflows"


@dataclass(frozen=True)
class SourceSpec:
    key: str
    label: str
    kind: str  # host | api | local
    env: tuple[str, ...] = ()
    default_model: str = ""
    models: tuple[str, ...] = ()
    max_references: int = 0
    approx_cost: str = ""
    status: str = "mapped"  # tested | mapped | unsupported
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "kind": self.kind, "env": list(self.env),
            "default_model": self.default_model, "models": list(self.models),
            "max_references": self.max_references, "approx_cost": self.approx_cost,
            "status": self.status, "notes": self.notes,
        }


SOURCES: dict[str, SourceSpec] = {
    "host": SourceSpec(
        "host", "Your harness's own image tool", "host", max_references=4,
        approx_cost="whatever your harness provider charges", status="tested",
        notes="Hermes: image_generate with your configured image_gen provider. Tested with GPT Image (openai-codex).",
    ),
    "openai": SourceSpec(
        "openai", "GPT Image (OpenAI API)", "api", env=("OPENAI_API_KEY",),
        default_model="gpt-image-1", models=("gpt-image-1", "gpt-image-1-mini"),
        max_references=4, approx_cost="about 4-20p per image",
    ),
    "gemini": SourceSpec(
        "gemini", "Nano Banana (Gemini API)", "api", env=("GEMINI_API_KEY",),
        default_model="gemini-2.5-flash-image", models=("gemini-2.5-flash-image", "gemini-3-pro-image-preview"),
        max_references=3, approx_cost="about 3p per image",
    ),
    "fal": SourceSpec(
        "fal", "FLUX or Nano Banana (fal.ai)", "api", env=("FAL_KEY",),
        default_model="fal-ai/flux-2-pro",
        models=("fal-ai/flux-2-pro", "fal-ai/nano-banana-pro", "fal-ai/flux-2/klein/9b"),
        max_references=4, approx_cost="about 1-12p per image",
        notes="With reference sheets the model's /edit endpoint is used.",
    ),
    "comfyui": SourceSpec(
        "comfyui", "Local ComfyUI (free)", "local", env=(),
        default_model="qwen-image-edit-2511", models=("qwen-image-edit-2511",),
        max_references=3, approx_cost="free (your GPU)",
        notes="Runs an API-format workflow template from assets/workflows/ or your own file.",
    ),
}


# ---------------------------------------------------------------- transport
def urllib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None,
                     *, timeout: float = 180.0) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed endpoints
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() or b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RenderError(f"network error: {exc}", transient=True) from exc


def _json(status: int, body: bytes, what: str) -> dict[str, Any]:
    text = body.decode("utf-8", "replace")
    if status >= 400:
        raise RenderError(f"{what} HTTP {status}: {text[:300]}", transient=status in {429, 500, 502, 503, 504} or is_transient(text))
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RenderError(f"{what} returned non-JSON: {text[:200]}") from exc
    if not isinstance(data, dict):
        raise RenderError(f"{what} returned {type(data).__name__}, expected an object")
    return data


def _save(out_dir: Path, data: bytes, suffix: str = ".png") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"img-{uuid.uuid4().hex[:12]}{suffix}"
    path.write_bytes(data)
    return path


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode()}"


def _key(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not value:
        raise RenderError(f"{name} is not set; add it to your environment to use this image source")
    return value


# ---------------------------------------------------------------- sources
def openai_generator(*, out_dir: Path, model: str = "", env: Mapping[str, str] | None = None,
                     transport: Transport = urllib_transport) -> Generator:
    environ = os.environ if env is None else env
    model = model or SOURCES["openai"].default_model

    def generate(prompt: str, references: Sequence[Path], aspect: str) -> Path:
        key = _key(environ, "OPENAI_API_KEY")
        w, h = ASPECT_SIZES.get(aspect, ASPECT_SIZES["landscape"])
        size = f"{w}x{h}"
        if references:
            boundary = uuid.uuid4().hex
            parts: list[bytes] = []
            for name, value in (("model", model), ("prompt", prompt), ("size", size), ("n", "1")):
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
            for ref in list(references)[: SOURCES["openai"].max_references]:
                mime = mimetypes.guess_type(str(ref))[0] or "image/png"
                parts.append(
                    f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; filename="{Path(ref).name}"\r\n'
                    f"Content-Type: {mime}\r\n\r\n".encode() + Path(ref).read_bytes() + b"\r\n"
                )
            parts.append(f"--{boundary}--\r\n".encode())
            status, body = transport("POST", "https://api.openai.com/v1/images/edits",
                                     {"Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
                                     b"".join(parts))
        else:
            status, body = transport("POST", "https://api.openai.com/v1/images/generations",
                                     {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                     json.dumps({"model": model, "prompt": prompt, "size": size, "n": 1}).encode())
        data = _json(status, body, "OpenAI images")
        item = (data.get("data") or [{}])[0]
        if item.get("b64_json"):
            return _save(out_dir, base64.b64decode(item["b64_json"]))
        if item.get("url"):
            st, img = transport("GET", item["url"], {}, None)
            if st >= 400:
                raise RenderError(f"OpenAI image download HTTP {st}", transient=True)
            return _save(out_dir, img)
        raise RenderError("OpenAI images returned no image")

    return generate


def gemini_generator(*, out_dir: Path, model: str = "", env: Mapping[str, str] | None = None,
                     transport: Transport = urllib_transport) -> Generator:
    environ = os.environ if env is None else env
    model = model or SOURCES["gemini"].default_model

    def generate(prompt: str, references: Sequence[Path], aspect: str) -> Path:
        key = _key(environ, "GEMINI_API_KEY")
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for ref in list(references)[: SOURCES["gemini"].max_references]:
            mime = mimetypes.guess_type(str(ref))[0] or "image/png"
            parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(Path(ref).read_bytes()).decode()}})
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"],
                                 "imageConfig": {"aspectRatio": ASPECT_RATIOS.get(aspect, "3:2")}},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        status, raw = transport("POST", url, {"x-goog-api-key": key, "Content-Type": "application/json"},
                                json.dumps(body).encode())
        data = _json(status, raw, "Gemini")
        for candidate in data.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inline_data") or part.get("inlineData")
                if inline and inline.get("data"):
                    return _save(out_dir, base64.b64decode(inline["data"]))
        reason = (data.get("promptFeedback") or {}).get("blockReason") or "no image in the reply"
        raise RenderError(f"Gemini returned no image: {reason}")

    return generate


def fal_generator(*, out_dir: Path, model: str = "", env: Mapping[str, str] | None = None,
                  transport: Transport = urllib_transport, poll_seconds: float = 2.0,
                  max_wait: float = 300.0, sleep: Callable[[float], None] = time.sleep) -> Generator:
    environ = os.environ if env is None else env
    model = model or SOURCES["fal"].default_model

    def generate(prompt: str, references: Sequence[Path], aspect: str) -> Path:
        key = _key(environ, "FAL_KEY")
        headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
        endpoint = model
        body: dict[str, Any] = {"prompt": prompt, "num_images": 1, "output_format": "png"}
        if references:
            endpoint = f"{model}/edit"
            body["image_urls"] = [_data_uri(Path(r)) for r in list(references)[: SOURCES["fal"].max_references]]
        if "nano-banana" in model:
            body["aspect_ratio"] = ASPECT_RATIOS.get(aspect, "3:2")
        else:
            body["image_size"] = {"landscape": "landscape_4_3", "portrait": "portrait_4_3", "square": "square_hd"}.get(aspect, "landscape_4_3")
        status, raw = transport("POST", f"https://queue.fal.run/{endpoint}", headers, json.dumps(body).encode())
        queued = _json(status, raw, "fal submit")
        status_url, result_url = queued.get("status_url"), queued.get("response_url")
        if not status_url or not result_url:
            raise RenderError(f"fal submit gave no queue urls: {str(queued)[:200]}")
        waited = 0.0
        while True:
            st, raw = transport("GET", status_url, headers, None)
            state = str(_json(st, raw, "fal status").get("status", ""))
            if state == "COMPLETED":
                break
            if state in {"FAILED", "ERROR", "CANCELLED"}:
                raise RenderError(f"fal job {state.lower()}")
            if waited >= max_wait:
                raise RenderError("fal job timed out", transient=True)
            sleep(poll_seconds)
            waited += poll_seconds
        st, raw = transport("GET", result_url, headers, None)
        result = _json(st, raw, "fal result")
        images = result.get("images") or ([result["image"]] if result.get("image") else [])
        url = (images[0] or {}).get("url") if images else None
        if not url:
            raise RenderError("fal returned no image")
        if url.startswith("data:"):
            return _save(out_dir, base64.b64decode(url.split(",", 1)[1]))
        st, img = transport("GET", url, {}, None)
        if st >= 400:
            raise RenderError(f"fal image download HTTP {st}", transient=True)
        return _save(out_dir, img)

    return generate


def load_workflow(name_or_path: str) -> dict[str, Any]:
    path = Path(name_or_path).expanduser()
    if not path.is_file():
        path = WORKFLOWS / f"{name_or_path}.json"
    if not path.is_file():
        raise RenderError(f"ComfyUI workflow not found: {name_or_path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data


def fill_workflow(template: Mapping[str, Any], *, prompt: str, width: int, height: int,
                  images: Sequence[str], seed: int) -> dict[str, Any]:
    """Replace ``{{PROMPT}}``, ``{{WIDTH}}``, ``{{HEIGHT}}``, ``{{SEED}}`` and ``{{IMAGE_N}}``.

    Nodes that consume an image slot nobody filled are removed, together with every input
    that pointed at them, so a two-reference panel runs on a three-slot workflow.
    """
    graph = json.loads(json.dumps(template.get("prompt", template)))
    graph.pop("_meta", None)
    values: dict[str, Any] = {"{{PROMPT}}": prompt, "{{WIDTH}}": width, "{{HEIGHT}}": height, "{{SEED}}": seed}
    for index in range(1, 10):
        values[f"{{{{IMAGE_{index}}}}}"] = images[index - 1] if index <= len(images) else None
    dropped: set[str] = set()
    for node_id, node in graph.items():
        for name, value in list((node.get("inputs") or {}).items()):
            if isinstance(value, str) and value in values:
                if values[value] is None:
                    dropped.add(node_id)
                else:
                    node["inputs"][name] = values[value]
    changed = True
    while changed:  # drop nodes that depend on dropped nodes
        changed = False
        for node_id, node in graph.items():
            if node_id in dropped:
                continue
            for name, value in list((node.get("inputs") or {}).items()):
                if isinstance(value, list) and value and str(value[0]) in dropped:
                    if node.get("_optional_inputs") and name in node["_optional_inputs"]:
                        del node["inputs"][name]
                    else:
                        dropped.add(node_id)
                        changed = True
                        break
    for node_id in dropped:
        graph.pop(node_id, None)
    for node in graph.values():
        node.pop("_optional_inputs", None)
    return graph


def comfyui_generator(*, out_dir: Path, workflow: str = "qwen-image-edit-2511",
                      base_url: str = "http://127.0.0.1:8188", transport: Transport = urllib_transport,
                      poll_seconds: float = 2.0, max_wait: float = 600.0,
                      sleep: Callable[[float], None] = time.sleep) -> Generator:
    template = load_workflow(workflow)
    base = base_url.rstrip("/")

    def generate(prompt: str, references: Sequence[Path], aspect: str) -> Path:
        uploaded: list[str] = []
        for ref in list(references)[: SOURCES["comfyui"].max_references]:
            boundary = uuid.uuid4().hex
            name = f"reel-{uuid.uuid4().hex[:8]}{Path(ref).suffix or '.png'}"
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
                f"Content-Type: {mimetypes.guess_type(str(ref))[0] or 'image/png'}\r\n\r\n".encode()
                + Path(ref).read_bytes()
                + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n--{boundary}--\r\n'.encode()
            )
            st, raw = transport("POST", f"{base}/upload/image", {"Content-Type": f"multipart/form-data; boundary={boundary}"}, body)
            uploaded.append(str(_json(st, raw, "ComfyUI upload").get("name") or name))
        w, h = ASPECT_SIZES.get(aspect, ASPECT_SIZES["landscape"])
        graph = fill_workflow(template, prompt=prompt, width=w, height=h, images=uploaded,
                              seed=int.from_bytes(os.urandom(4), "big"))
        st, raw = transport("POST", f"{base}/prompt", {"Content-Type": "application/json"},
                            json.dumps({"prompt": graph, "client_id": "scrollback-reel"}).encode())
        submitted = _json(st, raw, "ComfyUI prompt")
        if submitted.get("node_errors"):
            raise RenderError(f"ComfyUI rejected the workflow: {str(submitted['node_errors'])[:300]}")
        prompt_id = submitted.get("prompt_id")
        if not prompt_id:
            raise RenderError(f"ComfyUI gave no prompt id: {str(submitted)[:200]}")
        waited = 0.0
        while True:
            st, raw = transport("GET", f"{base}/history/{prompt_id}", {}, None)
            history = _json(st, raw, "ComfyUI history").get(prompt_id)
            if history:
                status = history.get("status") or {}
                if status.get("status_str") == "error":
                    raise RenderError("ComfyUI job failed")
                for node_out in (history.get("outputs") or {}).values():
                    for image in node_out.get("images") or []:
                        query = urllib.parse.urlencode({"filename": image.get("filename", ""),
                                                        "subfolder": image.get("subfolder", ""),
                                                        "type": image.get("type", "output")})
                        st, img = transport("GET", f"{base}/view?{query}", {}, None)
                        if st >= 400:
                            raise RenderError(f"ComfyUI image download HTTP {st}", transient=True)
                        return _save(out_dir, img)
                if status.get("completed"):
                    raise RenderError("ComfyUI finished without an image")
            if waited >= max_wait:
                raise RenderError("ComfyUI job timed out", transient=True)
            sleep(poll_seconds)
            waited += poll_seconds

    return generate



def make_generator(source: str, *, out_dir: Path, model: str = "", host: Generator | None = None,
                   options: Mapping[str, Any] | None = None, env: Mapping[str, str] | None = None,
                   transport: Transport = urllib_transport) -> Generator:
    """The generator for a source key; ``host`` is the harness's own image tool."""
    opts = dict(options or {})
    if source == "host":
        if host is None:
            raise RenderError("this harness has no built-in image tool; choose another --source")
        return host
    if source == "openai":
        return openai_generator(out_dir=out_dir, model=model, env=env, transport=transport)
    if source == "gemini":
        return gemini_generator(out_dir=out_dir, model=model, env=env, transport=transport)
    if source == "fal":
        return fal_generator(out_dir=out_dir, model=model, env=env, transport=transport)
    if source == "comfyui":
        return comfyui_generator(out_dir=out_dir, workflow=str(opts.get("workflow") or model or "qwen-image-edit-2511"),
                                 base_url=str(opts.get("base_url") or "http://127.0.0.1:8188"), transport=transport)
    raise RenderError(f"unknown image source {source!r}; choose one of {', '.join(SOURCES)}")


def check_source(source: str, *, env: Mapping[str, str] | None = None, transport: Transport = urllib_transport,
                 options: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A no-cost readiness check: keys present, local server reachable. Never generates."""
    spec = SOURCES.get(source)
    if spec is None:
        return {"source": source, "ready": False, "problem": "unknown source"}
    environ = os.environ if env is None else env
    missing = [name for name in spec.env if not environ.get(name)]
    report: dict[str, Any] = {"source": source, "label": spec.label, "status": spec.status,
                              "ready": not missing, "problem": f"missing {', '.join(missing)}" if missing else ""}
    if source == "comfyui":
        base = str((options or {}).get("base_url") or "http://127.0.0.1:8188").rstrip("/")
        try:
            st, raw = transport("GET", f"{base}/object_info", {}, None)
            nodes = json.loads(raw.decode("utf-8", "replace")) if st < 400 else {}
        except (RenderError, json.JSONDecodeError):
            nodes = {}
        if not nodes:
            report.update(ready=False, problem=f"ComfyUI not reachable at {base}")
        else:
            graph = load_workflow(str((options or {}).get("workflow") or "qwen-image-edit-2511"))
            needed = {str(n["class_type"]) for n in graph.get("prompt", graph).values()
                      if isinstance(n, dict) and n.get("class_type")}
            absent = sorted(c for c in needed if c not in nodes)
            # Model files: a string input whose node lists allowed values must be one of them.
            missing_files: list[str] = []
            for node in graph.get("prompt", graph).values():
                if not isinstance(node, dict) or node.get("class_type") not in nodes:
                    continue
                spec_inputs = (nodes[node["class_type"]].get("input") or {})
                allowed = {**(spec_inputs.get("required") or {}), **(spec_inputs.get("optional") or {})}
                for name, value in (node.get("inputs") or {}).items():
                    choices = (allowed.get(name) or [None])[0]
                    if isinstance(value, str) and isinstance(choices, list) and choices and "{{" not in value and value not in choices:
                        missing_files.append(value)
            problems = ([f"missing nodes: {', '.join(absent)}"] if absent else []) + (
                [f"missing model files: {', '.join(sorted(set(missing_files)))}"] if missing_files else [])
            report.update(ready=not problems, problem="; ".join(problems))
            report["nodes_checked"] = len(needed)
    return report


__all__ = ("SOURCES", "SourceSpec", "check_source", "fill_workflow", "load_workflow", "make_generator")
