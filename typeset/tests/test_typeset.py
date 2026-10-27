"""Run inside the typeset image:  pytest -q /app/tests"""

from __future__ import annotations

import base64
import json
import struct
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: E402


@pytest.fixture(scope="session")
def base_url():
    srv = server.make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def post(base_url: str, payload: object, raw: bytes | None = None):
    data = raw if raw is not None else json.dumps(payload).encode()
    req = urllib.request.Request(f"{base_url}/pdf", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def render(base_url: str, markdown: str, title: str = "Test", images: dict | None = None):
    status, headers, body = post(base_url, {"markdown": markdown, "title": title, "images": images or {}})
    assert status == 200, body[:2000]
    assert headers["Content-Type"] == "application/pdf"
    assert body.startswith(b"%PDF-")
    return headers, body


def pdftext(pdf: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf)
        f.flush()
        return subprocess.run(["pdftotext", "-enc", "UTF-8", f.name, "-"], capture_output=True, text=True, check=True).stdout


def png(width: int = 40, height: int = 20) -> bytes:
    row = b"\x00" + b"\xff\x00\x00" * width
    raw = row * height

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_health(base_url):
    with urllib.request.urlopen(f"{base_url}/health", timeout=10) as resp:
        assert resp.status == 200
        assert json.loads(resp.read()) == {"status": "ok"}


def test_good_doc_renders_pdf(base_url):
    md = (
        "# Kinematics\n\nVelocity is the rate of change of displacement: $v = \\frac{dx}{dt}$.\n\n"
        "$$E = mc^2$$\n\nNewton wrote $\\mathbf{F} = m\\mathbf{a}$ and $\\dv{x}{t}$, $\\qty{9.8}{\\metre\\per\\second\\squared}$.\n"
    )
    headers, pdf = render(base_url, md, title="Motion basics")
    text = pdftext(pdf)
    assert "Motion basics" in text
    assert "Kinematics" in text
    assert "Velocity is the rate of change" in text
    assert headers["X-Typeset-Fallback"] == "0"
    assert "\\frac" not in text and "\\dv" not in text


def test_bad_formula_falls_back_document_builds(base_url):
    md = (
        "Good one: $a^2 + b^2 = c^2$.\n\n"
        "Broken one: $\\frac{1}{$ and more prose after it.\n\n"
        "$$\\int_0^1 x\\,dx = \\frac{1}{2}$$\n\n"
        "Also good: $\\ce{H2O}$ and $\\sqrt{2}$.\n"
    )
    headers, pdf = render(base_url, md)
    text = pdftext(pdf)
    assert headers["X-Typeset-Fallback"] == "1"
    assert "\\frac{1}{" in text  # the bad formula as its source
    assert "more prose after it" in text
    # The good formulas were typeset, not printed as source.
    assert "a^2" not in text and "\\int" not in text and "\\sqrt" not in text and "\\ce" not in text


def test_plain_text_specials_are_escaped(base_url):
    specials = "Profit 50% on item #3 at R&D, snake_case {braces} ~tilde ^caret path C:\\temp\\new"
    md = (
        f"{specials}\n\n"
        f"- list: {specials}\n\n"
        "| column | value |\n|---|---|\n"
        f"| cell | {specials} |\n\n"
        "Tags <b>stay</b> literal and so does @someone.\n"
    )
    headers, pdf = render(base_url, md, title="Title with % & # _ {x}")
    text = pdftext(pdf)
    assert headers["X-Typeset-Fallback"] == "0"
    # paragraph, list item and table cell each carry the full string
    for token in ["50%", "#3", "R&D", "snake_case", "{braces}", "~tilde", "^caret", "C:\\temp\\new"]:
        assert text.count(token) == 3, (token, text)
    assert "<b>stay</b>" in text and "@someone" in text
    assert "Title with % & # _ {x}" in text


def test_unicode_text_is_present(base_url):
    md = "Capacitance 4.7 µF; A → B; x ≤ 3 ≥ y; 2 × 3; 25 °C; α β γ Δ Ω π.\n\n| µ | → |\n|---|---|\n| ≤ | ° |\n"
    _, pdf = render(base_url, md)
    text = pdftext(pdf)
    for ch in ["µ", "→", "≤", "≥", "×", "°", "α", "β", "γ", "Δ", "Ω", "π"]:
        assert ch in text, (ch, text)


def test_micro_sign_inside_formula_is_not_dropped(base_url):
    headers, pdf = render(base_url, "Capacitor $C = 4.7\\,µ\\text{F}$ here.\n")
    text = pdftext(pdf)
    assert headers["X-Typeset-Fallback"] == "0"
    assert "μF" in text or "µF" in text, text


def test_chemistry_compiles(base_url):
    md = "Sulfuric acid: $\\ce{H2SO4 -> 2H+ + SO4^2-}$\n\nBenzene:\n\n$$\\chemfig{*6(=-=-=-)}$$\n\nEthanol $\\chemfig{H-C(-[2]H)(-[6]H)-O-H}$.\n"
    headers, pdf = render(base_url, md)
    text = pdftext(pdf)
    assert headers["X-Typeset-Fallback"] == "0"
    assert "\\ce" not in text and "\\chemfig" not in text
    assert "Sulfuric acid" in text and "SO" in text


def test_image_reference_renders(base_url):
    md = "Before the figure.\n\n![A red box](box.png)\n\nAfter. Missing: ![gone](nothere.png) and unsafe ![up](../etc/passwd)\n"
    images = {"box.png": base64.b64encode(png()).decode(), "../etc/passwd": base64.b64encode(png()).decode()}
    _, pdf = render(base_url, md, images=images)
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf)
        f.flush()
        listing = subprocess.run(["pdfimages", "-list", f.name], capture_output=True, text=True, check=True).stdout
    assert len(listing.strip().splitlines()) - 2 == 1, listing  # header lines + one image
    text = pdftext(pdf)
    assert "A red box" in text and "gone" in text and "up" in text


def test_bad_request(base_url):
    status, _, body = post(base_url, None, raw=b"not json")
    assert status == 400 and "error" in json.loads(body)
    status, _, body = post(base_url, {"title": "x"})
    assert status == 400 and "error" in json.loads(body)


def test_unreadable_image_keeps_formulas(base_url):
    broken = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"garbage" * 10).decode()
    md = "Formula $x^2$ stays typeset.\n\n![Broken picture](bad.png)\n"
    headers, pdf = render(base_url, md, images={"bad.png": broken})
    text = pdftext(pdf)
    assert headers["X-Typeset-Fallback"] == "0+images"
    assert "Broken picture" in text and "x^2" not in text


def test_unbuildable_document_returns_422(base_url, monkeypatch):
    monkeypatch.setattr(server, "_render", lambda *a, **k: (None, "! LaTeX Error: simulated"))
    status, _, body = post(base_url, {"markdown": "Text $x$", "title": "", "images": {}})
    assert status == 422
    assert json.loads(body)["error"]


def test_timeout_returns_504(base_url, monkeypatch):
    monkeypatch.setattr(server, "DOC_TIMEOUT", 0.01)
    status, _, body = post(base_url, {"markdown": "Text", "title": "", "images": {}})
    assert status == 504
    assert "error" in json.loads(body)
