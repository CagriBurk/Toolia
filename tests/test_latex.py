"""LaTeX → PDF (convert/latex.py, iş türü tex_to_pdf). Derleme testleri yalnızca bu bilgisayarda
pdflatex varsa çalışır; ana dosya seçimi, motor seçimi, günlük okuma ve zip güvenliği
TeX olmadan da denenir."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from toolia import engines
from toolia.api import app as app_module
from toolia.convert import latex
from toolia.errors import TooliaError
from toolia.settings import EnginePaths, Settings

DOC = r"""\documentclass{article}
\begin{document}
Merhaba dünya.
\end{document}
"""


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def _zip(path: Path, files: dict[str, str | bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


# --- ana dosya ---------------------------------------------------------------------------------

def test_main_tex_is_preferred_over_other_documents(tmp_path: Path):
    _write(tmp_path, {"main.tex": DOC, "ek.tex": DOC, "bolum/giris.tex": "\\section{Giriş}"})
    main, notes = latex.find_main(tmp_path)
    assert main.name == "main.tex"
    assert notes and "ek.tex" in notes[0]


def test_subfiles_and_commented_documentclass_are_not_main(tmp_path: Path):
    _write(tmp_path, {
        "rapor.tex": DOC,
        "a_bolum.tex": "\\documentclass[rapor.tex]{subfiles}\n\\begin{document}x\\end{document}",
        "b_eski.tex": "% \\documentclass{article}\nnot",
    })
    main, notes = latex.find_main(tmp_path)
    assert main.name == "rapor.tex"
    assert notes == []


def test_shallowest_document_wins_in_wrapped_zip(tmp_path: Path):
    _write(tmp_path, {"Proje/tez.tex": DOC, "Proje/ornekler/deneme.tex": DOC})
    main, _ = latex.find_main(tmp_path)
    assert main.relative_to(tmp_path).as_posix() == "Proje/tez.tex"


def test_requested_main_file(tmp_path: Path):
    _write(tmp_path, {"main.tex": DOC, "poster/poster.tex": DOC})
    assert latex.find_main(tmp_path, "poster/poster.tex")[0].name == "poster.tex"
    assert latex.find_main(tmp_path, "poster.tex")[0].name == "poster.tex"
    with pytest.raises(TooliaError, match="Ana dosya bulunamadı"):
        latex.find_main(tmp_path, "yok.tex")


def test_project_without_tex(tmp_path: Path):
    _write(tmp_path, {"notlar.txt": "x"})
    with pytest.raises(TooliaError, match=".tex dosyası yok"):
        latex.find_main(tmp_path)


# --- motor seçimi ------------------------------------------------------------------------------

@pytest.mark.parametrize(("source", "engine"), [
    (DOC, "pdflatex"),
    ("% !TEX program = lualatex\n" + DOC, "lualatex"),
    ("% !TeX TS-program = XeLaTeX\n" + DOC, "xelatex"),
    ("\\documentclass{article}\\usepackage{fontspec}", "xelatex"),
    ("\\documentclass{article}\\usepackage[math]{amsmath,unicode-math}", "xelatex"),
    ("\\documentclass{article}\\usepackage{luacode}", "lualatex"),
    ("\\documentclass{article}\n% \\usepackage{fontspec}\n", "pdflatex"),
    ("% !TEX program = word\n" + DOC, "pdflatex"),
])
def test_pick_engine(source: str, engine: str):
    assert latex.pick_engine(source) == engine


# --- günlük ------------------------------------------------------------------------------------

LOG = r"""This is pdfTeX
C:/tmp/proje/main.tex:12: Undefined control sequence.
l.12 Burada \foo
               bar
./bolum.tex:3: LaTeX Error: File `tikzcd.sty' not found.
! Emergency stop.
! ==> Fatal error occurred, no output PDF file produced!
LaTeX Warning: Citation `knuth' on page 1 undefined on input line 5.
LaTeX Warning: Citation `knuth' on page 2 undefined on input line 9.
LaTeX Warning: Reference `sek:giris' on page 1 undefined on input line 7.
"""


def test_parse_errors_gives_file_line_and_friendly_text():
    errors = latex.parse_errors(LOG, Path("C:/tmp/proje"))
    assert [str(e) for e in errors] == [
        "main.tex, satır 12: Tanımsız komut (yazım hatası ya da eksik \\usepackage) "
        "(Burada \\foo)",
        "bolum.tex, satır 3: Eksik paket: tikzcd.sty",
    ]


def test_log_warnings_count_unique_citations_and_refs():
    warnings = latex.log_warnings(LOG)
    assert any("atıf) 1 tane: knuth" in w for w in warnings)
    assert any("sek:giris" in w for w in warnings)


# --- zip güvenliği -----------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["../disari.tex", "/mutlak.tex", "C:/Windows/x.tex",
                                 "a/../../b.tex"])
def test_zip_with_unsafe_paths_is_rejected(tmp_path: Path, bad: str):
    z = _zip(tmp_path / "p.zip", {"main.tex": DOC, bad: "x"})
    dest = tmp_path / "proje"
    dest.mkdir()
    with pytest.raises(TooliaError, match="güvensiz"):
        latex.extract_project(z, dest)
    assert not (tmp_path / "disari.tex").exists()


def test_zip_skips_macos_metadata_and_extracts_tree(tmp_path: Path):
    z = _zip(tmp_path / "p.zip", {"main.tex": DOC, "sekiller/a.txt": "x",
                                  "__MACOSX/._main.tex": "çöp"})
    dest = tmp_path / "proje"
    dest.mkdir()
    latex.extract_project(z, dest)
    assert (dest / "main.tex").is_file() and (dest / "sekiller/a.txt").is_file()
    assert not (dest / "__MACOSX").exists()


def test_not_a_zip_and_too_many_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bad = tmp_path / "bozuk.zip"
    bad.write_bytes(b"PK degil")
    with pytest.raises(TooliaError, match="Proje.zip"):
        latex.extract_project(bad, tmp_path, display_name="Proje.zip")
    monkeypatch.setattr(latex, "MAX_ZIP_FILES", 2)
    z = _zip(tmp_path / "cok.zip", {f"{i}.tex": "x" for i in range(3)})
    with pytest.raises(TooliaError, match="çok fazla"):
        latex.extract_project(z, tmp_path)


# --- motor algılama ----------------------------------------------------------------------------

def test_missing_tex_override_means_unavailable(tmp_path: Path):
    s = Settings(engines=EnginePaths(latex=str(tmp_path / "pdflatex.exe")))
    st = engines.detect_latex(s)
    assert not st.available and not st.ok and st.optional
    assert st.install_hint


# --- gerçek derleme (TeX kuruluysa) ------------------------------------------------------------

TEX = engines.find_tex()
needs_tex = pytest.mark.skipif(TEX is None, reason="pdflatex yok")


@pytest.fixture(scope="module")
def tex() -> Path:
    assert TEX is not None
    return TEX


@needs_tex
def test_compile_zip_project_with_bibliography(tmp_path: Path, tex: Path):
    z = _zip(tmp_path / "Rapor.zip", {
        "main.tex": "\\documentclass{article}\\usepackage[T1]{fontenc}\\usepackage{lmodern}"
                    "\\usepackage[utf8]{inputenc}\n\\begin{document}\n"
                    "\\input{bolum/giris}\nAtıf \\cite{knuth}.\n\\bibliographystyle{plain}"
                    "\\bibliography{kaynak}\n\\end{document}\n",
        "bolum/giris.tex": "\\section{Giriş}Çğüşöı.",
        "kaynak.bib": "@book{knuth, author={Donald Knuth}, title={The TeXbook}, year={1984},"
                      " publisher={AW}}",
        # Projedeki latexmkrc Perl kodudur; okunmamalı.
        "latexmkrc": "system('echo calisti > rc-calisti.txt');",
    })
    root = tmp_path / "proje"
    root.mkdir()
    latex.extract_project(z, root)
    main, _ = latex.find_main(root)
    r = latex.compile_project(root, main, tmp_path / "out.pdf", tex=tex)
    assert r.engine == "pdflatex" and r.main == "main.tex"
    with pymupdf.open(r.output) as doc:
        text = doc[0].get_text()
    assert "Giriş" in text and "TeXbook" in text
    assert not list(root.rglob("rc-calisti.txt"))
    assert any("latexmkrc" in w for w in r.warnings)


@needs_tex
def test_errors_still_give_pdf_and_shell_escape_is_off(tmp_path: Path, tex: Path):
    _write(tmp_path, {"a.tex": "\\documentclass{article}\\begin{document}\nX\n\\foo\n"
                               "\\immediate\\write18{echo x > kabuk.txt}\n\\end{document}\n"})
    r = latex.compile_project(tmp_path, tmp_path / "a.tex", tmp_path / "out.pdf",
                              tex=tex)
    assert r.output.is_file()
    assert any("a.tex, satır 3" in w for w in r.warnings)
    assert not (tmp_path / "kabuk.txt").exists()


@needs_tex
def test_fatal_error_reports_missing_package(tmp_path: Path, tex: Path):
    _write(tmp_path, {"a.tex": "\\documentclass{article}\\usepackage{boyle-bir-paket-yok}"
                               "\\begin{document}X\\end{document}\n"})
    with pytest.raises(TooliaError, match="Eksik paket: boyle-bir-paket-yok.sty"):
        latex.compile_project(tmp_path, tmp_path / "a.tex", tmp_path / "out.pdf",
                              tex=tex)


@needs_tex
def test_tex_job_through_api(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    app = app_module.create_app(settings, start_background=False)
    with TestClient(app, client=("127.0.0.1", 5000)) as c:
        c.get("/api/session")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("main.tex", DOC)
        up = c.post("/api/files", files=[("files", ("Ödev 1.zip", buf.getvalue()))]).json()[0]
        assert up["kind"] == "zip"
        r = c.post("/api/jobs", json={"type": "tex_to_pdf", "files": [up["id"]]})
        assert r.status_code == 200, r.text
        job = app.state.jobs.wait(r.json()["id"], 300)
        assert job.status == "bitti", job.error
        out = app.state.store.get(job.outputs[0])
        assert out.name == "Ödev 1.pdf" and out.kind == "pdf"


@needs_tex
def test_compiles_without_perl_or_tex_on_path(tmp_path: Path, tex: Path,
                                              monkeypatch: pytest.MonkeyPatch):
    """Uygulama kısayoldan açılınca PATH'te Git'in Perl'i yok; MiKTeX'in latexmk'si bu yüzden
    çalışmıyordu. Derleme Perl'e ve PATH'e bağlı olmamalı."""
    import os
    system = os.environ.get("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("PATH", os.pathsep.join([system, os.path.join(system, "System32")]))
    _write(tmp_path, {"a.tex": r"\documentclass{article}\begin{document}\section{A}\label{a}"
                               r"Bkz. \ref{a}.\end{document}"})
    r = latex.compile_project(tmp_path, tmp_path / "a.tex", tmp_path / "out.pdf", tex=tex)
    with pymupdf.open(r.output) as doc:
        assert "Bkz. 1" in doc[0].get_text()  # ikinci geçiş yapıldı: \ref çözüldü


def _no_perl_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    system = os.environ.get("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("PATH", os.pathsep.join([system, os.path.join(system, "System32")]))


def _text(pdf: Path) -> str:
    with pymupdf.open(pdf) as doc:
        return "".join(page.get_text() for page in doc)


@needs_tex
@pytest.mark.parametrize(("name", "source", "expect"), [
    ("biblatex", r"""\documentclass{article}
\usepackage[backend=biber,style=numeric]{biblatex}
\addbibresource{k.bib}
\begin{document}Atif \cite{knuth}.\printbibliography\end{document}
""", ["TeXbook", "[1]"]),
    ("glossaries", r"""\documentclass{article}
\usepackage[acronym]{glossaries}
\makeglossaries
\newglossaryentry{derleyici}{name=derleyici,description={kaynak kodu ceviren program}}
\newacronym{pdf}{PDF}{Portable Document Format}
\begin{document}Bir \gls{derleyici} ve \gls{pdf}.\printglossaries\end{document}
""", ["kaynak kodu ceviren", "Portable Document Format"]),
    ("nomencl", r"""\documentclass{article}
\usepackage{nomencl}
\makenomenclature
\begin{document}$E=mc^2$\nomenclature{$c$}{Isik hizi}\printnomenclature\end{document}
""", ["Isik hizi"]),
    ("makeidx", r"""\documentclass{article}
\usepackage{makeidx}
\makeindex
\begin{document}Kelime\index{kelime}.\printindex\end{document}
""", ["kelime, 1"]),
])
def test_bibliography_glossary_and_index_tools_without_perl(
        tmp_path: Path, tex: Path, monkeypatch: pytest.MonkeyPatch,
        name: str, source: str, expect: list[str]):
    """biber, makeglossaries ve makeindex adımları; Perl ve TeX PATH'te değilken (MiKTeX'in
    makeglossaries'i Perl ister, makeglossaries-lite istemez)."""
    _no_perl_path(monkeypatch)
    _write(tmp_path, {"a.tex": source, "k.bib": "@book{knuth, author={Donald Knuth}, "
                      "title={The TeXbook}, year={1984}, publisher={AW}}"})
    r = latex.compile_project(tmp_path, tmp_path / "a.tex", tmp_path / "out.pdf", tex=tex)
    text = _text(r.output)
    assert all(e in text for e in expect), (name, text[:500], r.warnings)


GS = engines.detect_ghostscript(Settings()).path


@needs_tex
@pytest.mark.skipif(GS is None, reason="Ghostscript yok")
@pytest.mark.parametrize("engine", ["pdflatex", "lualatex", "xelatex"])
def test_eps_figures_with_every_engine(tmp_path: Path, tex: Path, engine: str):
    """pdfLaTeX/LuaLaTeX EPS'yi kabuk komutsuz okuyamaz; Ghostscript ile önceden çevrilir.
    (LuaLaTeX ayrıca MiKTeX'te -max-print-line'ı tanımadığı için hiç çalışmıyordu.)"""
    (tmp_path / "sekil").mkdir()
    (tmp_path / "sekil" / "ucgen.eps").write_text(
        "%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 60\n"
        "newpath 10 10 moveto 90 10 lineto 50 55 lineto closepath fill\n"
        "/Helvetica findfont 12 scalefont setfont 20 20 moveto (EPSYAZI) show\n"
        "showpage\n%%EOF\n", encoding="ascii")
    _write(tmp_path, {"a.tex": "\\documentclass{article}\\usepackage{graphicx}"
                               "\\begin{document}\\includegraphics{sekil/ucgen} "
                               "\\includegraphics[width=3cm]{sekil/ucgen.eps}\\end{document}\n"})
    r = latex.compile_project(tmp_path, tmp_path / "a.tex", tmp_path / "out.pdf", tex=tex,
                              engine=engine, ghostscript=GS)
    assert r.engine == engine
    assert _text(r.output).count("EPSYAZI") == 2, r.warnings


def test_eps_without_ghostscript_is_reported(tmp_path: Path):
    (tmp_path / "s.eps").write_text("%!PS\n", encoding="ascii")
    runner = latex._Runner(tmp_path / "pdflatex.exe", tmp_path, lambda *_: None)
    notes = latex._convert_eps(tmp_path, None, runner)
    assert notes and "Ghostscript" in notes[0]


def test_shell_escape_error_is_explained():
    log = ("./a.tex:3: Package minted Error: You must invoke LaTeX with the -shell-escape flag."
           "\nl.3 \\begin{document}\n")
    msg = str(latex.parse_errors(log)[0])
    assert "minted" in msg and "listings" in msg and "Overleaf" in msg


# --- MiKTeX ayarları ---------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, results: dict[str, tuple[int, bytes]]):
        self.results = results
        self.calls: list[list[str]] = []

    def __call__(self, args, **kw):
        import subprocess
        self.calls.append(list(args))
        name = Path(args[0]).stem
        code, out = self.results.get(name, (0, b""))
        return subprocess.CompletedProcess(args, code, out, b"")


def _fake_miktex(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "MiKTeX" / "miktex" / "bin" / "x64"
    bin_dir.mkdir(parents=True)
    for name in ("pdflatex", "initexmf", "miktex", "mpm", "kpsewhich"):
        (bin_dir / engines._exe_name(name)).write_bytes(b"")
    return bin_dir / engines._exe_name("pdflatex")


def test_configure_miktex_enables_autoinstall_and_installs_cm_super(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = _FakeProc({})
    monkeypatch.setattr(latex.proc, "run", fake)
    assert latex.configure_miktex(_fake_miktex(tmp_path)) == []
    assert fake.calls[0][1:] == ["--set-config-value=[MPM]AutoInstall=1"]
    assert fake.calls[1][1:] == ["packages", "install", "cm-super"]


def test_configure_miktex_falls_back_to_mpm_and_reports_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = _FakeProc({"miktex": (1, b"unknown command"), "mpm": (1, b"network error")})
    monkeypatch.setattr(latex.proc, "run", fake)
    notes = latex.configure_miktex(_fake_miktex(tmp_path))
    assert [c[1] for c in fake.calls[1:3]] == ["packages", "--install=cm-super"]
    assert notes == [latex.CM_SUPER_HINT]


def test_already_installed_package_counts_as_success(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(latex.proc, "run", _FakeProc(
        {"miktex": (1, b"Sorry, but: cm-super: package is already installed")}))
    assert latex.install_miktex_package(_fake_miktex(tmp_path), "cm-super")


def test_cm_super_is_installed_once_before_first_pdflatex_run(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = _FakeProc({"kpsewhich": (1, b"")})  # cm-super yok
    monkeypatch.setattr(latex.proc, "run", fake)
    monkeypatch.setattr(latex, "_CM_SUPER_CHECKED", set())
    runner = latex._Runner(_fake_miktex(tmp_path), tmp_path, lambda *_: None)
    assert latex._ensure_cm_super(runner) == []
    assert latex._ensure_cm_super(runner) == []  # ikinci derlemede yeniden denenmez
    installs = [c for c in fake.calls if "install" in c]
    assert len(installs) == 1 and installs[0][-1] == "cm-super"


# --- gerçekçi Overleaf projelerinden çıkan hatalar (2026-11-28 deneme seti) -------------------

def test_package_error_with_windows_path_and_continuation_is_parsed():
    """MiKTeX paket dosyasındaki hatayı tam Windows yoluyla yazar; ileti '(fontspec)' devam
    satırlarında sürer. Eskiden hiç okunmuyor, kullanıcı İngilizce yarım bir cümle görüyordu."""
    log = (r"C:\Users\x\AppData\Local\Programs\MiKTeX\tex\latex\fontspec\fontspec.sty:101: "
           "Fatal Package fontspec Error: The fontspec package requires either XeTeX or\n"
           "(fontspec)                      LuaTeX.\n"
           "(fontspec)                      \n"
           r"l.101 \msg_fatal:nn {fontspec} {cannot-use-pdftex}" + "\n")
    errors = latex.parse_errors(log, Path("C:/proje"))
    assert len(errors) == 1
    assert errors[0].file == "fontspec.sty" and errors[0].line == 101
    assert "XeLaTeX" in str(errors[0]) and "Otomatik" in str(errors[0])
    # TeX Live (Linux) aynı hatayı /usr/share/... yoluyla yazar.
    linux = log.replace(log.split(":101:")[0],
                        "/usr/share/texlive/texmf-dist/tex/latex/fontspec/fontspec.sty")
    assert latex.parse_errors(linux, Path("/tmp/proje"))[0].file == "fontspec.sty"


def test_emergency_stop_line_gives_file_to_previous_error():
    log = ("! LaTeX Error: File `yok.sty' not found.\n\nl.3 \\begin\n"
           "./main.tex:3: Emergency stop.\n")
    assert str(latex.parse_errors(log)[0]) == "main.tex, satır 3: Eksik paket: yok.sty"


def test_main_file_is_the_one_that_includes_others(tmp_path: Path):
    """main.tex yokken alfabede önce gelen not dosyası değil, bölümleri içeren tez seçilmeli."""
    _write(tmp_path, {
        "Proje/aaa-notes.tex": DOC,
        "Proje/thesis.tex": "\\documentclass{report}\\begin{document}\\include{bolum1}"
                            "\\end{document}",
        "Proje/bolum1.tex": "\\chapter{Bir}",
    })
    main, notes = latex.find_main(tmp_path)
    assert main.name == "thesis.tex"
    assert "aaa-notes.tex" in notes[0]


def test_included_document_is_not_main(tmp_path: Path):
    _write(tmp_path, {"a.tex": "\\documentclass{article}\\begin{document}\\input{z}"
                               "\\end{document}",
                      "z.tex": DOC})  # z de \documentclass içeriyor ama a onu içe alıyor
    assert latex.find_main(tmp_path)[0].name == "a.tex"


def test_babel_label_garbage_is_cleaned():
    name = (r"fig\relax \unskip \penalty \@M \protect\leavevmode@ifvmode \kern +.1667em"
            r"\relax :grafik")
    assert latex._clean_label(name) == "fig:grafik"


def test_turkish_babel_shorthand_hint():
    errs = [latex.TexError("Package keyval Error: hash=ab undefined.", "main.tex", 3)]
    hint = latex.babel_shorthand_hint([r"\usepackage[turkish]{babel}"], errs, "")
    assert hint and "shorthands=off" in hint
    assert latex.babel_shorthand_hint([r"\usepackage[turkish,shorthands=off]{babel}"], errs,
                                      "") is None
    assert latex.babel_shorthand_hint([r"\usepackage[english]{babel}"], errs, "") is None


def test_index_jobs_take_only_safe_makeindex_options(tmp_path: Path):
    for name in ("main.idx", "kisiler.idx", "x.idx"):
        (tmp_path / name).write_text("")
    log = ("Writing index file main.idx\nWriting index file kisiler.idx\n"
           "after calling `makeindex -s ozel.ist -l kisiler.idx'.\n"
           "after calling `makeindex -o ../../disari.ind x.idx'.\n"
           "after calling `makeindex -s ../kotu.ist ../disari.idx'.\n")
    jobs = dict(latex._index_jobs(tmp_path / "main.tex", log))
    assert jobs == {"kisiler.idx": ["-s", "ozel.ist", "-l"], "x.idx": [], "main.idx": []}


def test_biber_error_names_the_bib_file(tmp_path: Path):
    blg = tmp_path / "main.blg"
    blg.write_text(
        "[328] bibtex.pm:1519> INFO - Found BibTeX data source 'refs.bib'\n"
        r"[366] Utils.pm:479> ERROR - BibTeX subsystem: C:\Users\x\AppData\Local\Temp"
        r"\biber_tmp_2Pu0\8fe4c98_17464.utf8, line 8, syntax error: found " + '"author"\n',
        encoding="utf-8")
    assert latex._bib_errors(blg, biber=True) == ['refs.bib, line 8, syntax error: found "author"']


def test_biber_request_alone_does_not_force_tex_reruns():
    log = ("Package biblatex Warning: Please (re)run Biber on the file:\n(biblatex) main\n"
           "(biblatex) and rerun LaTeX afterwards.\n")
    assert not latex._needs_rerun(log)
    assert latex._needs_rerun(log + "LaTeX Warning: Label(s) may have changed. Rerun to get "
                                     "cross-references right.\n")


@needs_tex
def test_broken_bib_is_reported_without_wasted_passes(tmp_path: Path, tex: Path):
    _write(tmp_path, {
        "main.tex": "\\documentclass{article}\\usepackage[backend=biber]{biblatex}"
                    "\\addbibresource{refs.bib}\\begin{document}\\cite{iyi}\\end{document}",
        "refs.bib": "@book{iyi, title={A}, year={2000}}\n@book{bozuk title={B} author={C}}\n",
    })
    steps: list[str] = []
    r = latex.compile_project(tmp_path, tmp_path / "main.tex", tmp_path / "out.pdf", tex=tex,
                              on_progress=lambda _f, m: steps.append(m))
    assert any(w.startswith("Kaynakça oluşturulamadı (biber): refs.bib") for w in r.warnings)
    assert not any(".bib dosyası projede mi" in w for w in r.warnings)
    assert len(steps) <= 4, steps  # tex, biber, tex (en çok bir yeniden geçiş daha)


@needs_tex
def test_named_imakeidx_indexes_are_built(tmp_path: Path, tex: Path):
    _write(tmp_path, {"main.tex": r"""\documentclass{article}
\usepackage{imakeidx}
\makeindex
\makeindex[name=kisiler,title=Kisiler Dizini]
\begin{document}
Konu\index{konualfa}. Kisi\index[kisiler]{Euler}.
\printindex
\printindex[kisiler]
\end{document}
"""})
    r = latex.compile_project(tmp_path, tmp_path / "main.tex", tmp_path / "out.pdf", tex=tex)
    text = _text(r.output)
    assert "konualfa" in text and "Kisiler Dizini" in text and "Euler, 1" in text
    assert not any("Dizin oluşturulamadı" in w for w in r.warnings)


def test_missing_system_font_is_explained():
    log = ('./main.tex:4: Package fontspec Error: The font "Calibri" cannot be found; this may '
           "be but usually is not a fontspec bug.\n")
    assert "Yazı tipi bulunamadı: Calibri" in str(latex.parse_errors(log)[0])


# --- 2026-11-28 bağımsız denetim (LATEX_DENETIM_RAPORU.md) regresyonları ------------------------

@needs_tex
def test_k1_glossary_aux_cannot_run_shell_commands(tmp_path: Path, tex: Path):
    """K1: belge .aux'a makeglossaries-lite'ın kabuğa verdiği alanları yazabiliyordu. Artık
    makeglossaries-lite hiç çalışmıyor; .aux'taki program adı ve ek seçenekler yok sayılıyor."""
    # Eski kodla doğrulandı: bu belge makeglossaries-lite üzerinden `echo` çalıştırıp
    # kabuk-calisti.txt yaratıyordu. \@auxout yalnız \begin{document}'ten sonra açıktır;
    # hedef göreli (yolda ters eğik çizgi ya da Türkçe harf TeX'te bozulmasın).
    payload = "echo x > kabuk-calisti.txt"
    _write(tmp_path, {"main.ist": "", "main.tex": r"""\documentclass{article}
\begin{document}
\makeatletter
\newwrite\glo
\immediate\openout\glo=\jobname.glo \immediate\write\glo{x}\immediate\closeout\glo
\immediate\write\@auxout{\string\@newglossary{main}{glg}{gls}{glo}}
\immediate\write\@auxout{\string\@istfilename{main.ist}}
\immediate\write\@auxout{\string\@gls@extramakeindexopts{& PAYLOAD &}}
\immediate\write\@auxout{\string\@glsmakeindexappname{PAYLOAD}}
\makeatother
x\end{document}
""".replace("PAYLOAD", payload)})
    r = latex.compile_project(tmp_path, tmp_path / "main.tex", tmp_path / "out.pdf", tex=tex)
    assert r.output.is_file()
    assert not list(tmp_path.rglob("kabuk-calisti*"))


def test_k1_glossary_jobs_ignore_program_name_and_reject_unsafe_names(tmp_path: Path):
    main = tmp_path / "main.tex"
    (tmp_path / "main.glo").write_text("x")
    (tmp_path / "main.syg").write_text("x")
    (tmp_path / "main.ist").write_text("")
    (tmp_path / "main.aux").write_text(
        r"\@newglossary{main}{glg}{gls}{glo}" "\n"
        r"\@newglossary{sym}{slg}{sls}{syg}" "\n"
        r"\@newglossary{kotu}{../x}{-o}{glo}" "\n"
        r"\@glsmakeindexappname{calc.exe}" "\n"
        r"\@gls@extramakeindexopts{-o ../disari.ind}" "\n"
        r"\@istfilename{main.ist}" "\n", encoding="utf-8")
    jobs, notes = latex._glossary_jobs(main)
    assert jobs == [["-s", "main.ist", "-t", "main.glg", "-o", "main.gls", "main.glo"],
                    ["-s", "main.ist", "-t", "main.slg", "-o", "main.sls", "main.syg"]]
    assert any("güvenli değil" in n for n in notes)
    (tmp_path / "main.aux").write_text(r"\@newglossary{main}{glg}{gls}{glo}\@istfilename{-x.ist}")
    assert latex._glossary_jobs(main)[0] == []


@needs_tex
def test_d4_custom_glossary_type_with_nomain(tmp_path: Path, tex: Path):
    _write(tmp_path, {"main.tex": r"""\documentclass{article}
\usepackage[nomain]{glossaries}
\newglossary[slg]{symbols}{sls}{slo}{Semboller}
\makeglossaries
\newglossaryentry{pi}{type=symbols,name={$\pi$},description={pi sayisi SEMBOLACIKLAMA}}
\begin{document}\gls{pi}.\printglossary[type=symbols]\end{document}
"""})
    r = latex.compile_project(tmp_path, tmp_path / "main.tex", tmp_path / "out.pdf", tex=tex)
    assert "SEMBOLACIKLAMA" in _text(r.output)


@needs_tex
def test_k2_biber_conf_cannot_write_outside_project(tmp_path: Path, tex: Path):
    """K2: biber çalışma klasöründeki biber.conf'u okuyup çıktıyı proje dışına yazabiliyordu."""
    proj = tmp_path / "proje"
    outside = tmp_path / "disari-biber.txt"
    _write(proj, {
        "main.tex": "\\documentclass{article}\\usepackage[backend=biber]{biblatex}"
                    "\\addbibresource{k.bib}\\begin{document}\\cite{knuth}\\printbibliography"
                    "\\end{document}",
        "k.bib": "@book{knuth, author={Donald Knuth}, title={The TeXbook}, year={1984}}",
        "biber.conf": f"<config><output_file>{outside.as_posix()}</output_file></config>",
    })
    r = latex.compile_project(proj, proj / "main.tex", tmp_path / "out.pdf", tex=tex)
    assert not outside.exists()
    assert "TeXbook" in _text(r.output)  # kaynakça yine de projede doğru üretildi
    assert any("biber.conf" in w for w in r.warnings)


@needs_tex
def test_k3_remote_bib_source_is_never_fetched(tmp_path: Path, tex: Path):
    """K3: biber uzak kaynağı indiriyordu; belge diskten okuduğunu adrese koyup dışarı
    gönderebilirdi. Uzak kaynak görülünce biber hiç çalışmamalı."""
    import http.server
    import threading

    hits: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"@book{x, title={T}, year={2000}}")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/leak?secret=from_tex"
    try:
        _write(tmp_path, {"main.tex": "\\documentclass{article}\\usepackage[backend=biber]"
                          "{biblatex}\\addbibresource[location=remote]{" + url + "}"
                          "\\begin{document}\\cite{x}\\printbibliography\\end{document}"})
        r = latex.compile_project(tmp_path, tmp_path / "main.tex", tmp_path / "out.pdf",
                                  tex=tex)
    finally:
        server.shutdown()
    assert hits == []
    assert any("proje dışını gösteriyor" in w for w in r.warnings)


@pytest.mark.parametrize(("source", "bad"), [
    ("refs.bib", False), ("kaynak/refs.bib", False), ("http://x/y.bib", True),
    ("https://x/y.bib", True), ("ftp://x", True), ("//sunucu/pay/a.bib", True),
    ("\\\\sunucu\\pay\\a.bib", True), ("C:/gizli.bib", True), ("/etc/passwd", True),
    ("../disari.bib", True), ("a/../../b.bib", True), ("file:///c:/x.bib", True),
    ("&#104;ttp://x/y.bib", True),
])
def test_k3_bcf_source_classification(tmp_path: Path, source: str, bad: bool):
    bcf = tmp_path / "main.bcf"
    bcf.write_text('<bcf:controlfile><bcf:bibdata section="0"><bcf:datasource type="file" '
                   f'datatype="bibtex" glob="false">{source}</bcf:datasource></bcf:bibdata>'
                   "</bcf:controlfile>", encoding="utf-8")
    assert bool(latex.unsafe_bib_sources(bcf)) is bad


def _zip_raw(path: Path, entries: list[tuple[str, bytes]], **kw) -> Path:
    with zipfile.ZipFile(path, "w", **kw) as zf:
        for name, data in entries:
            zf.writestr(zipfile.ZipInfo(name), data)
    return path


@pytest.mark.parametrize("bad", ["sub/a.tex:gizli", "NUL", "sub/con.tex", "a?.tex", "a<b.tex",
                                 "klasor./a.tex", "a.tex ", "sub/../../x.tex", "C:x.tex"])
def test_y2_zip_rejects_ads_reserved_and_forbidden_names(tmp_path: Path, bad: str):
    z = _zip_raw(tmp_path / "p.zip", [("main.tex", b"x"), (bad, b"gizli")])
    dest = tmp_path / "proje"
    dest.mkdir()
    with pytest.raises(TooliaError, match="güvensiz"):
        latex.extract_project(z, dest)


def test_y2_backslash_directory_entry_and_file_dir_conflict(tmp_path: Path):
    z = _zip_raw(tmp_path / "w.zip", [("sub\\", b""), ("sub\\main.tex", b"x")])
    dest = tmp_path / "a"
    dest.mkdir()
    latex.extract_project(z, dest)
    assert (dest / "sub" / "main.tex").read_bytes() == b"x"
    z2 = _zip_raw(tmp_path / "c.zip", [("sub", b"dosya"), ("sub/main.tex", b"x")])
    dest2 = tmp_path / "b"
    dest2.mkdir()
    with pytest.raises(TooliaError, match="hem dosya hem klasör"):
        latex.extract_project(z2, dest2)


def test_y2_encrypted_and_corrupt_zips_give_clear_errors(tmp_path: Path):
    # Şifreli: "şifreli" bayrağı (0x1) elle konur.
    # writestr bayrağı sıfırladığı için yerel başlıkta (+6) ve merkezi dizinde (+8) elle konur.
    enc = tmp_path / "enc.zip"
    with zipfile.ZipFile(enc, "w") as zf:
        zf.writestr("main.tex", b"x" * 20)
    raw = bytearray(enc.read_bytes())
    raw[raw.find(b"PK\x03\x04") + 6] |= 0x1
    raw[raw.find(b"PK\x01\x02") + 8] |= 0x1
    enc.write_bytes(bytes(raw))
    with pytest.raises(TooliaError, match="şifreli"):
        latex.extract_project(enc, tmp_path)
    # Bozuk CRC: içerik baytı değiştirilir.
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("main.tex", b"ABCDEFGH" * 10)
    raw = bytearray(bad.read_bytes())
    i = raw.find(b"ABCDEFGH")
    raw[i] ^= 0xFF
    bad.write_bytes(bytes(raw))
    out = tmp_path / "x"
    out.mkdir()
    with pytest.raises(TooliaError, match="bozuk"):
        latex.extract_project(bad, out)


def test_y2_quota_is_shared_between_zips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(latex, "MAX_ZIP_BYTES", 1500)
    z = _zip(tmp_path / "p.zip", {"main.tex": "x" * 1000})
    quota = latex.ZipQuota()
    (tmp_path / "a").mkdir()
    latex.extract_project(z, tmp_path / "a", quota=quota)
    (tmp_path / "b").mkdir()
    with pytest.raises(TooliaError, match="1 GB"):
        latex.extract_project(z, tmp_path / "b", quota=quota)


def test_y2_compression_bomb_is_rejected_before_writing(tmp_path: Path):
    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf, \
            zf.open("main.tex", "w", force_zip64=True) as f:
        chunk = b"\0" * (1024 * 1024)
        for _ in range(120):
            f.write(chunk)
    dest = tmp_path / "proje"
    dest.mkdir()
    with pytest.raises(TooliaError, match="sıkıştırma bombası"):
        latex.extract_project(bomb, dest)
    assert not (dest / "main.tex").exists()


@needs_tex
def test_y2_job_deduplicates_files_and_rejects_dir_collision(
        settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from toolia.jobs import workers
    from toolia.jobs.models import TexToPdfRequest
    from toolia.storage import FileStore

    store = FileStore(settings.files_dir, settings.max_upload_mb)
    z = store.add_file(_zip(tmp_path / "p.zip", {"sekil/a.png": "x", "main.tex": DOC}), "p.zip")
    clash = store.add_file(_write_one(tmp_path / "sekil", "x"), "sekil")
    seen = []
    real = latex.extract_project
    monkeypatch.setattr(latex, "extract_project",
                        lambda *a, **kw: (seen.append(a[0]), real(*a, **kw))[1])
    req = TexToPdfRequest(type="tex_to_pdf", files=[z.id, z.id, z.id, clash.id])
    work = tmp_path / "is"
    work.mkdir()
    with pytest.raises(TooliaError, match="aynı adla bir klasör"):
        workers.tex_to_pdf(store, settings, req, lambda *_: None, work, "is")
    assert len(seen) == 1


def _write_one(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


@needs_tex
def test_y3_stale_pdf_is_not_returned_after_fatal_error(tmp_path: Path, tex: Path):
    """Y3: zip'le gelen ya da önceki derlemeden kalan main.pdf, ölümcül hatada başarı
    sayılıyordu. Artık hata verilir; yerinde derlemede eski PDF geri konur."""
    _write(tmp_path, {"main.tex": "\\documentclass{article}\\usepackage{boyle-bir-paket-yok}"
                                  "\\begin{document}x\\end{document}"})
    doc = pymupdf.open()
    doc.new_page()
    doc.save(tmp_path / "main.pdf")  # geçerli ama eski bir PDF
    before = (tmp_path / "main.pdf").read_bytes()
    with pytest.raises(TooliaError, match="Eksik paket"):
        latex.compile_project(tmp_path, tmp_path / "main.tex", tmp_path / "main.pdf", tex=tex)
    assert (tmp_path / "main.pdf").read_bytes() == before
    assert not (tmp_path / "main.pdf.toolia-eski").exists()


@pytest.mark.parametrize("name", ["-output-directory=x.tex", "&pdflatex.tex", "*a.tex",
                                  "yuzde%d.tex"])
def test_y4_option_like_main_names_are_rejected(tmp_path: Path, name: str):
    # Ad, dosya okunmadan önce denetlenir (Windows `*` içeren adı zaten yazamaz).
    with pytest.raises(TooliaError, match="seçenek gibi"):
        latex.compile_project(tmp_path, tmp_path / name, tmp_path / "o.pdf",
                              tex=tmp_path / "pdflatex.exe")


def test_y4_safe_name_rejects_leading_dash_and_dot():
    for bad in ("-o.idx", "-s.ist", ".gizli.ist", "a/b.idx", "a b.idx"):
        assert not latex._SAFE_NAME.match(bad), bad
    for good in ("main.idx", "kisiler.idx", "_x-1.ist"):
        assert latex._SAFE_NAME.match(good), good


@needs_tex
@pytest.mark.skipif(GS is None, reason="Ghostscript yok")
@pytest.mark.parametrize("name", ["-h", "@liste", "yuzde%d"])
def test_y4_eps_names_are_not_read_as_options(tmp_path: Path, tex: Path, name: str):
    (tmp_path / f"{name}.eps").write_text(
        "%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 60\n"
        "/Helvetica findfont 12 scalefont setfont 20 20 moveto (EPSYAZI) show\n"
        "showpage\n%%EOF\n", encoding="ascii")
    runner = latex._Runner(tex, tmp_path, lambda *_: None)
    assert latex._convert_eps(tmp_path, GS, runner) == []
    target = tmp_path / f"{name}-eps-converted-to.pdf"
    assert latex._valid_pdf(target)
    assert sorted(p.name for p in tmp_path.glob("*.pdf")) == [target.name]


def test_o1_eps_and_cm_super_respect_the_deadline(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "a.eps").write_text("%!PS\n", encoding="ascii")
    runner = latex._Runner(tmp_path / "pdflatex.exe", tmp_path, lambda *_: None)
    runner.deadline = 0  # süre çoktan doldu
    called = []
    monkeypatch.setattr(latex.proc, "run", lambda *a, **k: called.append(a))
    with pytest.raises(latex.proc.TimedOut):
        latex._convert_eps(tmp_path, "gs", runner)
    assert called == []
    runner.miktex = True
    monkeypatch.setattr(latex, "_CM_SUPER_CHECKED", set())
    monkeypatch.setattr(latex, "_CM_SUPER_FAILED", {})
    with pytest.raises(latex.proc.TimedOut):
        latex._ensure_cm_super(runner)


def test_o2_failed_cm_super_install_is_retried_later_not_forever_skipped(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(latex, "_CM_SUPER_CHECKED", set())
    monkeypatch.setattr(latex, "_CM_SUPER_FAILED", {})
    monkeypatch.setattr(latex, "has_cm_super", lambda *a, **k: False)
    results = iter([False, True])
    calls = []

    def install(*a, **k):
        calls.append(1)
        return next(results)

    monkeypatch.setattr(latex, "install_miktex_package", install)
    runner = latex._Runner(_fake_miktex(tmp_path), tmp_path, lambda *_: None)
    assert latex._ensure_cm_super(runner) == [latex.CM_SUPER_HINT]
    assert latex._ensure_cm_super(runner) == [latex.CM_SUPER_HINT]  # bir saat içinde denenmez
    assert len(calls) == 1
    latex._CM_SUPER_FAILED[str(runner.tex_path)] -= latex.CM_SUPER_RETRY_S + 1
    assert latex._ensure_cm_super(runner) == []
    assert latex._ensure_cm_super(runner) == []
    assert len(calls) == 2


def test_o4_uppercase_extension_and_same_stem_subfile(tmp_path: Path):
    _write(tmp_path, {"MAIN.TEX": DOC})
    assert latex.find_main(tmp_path)[0].name == "MAIN.TEX"
    other = tmp_path / "iki"
    _write(other, {"main.tex": "\\documentclass{article}\\begin{document}\\input{sub/main}"
                               "\\end{document}",
                   "sub/main.tex": "\\documentclass{article}\\begin{document}x\\end{document}",
                   "zeta.tex": DOC})
    main, _ = latex.find_main(other)
    assert main.relative_to(other).as_posix() == "main.tex"


@pytest.mark.parametrize(("source", "engine"), [
    ("\\documentclass{article}\\% \\usepackage{fontspec}", "xelatex"),
    ("\\documentclass{article}100\\\\% \\usepackage{fontspec}", "pdflatex"),
    ("\n" * 25 + "% !TEX program = xelatex\n" + DOC, "pdflatex"),
])
def test_d1_comment_and_magic_detection(source: str, engine: str):
    assert latex.pick_engine(source) == engine


def test_d1_fontspec_in_preamble_or_local_class(tmp_path: Path):
    _write(tmp_path, {"main.tex": "\\documentclass{tezsinifi}\\input{preamble}"
                                  "\\begin{document}x\\end{document}",
                      "preamble.tex": "\\usepackage{fontspec}"})
    main = tmp_path / "main.tex"
    assert latex.pick_engine(latex._read(main), latex._engine_sources(main)) == "xelatex"
    _write(tmp_path, {"preamble.tex": "", "tezsinifi.cls": "\\RequirePackage{luacode}"})
    assert latex.pick_engine(latex._read(main), latex._engine_sources(main)) == "lualatex"


def test_d2_unwrap_rejoins_79_char_lines():
    long = ("./main.tex:5: Package fontspec Error: The font \"Calibri\" cannot be found; this "
            "may be but usually is not a fontspec bug.")
    line = long[:79]
    log = line + "\n" + long[79:] + "\nl.5 x\n"
    assert "Yazı tipi bulunamadı: Calibri" in str(latex.parse_errors(latex._unwrap(log))[0])


def test_d2_babel_hint_with_class_option_and_bounded_biber_request():
    errs = [latex.TexError("Missing number, treated as zero.")]
    assert latex.babel_shorthand_hint(
        [r"\documentclass[turkish]{article}\usepackage{babel}"], errs, "")
    log = ("Package biblatex Warning: Please (re)run Biber on the file:\n(biblatex) main\n"
           "(biblatex) and rerun LaTeX afterwards.\n" + "x\n" * 3
           + "LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.\n"
           + "Please (re)run Biber on the file:\n(biblatex) main\n")
    assert latex._needs_rerun(log)
    assert latex.parse_errors("./MAIN.TEX:3: Undefined control sequence.\n")[0].line == 3


def test_o7_install_engine_worker_refuses_device(settings: Settings, tmp_path: Path):
    from toolia import access
    from toolia.jobs import workers
    from toolia.jobs.models import InstallEngineRequest

    req = InstallEngineRequest(type="install_engine", engine="miktex")
    token = access._owner.set("cihaz-1")
    try:
        with pytest.raises(TooliaError, match="yalnızca bu bilgisayardan"):
            workers.install_engine(None, settings, req, lambda *_: None, tmp_path, "is")
    finally:
        access._owner.reset(token)
