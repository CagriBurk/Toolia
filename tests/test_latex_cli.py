"""`toolia latex` komutu (cli.py). Girdi denetimi ve çıktı klasörü sahte derleyiciyle her yerde
sınanır; gerçek derleme testleri yalnız pdflatex kuruluysa çalışır (CI'da `latex` işi kurar)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pymupdf
import pytest
from typer.testing import CliRunner

from toolia import engines
from toolia.cli import app
from toolia.convert import latex

runner = CliRunner()

DOC = r"""\documentclass{article}
\begin{document}
Merhaba LaTeX.
\end{document}
"""


@pytest.fixture
def config(tmp_path: Path) -> Path:
    """Kullanıcının kendi config.toml'u testlere karışmasın."""
    p = tmp_path / "config.toml"
    p.write_text("", encoding="utf-8")
    return p


def _invoke(*args: str | Path):
    return runner.invoke(app, ["latex", *map(str, args)])


@pytest.fixture
def fake_tex(monkeypatch: pytest.MonkeyPatch):
    """LaTeX kurulu sayılır; derleme yerine çağrılar kaydedilir ve küçük bir PDF yazılır."""
    calls: list[dict] = []
    monkeypatch.setattr(engines, "detect_latex", lambda s: engines.EngineStatus(
        key="latex", name="LaTeX", available=True, needed_for="", path="pdflatex",
        optional=True))

    def compile_project(root, main, out, **kw):
        calls.append({"root": root, "main": main, "out": out, **kw})
        if not Path(out).parent.is_dir():
            raise FileNotFoundError(out)
        with pymupdf.open() as doc:
            doc.new_page()
            doc.save(out)
        return latex.TexResult(output=Path(out), main=main.name, engine="pdflatex")

    monkeypatch.setattr(latex, "compile_project", compile_project)
    return calls


def test_rejects_file_that_is_not_tex_or_zip(tmp_path: Path, config: Path, fake_tex):
    png = tmp_path / "resim.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    r = _invoke(png, "--config", config)
    assert r.exit_code == 2
    assert "resim.png" in r.output and "LaTeX dosyası değil" in r.output
    assert not fake_tex


def test_uppercase_extension_is_accepted(tmp_path: Path, config: Path, fake_tex):
    src = tmp_path / "Tez.TEX"
    src.write_text(DOC, encoding="utf-8")
    r = _invoke(src, "--config", config)
    assert r.exit_code == 0, r.output
    assert fake_tex[0]["main"] == src


def test_relative_source_is_resolved_and_output_folder_created(
    tmp_path: Path, config: Path, fake_tex, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "belge.tex").write_text(DOC, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    r = _invoke("belge.tex", "-o", "yeni/klasor/cikti.pdf", "--config", config)
    assert r.exit_code == 0, r.output
    call = fake_tex[0]
    assert call["main"].is_absolute() and call["root"].is_absolute()
    assert call["main"] == (tmp_path / "belge.tex").resolve()
    assert Path(call["out"]).is_absolute()
    assert (tmp_path / "yeni" / "klasor" / "cikti.pdf").is_file()


def test_relative_folder_is_resolved(tmp_path: Path, config: Path, fake_tex,
                                     monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "main.tex").write_text(DOC, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    r = _invoke(".", "--config", config)
    assert r.exit_code == 0, r.output
    assert fake_tex[0]["root"] == tmp_path.resolve()
    assert (tmp_path / "main.pdf").is_file()


def test_missing_latex_is_a_clear_error_and_creates_nothing(
    tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(engines, "detect_latex", lambda s: engines.EngineStatus(
        key="latex", name="LaTeX", available=False, needed_for="", optional=True,
        install_hint="winget install MiKTeX.MiKTeX"))
    src = tmp_path / "a.tex"
    src.write_text(DOC, encoding="utf-8")
    r = _invoke(src, "-o", tmp_path / "yok" / "a.pdf", "--config", config)
    assert r.exit_code == 2
    assert "LaTeX bulunamadı" in r.output
    assert not (tmp_path / "yok").exists()


def test_unknown_engine_is_rejected(tmp_path: Path, config: Path, fake_tex):
    src = tmp_path / "a.tex"
    src.write_text(DOC, encoding="utf-8")
    r = _invoke(src, "--motor", "context", "--config", config)
    assert r.exit_code == 2 and "Bilinmeyen motor" in r.output
    assert not fake_tex


# --- gerçek derleme (TeX kuruluysa) ------------------------------------------------------------

TEX = engines.find_tex()
needs_tex = pytest.mark.skipif(TEX is None, reason="pdflatex yok")


def _text(pdf: Path) -> str:
    with pymupdf.open(pdf) as doc:
        return doc[0].get_text()


@needs_tex
def test_compile_relative_tex_into_new_folder(tmp_path: Path, config: Path,
                                              monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "belge.tex").write_text(DOC, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    r = _invoke("belge.tex", "-o", "yeni/klasor/cikti.pdf", "--config", config)
    assert r.exit_code == 0, r.output
    out = tmp_path / "yeni" / "klasor" / "cikti.pdf"
    assert "Merhaba LaTeX" in _text(out)


@needs_tex
def test_compile_zip_beside_archive(tmp_path: Path, config: Path):
    z = tmp_path / "Rapor.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("main.tex", DOC)
    r = _invoke(z, "--config", config)
    assert r.exit_code == 0, r.output
    assert "Merhaba LaTeX" in _text(tmp_path / "Rapor.pdf")


@needs_tex
def test_compile_current_folder(tmp_path: Path, config: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "main.tex").write_text(DOC, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    r = _invoke(".", "--config", config)
    assert r.exit_code == 0, r.output
    assert "Merhaba LaTeX" in _text(tmp_path / "main.pdf")
