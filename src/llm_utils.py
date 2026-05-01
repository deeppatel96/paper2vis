"""Shared LLM provider helpers used by both extractor and codegen."""

from __future__ import annotations

import base64
import os
from pathlib import Path


def call_llm(provider: str, model: str, prompt: str, max_tokens: int = 2048) -> str:
    if provider == "anthropic":
        return _call_anthropic(prompt, model, max_tokens)
    elif provider == "openai":
        return _call_openai(prompt, model, max_tokens)
    elif provider == "ollama":
        return _call_ollama(prompt, model)
    raise ValueError(f"Unknown provider: {provider!r}")


def call_llm_vision(
    provider: str,
    model: str,
    prompt: str,
    image_paths: list[str | Path],
    max_tokens: int = 2048,
) -> str:
    """Call an LLM with both text and image inputs. Only openai and anthropic support vision."""
    if provider == "openai":
        return _call_openai_vision(prompt, model, image_paths, max_tokens)
    elif provider == "anthropic":
        return _call_anthropic_vision(prompt, model, image_paths, max_tokens)
    raise ValueError(f"Vision not supported for provider: {provider!r}. Use 'openai' or 'anthropic'.")


def call_llm_vision_bytes(
    provider: str,
    model: str,
    prompt: str,
    images: list[bytes],
    max_tokens: int = 1024,
) -> str:
    """Like call_llm_vision but accepts raw image bytes instead of file paths."""
    if provider == "openai":
        return _call_openai_vision_bytes(prompt, model, images, max_tokens)
    elif provider == "anthropic":
        return _call_anthropic_vision_bytes(prompt, model, images, max_tokens)
    raise ValueError(f"Vision not supported for provider: {provider!r}. Use 'openai' or 'anthropic'.")


# ---------------------------------------------------------------------------
# Text-only implementations
# ---------------------------------------------------------------------------

def _call_anthropic(prompt: str, model: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_openai(prompt: str, model: str, max_tokens: int) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def _call_ollama(prompt: str, model: str) -> str:
    import json as _json
    import urllib.request
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://host-gateway:11434")
    payload = _json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = _json.loads(resp.read())
    return data["message"]["content"]


# ---------------------------------------------------------------------------
# Vision implementations
# ---------------------------------------------------------------------------

def _encode_image(path: str | Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")


def _call_openai_vision(
    prompt: str, model: str, image_paths: list[str | Path], max_tokens: int
) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    content: list[dict] = [{"type": "text", "text": prompt}]
    for path in image_paths:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{_encode_image(path)}",
                "detail": "high",
            },
        })

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def _call_anthropic_vision(
    prompt: str, model: str, image_paths: list[str | Path], max_tokens: int
) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    content: list[dict] = []
    for path in image_paths:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": _encode_image(path),
            },
        })
    content.append({"type": "text", "text": prompt})

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Bytes-based vision (no temp files needed)
# ---------------------------------------------------------------------------

def _bytes_to_b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def _sniff_mime(data: bytes) -> str:
    """Guess MIME type from magic bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _call_openai_vision_bytes(
    prompt: str, model: str, images: list[bytes], max_tokens: int
) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    content: list[dict] = [{"type": "text", "text": prompt}]
    for img_bytes in images:
        mime = _sniff_mime(img_bytes)
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime};base64,{_bytes_to_b64(img_bytes)}",
                "detail": "high",
            },
        })

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""


def _call_anthropic_vision_bytes(
    prompt: str, model: str, images: list[bytes], max_tokens: int
) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    content: list[dict] = []
    for img_bytes in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _sniff_mime(img_bytes),
                "data": _bytes_to_b64(img_bytes),
            },
        })
    content.append({"type": "text", "text": prompt})

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
    )
    return message.content[0].text
