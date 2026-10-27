"""Run inside the typeset image:  pytest -q /app/tests"""

from __future__ import annotations

import base64
import json
import struct
import subprocess
import sys
import tempfile
import threading
import time
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


def pdftext_raw(pdf: bytes) -> str:
    """Text in content-stream order: superscripts stay next to their base."""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf)
        f.flush()
        return subprocess.run(
            ["pdftotext", "-raw", "-enc", "UTF-8", f.name, "-"], capture_output=True, text=True, check=True
        ).stdout


def pdftitle(pdf: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf)
        f.flush()
        info = subprocess.run(["pdfinfo", "-enc", "UTF-8", f.name], capture_output=True, text=True, check=True).stdout
    return next(line.split(":", 1)[1].strip() for line in info.splitlines() if line.startswith("Title:"))


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
    assert "Motion basics" not in text and pdftitle(pdf) == "Motion basics"
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
    assert pdftitle(pdf) == "Title with % & # _ {x}"


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
    monkeypatch.setattr(server, "_render", lambda *a, **k: (None, "! LaTeX Error: simulated", False))
    status, _, body = post(base_url, {"markdown": "Text $x$", "title": "", "images": {}})
    assert status == 422
    assert json.loads(body)["error"]


def test_timeout_returns_504(base_url, monkeypatch):
    monkeypatch.setattr(server, "DOC_TIMEOUT", 0.01)
    status, _, body = post(base_url, {"markdown": "Text", "title": "", "images": {}})
    assert status == 504
    assert "error" in json.loads(body)


def _tex_processes() -> list[str]:
    """TeX/Quarto processes still alive, plus any zombie (unreaped) process."""
    time.sleep(0.5)  # give init a moment to reap
    found = []
    for d in Path("/proc").glob("[0-9]*"):
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            state = (d / "stat").read_text().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError):
            continue
        if state == "Z":
            found.append(f"zombie {d.name}")
        elif "xelatex" in cmd or "deno" in cmd or "quarto" in cmd:
            found.append(cmd)
    return found


def test_timeout_kills_whole_process_tree(base_url, monkeypatch):
    monkeypatch.setattr(server, "DOC_TIMEOUT", 6)
    status, _, _ = post(base_url, {"markdown": "Loop $\\def\\x{\\x}\\x$ here.\n", "title": "", "images": {}})
    assert status in (200, 504)
    assert _tex_processes() == []


def test_looping_formula_reaches_fallback(base_url):
    headers, pdf = render(base_url, "Loop $\\def\\x{\\x}\\x$ and good $y^2$.\n")
    assert headers["X-Typeset-Fallback"] == "1"
    text = pdftext(pdf)
    assert "\\def\\x{\\x}\\x" in text and "y^2" not in text
    assert _tex_processes() == []


def test_title_is_plain_metadata_not_printed(base_url):
    _, pdf = render(base_url, "Body $x^2$.", title="Bad $\\frac{1}{$")
    assert pdftitle(pdf) == "Bad $\\frac{1}{$"
    assert "Bad" not in pdftext(pdf)
    _, pdf = render(base_url, "Body.", title="$x$ and $y$ *cost* $5")
    assert pdftitle(pdf) == "$x$ and $y$ *cost* $5"
    assert "cost" not in pdftext(pdf)


def test_no_tex_ligatures_in_text(base_url):
    # escaped as the backend's builders escape plain text
    md = 'Say \\"q\\" \\<\\< \\>\\> ,, \\`tick\\` \\-\\- and \\-\\-\\- end. `mono -- "x"`\n'
    headers, pdf = render(base_url, md)
    text = pdftext(pdf)
    assert headers["X-Typeset-Fallback"] == "0"
    for token in ['"q"', "<<", ">>", ",,", "`tick`", " -- ", "---", 'mono -- "x"']:
        assert token in text, (token, text)
    for curly in "\u201c\u201d\u2018\u2019\u201e\u00ab\u00bb\u2013\u2014":
        assert curly not in text, (curly, text)


def test_body_cap_is_100_mb():
    assert server.MAX_BODY == 100 * 1024 * 1024


def test_file_access_formulas_are_never_compiled(base_url):
    md = "Leak $\\input{/etc/passwd}$ and $\\immediate\\write18{touch /tmp/pwned}$, good $z^2$.\n"
    headers, pdf = render(base_url, md)
    text = pdftext(pdf)
    assert headers["X-Typeset-Fallback"] == "2"
    assert "\\input{/etc/passwd}" in text
    assert "root:" not in text and "z^2" not in text
    assert not Path("/tmp/pwned").exists()


def test_busy_returns_503(base_url, monkeypatch):
    slots = server.threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(server, "_slots", slots)
    monkeypatch.setattr(server, "QUEUE_WAIT", 0.1)
    status, _, body = post(base_url, {"markdown": "x", "title": "", "images": {}})
    assert status == 503 and json.loads(body) == {"error": "busy"}


def test_invalid_base64_is_400(base_url):
    status, _, body = post(base_url, {"markdown": "x", "title": "", "images": {"a.png": "not*base64!"}})
    assert status == 400 and "base64" in json.loads(body)["error"]



DANGEROUS = """input include openin openout read write immediate filedump filesize filemoddate
mdfivesum IfFileExists InputIfFileExists UseName use csname endcsname expandafter def gdef
edef let newcommand renewcommand catcode lccode uccode scantokens ExplSyntaxOn ExplSyntaxOff
begingroup endgroup string detokenize special usepackage makeatletter VerbatimInput
lstinputlisting directlua""".split()


def test_allowlist_excludes_dangerous_words():
    assert len(server.ALLOWLIST) > 1000
    assert sorted(set(DANGEROUS) & server.ALLOWLIST) == []


BYPASSES = {
    "usename": r"\UseName{input}{/etc/hostname}",
    "begin-input": r"\begin{input}{/etc/hostname}",
    "expl3": r"\ExplSyntaxOn \use:c {input} {/etc/hostname} \ExplSyntaxOff",
    "filedump": r"\mathrm{\filedump length 60 {/proc/self/environ}}",
    "filesize": r"\filesize{/etc/passwd}",
    "iffileexists": r"\IfFileExists{/etc/passwd}{YES}{NO}",
    "verbatim": r"\VerbatimInput{/etc/hostname}",
    "hat-hat": r"^^5cinput{/etc/hostname}",
    "at": r"\@@input /etc/hostname",
}


@pytest.mark.parametrize("name", sorted(BYPASSES))
def test_file_access_bypasses_show_source(base_url, name):
    src = BYPASSES[name]
    headers, pdf = render(base_url, f"Probe ${src}$ end. Good $z^2$.\n")
    text = pdftext(pdf)
    assert headers["X-Typeset-Fallback"] == "1"
    assert src.split("{")[0].strip() in text, text
    hostname = Path("/etc/hostname").read_text().strip()
    assert hostname not in text and "root:" not in text and "PATH=" not in text


def test_spike_sheet_formulas_all_compile(base_url):
    md = (Path(__file__).parent / "data" / "spike_items.md").read_text()
    refused = [m for m in server.collect_math(json.loads(subprocess.run(
        ["quarto", "pandoc", "-f", server.MD_FORMAT, "-t", "json"], input=md, capture_output=True, text=True, check=True
    ).stdout)) if not server.formula_allowed(m[1])]
    assert refused == []
    headers, pdf = render(base_url, md)
    assert headers["X-Typeset-Fallback"] == "0"
    assert "\\frac" not in pdftext(pdf)


def test_chemistry_module_samples_compile(base_url):
    headers, pdf = render(base_url, "An $S_N2$ step, $\\beta$ decay and a nitro group $-\\text{NO}_2$.\n")
    assert headers["X-Typeset-Fallback"] == "0"
    assert "\\text" not in pdftext(pdf)


def test_slow_first_render_is_retried_not_degraded(base_url, monkeypatch):
    monkeypatch.setattr(server, "FIRST_RENDER_SHARE", 0.002)  # cap ~0.24 s: always hit
    md = "Formula $x^2 + \\frac{a}{b}$.\n\n![A red box](box.png)\n"
    headers, pdf = render(base_url, md, images={"box.png": base64.b64encode(png()).decode()})
    assert headers["X-Typeset-Fallback"] == "0"
    text = pdftext(pdf)
    assert "x^2" not in text and "\\frac" not in text
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf)
        f.flush()
        listing = subprocess.run(["pdfimages", "-list", f.name], capture_output=True, text=True, check=True).stdout
    assert len(listing.strip().splitlines()) - 2 == 1, listing


# -- final review fixes -----------------------------------------------------------------


def test_quarto_shortcodes_are_literal_in_math_code_and_text(base_url):
    """Nothing in the document is a Quarto shortcode: `{{<` in a formula, a code
    span or text prints as written and never truncates the document."""
    md = (
        "Code `{{< env HOSTNAME >}}` and `{{< include /etc/passwd >}}` stay.\n\n"
        "Math $x_{{< env HOSTNAME >}}$ end.\n\n"
        "Truncate $a_{{<5}} + b$ here.\n\n"
        "Text \\{\\{\\< include /etc/passwd \\>\\}\\} too.\n\n"
        "Last paragraph present.\n"
    )
    headers, pdf = render(base_url, md)
    text = pdftext(pdf)
    assert headers["X-Typeset-Fallback"] == "0", text
    assert "{{< env HOSTNAME >}}" in text and "{{< include /etc/passwd >}}" in text
    assert "{{< include /etc/passwd >}} too" in text
    assert "here." in text and "Last paragraph present" in text
    hostname = Path("/etc/hostname").read_text().strip()
    assert hostname not in text and "root:" not in text


INDIC = {
    "hindi": "बल",
    "hindi-2": "होता",
    "marathi": "मराठी",
    "telugu": "తెలుగు",
    "tamil": "தமிழ்",
    "kannada": "ಕನ್ನಡ",
}


def test_indic_scripts_render(base_url):
    md = "बल $F = ma$ होता है। मराठी తెలుగు தமிழ் ಕನ್ನಡ\n\n**बल** and *తెలుగు*.\n"
    headers, pdf = render(base_url, md)
    text = pdftext(pdf)
    assert headers["X-Typeset-Fallback"] == "0", text
    for name, word in INDIC.items():
        assert word in text, (name, word, text)
    assert "F = ma" not in text  # the formula is typeset (math spacing)


def test_missing_glyphs_are_reported_not_silent(base_url):
    # Linear B: no font in the image has it
    headers, pdf = render(base_url, "A rare sign \U00010000 here, $x^2$.\n")
    assert headers["X-Typeset-Fallback"] == "0+glyphs"
    assert "here" in pdftext(pdf)


BOLD = {
    "\\boldsymbol{\\omega}": "\U0001d74e",  # bold italic omega
    "\\boldsymbol{F}": "\U0001d46d",  # bold italic F
    "\\boldsymbol{\\nabla}": "\U0001d735",  # bold italic nabla
    "\\vb*{a}": "\U0001d482",  # bold italic a
    "\\bm{x}": "\U0001d499",  # bold italic x
    "\\mathbf{\\alpha}": "\U0001d6c2",  # bold alpha
    "\\vb{\\omega}": "\U0001d6da",  # bold omega
    "\\vb{\\alpha}": "\U0001d6c2",
    "\\mathbf{F}": "\U0001d405",  # bold F
    "\\boldsymbol{2}": "\U0001d7d0",  # bold digit two
}


@pytest.mark.parametrize("src", sorted(BOLD))
def test_bold_math_is_bold(base_url, src):
    headers, pdf = render(base_url, f"Bold ${src}$ here.\n")
    text = pdftext(pdf)
    assert headers["X-Typeset-Fallback"] == "0", text
    assert BOLD[src] in text, (src, text)


# Compared with all white space removed (pdftotext puts a raised exponent on
# its own line): the characters, in order, exactly as written.
SIUNITX = {
    "\\si{\\joule\\per\\kilogram\\kelvin}": ("ValueJkg−1Kend.", ["K−1"]),
    "\\num{1,500}": ("Value1,500end.", []),
    "\\num{12345}": ("Value12345end.", []),
    "\\num{.5}": ("Value.5end.", ["0.5"]),
    "\\num{1.5e3}": ("Value1.5e3end.", ["×", "\U0001d452"]),  # no italic e
    "\\SI{1,500}{\\metre}": ("Value1,500mend.", []),
    "\\si{\\square\\metre}": ("Valuem2end.", ["□"]),
    "\\SI{1.5e3}{\\metre}": ("Value1.5e3mend.", ["×", "\U0001d452"]),
    "\\si{\\micro\\metre}": ("Valueµmend.", []),
    "\\SI{3 \\times 10^{8}}{\\metre\\per\\second}": ("Value3×108ms−1end.", []),
}


@pytest.mark.parametrize("src", sorted(SIUNITX))
def test_siunitx_prints_numbers_as_written(base_url, src):
    want, never = SIUNITX[src]
    headers, pdf = render(base_url, f"Value ${src}$ end.\n")
    raw = pdftext_raw(pdf)
    text = "".join(raw.split())
    assert headers["X-Typeset-Fallback"] == "0", raw
    assert want in text, (src, raw)
    for bad in never:
        assert bad not in text, (src, bad, raw)
    # a comma in a number is not followed by math punctuation space
    if "," in src:
        assert "1,500" in raw, raw
