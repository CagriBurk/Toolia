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
