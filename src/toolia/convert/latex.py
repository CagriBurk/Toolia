"""LaTeX → PDF: tek .tex dosyası ya da Overleaf'ten indirilen proje .zip'i.

TeX dağıtımı uygulamaya gömülmez (GB'larca); kullanıcının MiKTeX'i ya da TeX Live'ı kullanılır
(`engines.detect_latex`). Derleme Overleaf'e benzer davranır: hata olsa da PDF üretilebiliyorsa
üretilir ve hatalar uyarı olarak bildirilir; PDF çıkmazsa ilk hata satır numarasıyla gösterilir.

Güvenlik (GUVENLIK_PLANI.md): .tex dosyası bir programdır.
- `\\write18` (kabuk komutu) her zaman kapalı: `-no-shell-escape`.
- Projedeki `latexmkrc` Perl kodudur; latexmk hiç kullanılmadığı için okunmaz.
- TeX bilgisayardaki başka dosyaları okuyabilir (`\\input{C:/...}`; MiKTeX bunu engellemiyor,
  denendi). Bu yüzden derleme yalnız bu bilgisayardan istenebilir; telefon modunda kapalıdır
  (`jobs/workers.py`).
- Zip açılırken mutlak yol, `..`, bağlantı ve aşırı boyut reddedilir.
- Süre sınırı (ilk derlemede MiKTeX eksik paketleri indirebilir) ve süreç ağacını öldürme `proc`.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import stat
import subprocess
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import pymupdf

from toolia import engines, proc
from toolia.errors import TooliaError

logger = logging.getLogger("toolia.latex")
ENGINES = engines.LATEX_ENGINES
TIMEOUT_S = 15 * 60
MAX_ZIP_FILES = 5000
MAX_ZIP_BYTES = 1024 * 1024 * 1024
MAX_SCAN_BYTES = 4 * 1024 * 1024  # ana dosya ararken okunacak en büyük .tex

Progress = Callable[[float, str], None]


@dataclass
class TexResult:
    output: Path
    main: str  # proje köküne göre, "/" ile
    engine: str
    warnings: list[str] = field(default_factory=list)


# --- proje hazırlama ---------------------------------------------------------------------------

def extract_project(archive: Path, dest: Path, display_name: str | None = None) -> None:
    """Zip'i `dest` altına güvenle açar."""
    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as e:
        raise TooliaError(f"'{display_name or archive.name}' açılamadı: geçerli bir .zip "
                          "değil.") from e
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_FILES:
            raise TooliaError(f"Zip'te çok fazla dosya var ({len(infos)}; en çok "
                              f"{MAX_ZIP_FILES}).")
        if sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
            raise TooliaError("Zip açıldığında 1 GB'tan büyük oluyor; LaTeX projesi için fazla.")
        root = dest.resolve()
        for info in infos:
            name = info.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if (not parts or name.startswith("/") or ":" in parts[0] or ".." in parts):
                raise TooliaError(f"Zip'te güvensiz dosya yolu: {info.filename}")
            if parts[0] == "__MACOSX":
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                continue  # bağlantılar açılmaz
            target = (root / Path(*parts)).resolve()
            if not target.is_relative_to(root):
                raise TooliaError(f"Zip'te güvensiz dosya yolu: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)


_DOCCLASS = re.compile(r"^[^%\n]*\\documentclass\s*(\[[^\]]*\])?\s*\{([^}]*)\}", re.MULTILINE)
_MAGIC = re.compile(r"^\s*%\s*!\s*TEX\s+(?:TS-)?program\s*=\s*(\w+)", re.IGNORECASE | re.MULTILINE)


_INCLUDES = re.compile(r"\\(?:input|include|subfile|subimport\*?\{[^}]*\}|import\*?\{[^}]*\})"
                       r"\s*\{([^}]+)\}")
_BIBREF = re.compile(r"^[^%\n]*\\(?:bibliography|addbibresource)\s*(?:\[[^\]]*\])?\{",
                     re.MULTILINE)
_MAIN_NAMES = {"thesis", "tez", "paper", "report", "rapor", "makale", "article", "document",
               "ana", "belge", "manuscript", "dissertation", "ms", "proje", "odev", "ödev"}


def _code(text: str) -> str:
    """Yorumları atılmış kaynak (kaçışlı \\% korunur)."""
    return "\n".join(re.split(r"(?<!\\)%", line, maxsplit=1)[0] for line in text.splitlines())


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def find_main(root: Path, preferred: str | None = None) -> tuple[Path, list[str]]:
    """Derlenecek ana .tex dosyası ve (birden çok aday varsa) bir uyarı."""
    texs = sorted(p for p in root.rglob("*.tex")
                  if p.is_file() and "__MACOSX" not in p.relative_to(root).parts)
    if not texs:
        raise TooliaError("Projede .tex dosyası yok.")
    rel = {p: p.relative_to(root).as_posix() for p in texs}
    if preferred:
        want = preferred.strip().replace("\\", "/").strip("/")
        hits = [p for p in texs if rel[p] == want] or [p for p in texs if p.name == want]
        if not hits:
            raise TooliaError(f"Ana dosya bulunamadı: {preferred}. Projedeki .tex dosyaları: "
                              + ", ".join(rel[p] for p in texs[:10]))
        return hits[0], []
    sources = {p: _read(p) for p in texs}
    # Başka bir dosyanın \input / \include ettiği dosya ana dosya değildir.
    included = {Path(ref.strip()).stem.lower()
                for text in sources.values() for ref in _INCLUDES.findall(_code(text))}
    candidates = []
    for p in texs:
        m = _DOCCLASS.search(sources[p])
        if m:
            subfile = m.group(2).strip() in ("subfiles", "standalone")
            stem = p.stem.lower()
            name_rank = 0 if stem == "main" else 1 if stem in _MAIN_NAMES else 2
            pulls = bool(_INCLUDES.search(_code(sources[p])) or _BIBREF.search(sources[p]))
            candidates.append((subfile, stem in included, name_rank, not pulls,
                               len(rel[p].split("/")), -len(sources[p]), rel[p], p))
    if not candidates:
        if len(texs) == 1:
            return texs[0], []
        raise TooliaError("Projede \\documentclass içeren bir .tex dosyası bulunamadı; ana "
                          "dosyanın adını yaz.")
    candidates.sort()
    main = candidates[0][-1]
    others = [c[-2] for c in candidates[1:] if not c[0] and not c[1]]
    notes = []
    if others:
        shown = ", ".join(others[:5]) + (" …" if len(others) > 5 else "")
        notes.append(f"Ana dosya olarak {rel[main]} derlendi (başka adaylar: {shown}). "
                     "Başkası gerekiyorsa ana dosyanın adını yaz.")
    return main, notes


def pick_engine(source: str) -> str:
    """`% !TEX program = xelatex` yorumu; yoksa paketlere bakılır (Overleaf'in varsayılanı
    pdfLaTeX'tir ama fontspec'li bir belge onunla derlenmez)."""
    if m := _MAGIC.search(source):
        name = m.group(1).lower()
        if name in ENGINES:
            return name
    code = "\n".join(line.split("%", 1)[0] for line in source.splitlines())
    if re.search(r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*\b(?:luacode|luatexbase|"
                 r"luaotfload)\b", code) or "\\directlua" in code:
        return "lualatex"
    if re.search(r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*\b(?:fontspec|"
                 r"unicode-math|polyglossia|xeCJK)\b", code):
        return "xelatex"
    return "pdflatex"


# --- günlük (log) okuma ------------------------------------------------------------------------

@dataclass
class TexError:
    message: str
    file: str | None = None
    line: int | None = None
    context: str | None = None

    def __str__(self) -> str:
        where = (f"{self.file}, satır {self.line}: " if self.file and self.line else
                 f"Satır {self.line}: " if self.line else "")
        text = where + _friendly(self.message)
        return text + (f" ({self.context})" if self.context else "")


_FILE_LINE = re.compile(r"^(?P<file>(?:\.{1,2}[\\/]|[A-Za-z]:[\\/])?[^\s:][^:\n]*?\.(?:tex|sty|"
                        r"cls|bbl|aux|toc|ldf|def|cfg|clo|fd|ltx|lbx|cbx|bbx)):(?P<line>\d+): "
                        r"(?P<msg>.+)$")
_CONTEXT = re.compile(r"^l\.(\d+)\s?(.*)$")
# Paket hatasının devam satırları: "(fontspec)                 or LuaTeX ..."
_CONTINUATION = re.compile(r"^\(([\w@.-]+)\)\s+(.*)$")


def _friendly(msg: str) -> str:
    msg = msg.strip()
    if m := re.search(r"File [`']([^`']+)' not found", msg):
        name = m.group(1)
        kind = "paket" if name.endswith((".sty", ".cls")) else "dosya"
        return f"Eksik {kind}: {name}"
    if "shell-escape" in msg or "shell escape" in msg.lower():
        return ("Bu belge kabuk komutu (shell-escape) isteyen bir paket kullanıyor (ör. minted, "
                "svg). Toolia güvenlik için kabuk komutlarını kapatır; minted yerine listings "
                "kullanabilir ya da bu belgeyi Overleaf'te derleyebilirsin")
    if re.search(r"(fontspec|unicode-math|polyglossia)\S* package requires either XeTeX or "
                 r"LuaTeX|requires (?:either )?XeTeX or LuaTeX", msg):
        return ("Bu belge XeLaTeX ya da LuaLaTeX ister (fontspec); derleyiciyi Otomatik ya da "
                "XeLaTeX seç")
    if m := re.search(r"The font \"([^\"]+)\" cannot be found", msg):
        return (f"Yazı tipi bulunamadı: {m.group(1)} (bu bilgisayarda kurulu değil; kur ya da "
                "belgede başka bir yazı tipi seç)")
    if msg.startswith("Undefined control sequence"):
        return "Tanımsız komut (yazım hatası ya da eksik \\usepackage)"
    if msg.startswith("Missing $ inserted"):
        return "Matematik kipi dışında matematik karakteri ($ eksik)"
    if m := re.match(r"(?:Fatal )?Package (\S+) Error: (.+)", msg):
        return f"{m.group(1)} paketi: {m.group(2)}"
    if m := re.match(r"LaTeX Error: (.+)", msg):
        return m.group(1)
    return msg


def _short(path: str) -> str:
    path = path.replace("\\", "/")
    return path[2:] if path.startswith("./") else path


_NOISE = ("Emergency stop", "==> Fatal error occurred", "Job aborted", "job aborted")


def _relative(path: str, base: Path | None) -> str:
    path = _short(path)
    if base is not None:
        try:
            return Path(path).resolve().relative_to(base.resolve()).as_posix()
        except (ValueError, OSError):
            pass
        # Paket dosyası: tam yol yerine yalnız adı (MiKTeX "C:/...", TeX Live "/usr/share/...").
        if path.startswith("/") or re.match(r"^[A-Za-z]:/", path):
            return PurePosixPath(path).name
    return path


def parse_errors(log: str, base: Path | None = None) -> list[TexError]:
    """Günlükteki hatalar, sırayla. `-file-line-error` ile hatalar `dosya:satır: ileti`
    biçimindedir (MiKTeX paket dosyalarında `C:\\...\\x.sty:12:` tam Windows yolu yazar);
    bazıları (ölümcül olanlar) hâlâ `! ileti` ile başlar. Dosya yolu `base`'e göre gösterilir."""
    lines = log.splitlines()
    errors: list[TexError] = []
    for i, line in enumerate(lines):
        err = None
        if m := _FILE_LINE.match(line):
            err = TexError(m.group("msg"), _relative(m.group("file"), base),
                           int(m.group("line")))
        elif line.startswith("! "):
            err = TexError(line[2:])
        if err is None:
            continue
        if err.message.strip().startswith(_NOISE):
            # "./a.tex:4: Emergency stop." önceki hatanın hangi dosyada olduğunu söyler.
            if errors and errors[-1].file is None and err.file:
                errors[-1].file = err.file
            continue
        for nxt in lines[i + 1:i + 6]:
            if c := _CONTINUATION.match(nxt):
                err.message = err.message.rstrip() + " " + c.group(2).strip()
            else:
                break
        for nxt in lines[i + 1:i + 12]:
            if c := _CONTEXT.match(nxt):
                err.line = err.line or int(c.group(1))
                snippet = c.group(2).strip()
                # Eksik paket bağlamı ("\begin") yanıltıcı: TeX bir sonraki satırı gösterir.
                if snippet and "not found" not in err.message:
                    err.context = snippet[-60:]
                break
        if errors and str(errors[-1]) == str(err):
            continue
        errors.append(err)
    return errors


def _clean_label(name: str) -> str:
    """babel kısaltmaları etkinken etiket adı açılmış komutlarla gelir:
    'fig\\relax \\unskip ... \\kern +.1667em\\relax :grafik' → 'fig:grafik'."""
    if "\\" not in name:
        return name
    name = re.sub(r"\\[A-Za-z@]+|\\.", " ", name)
    name = re.sub(r"[+-]?\d*\.?\d+(?:em|pt|ex)", " ", name)
    return re.sub(r"\s+", "", name)


def log_warnings(log: str, *, bib_failed: bool = False) -> list[str]:
    out = []
    cites = sorted(set(re.findall(r"Citation [`']([^`']+)' (?:on page \d+ )?undefined", log)))
    if cites:
        shown = ", ".join(cites[:5]) + (" …" if len(cites) > 5 else "")
        out.append(f"Tanımsız kaynak (atıf) {len(cites)} tane: {shown}."
                   + ("" if bib_failed else " .bib dosyası projede mi?"))
    refs = sorted({_clean_label(r) for r in
                   re.findall(r"Reference [`']([^']+)' on page \d+ undefined", log)})
    if refs:
        shown = ", ".join(refs[:5]) + (" …" if len(refs) > 5 else "")
        out.append(f"Tanımsız etiket (\\ref) {len(refs)} tane: {shown}.")
    missing_ind = sorted(set(re.findall(r"No file ([^\s]+\.ind)\.", log)))
    if missing_ind:
        out.append(f"Dizin oluşturulamadı: {', '.join(missing_ind)}.")
    return out


# babel'in Türkçe (ve birkaç başka dilin) kısaltmaları = : ! karakterlerini etkin yapar; bu,
# cleveref, biblatex ve \includegraphics[width=...] gibi yerlerde garip hatalara yol açar.
_SHORTHAND_ERRORS = ("Missing \\endcsname inserted", "Missing number, treated as zero",
                     "keyval Error", "Package keyval Error", "Argument of \\@sect")
_TURKISH_BABEL = re.compile(r"\\usepackage\s*\[([^\]]*\bturkish\b[^\]]*)\]\s*\{babel\}")


def babel_shorthand_hint(sources: list[str], errors: list[TexError], log: str) -> str | None:
    suspicious = (any(e.message.startswith(_SHORTHAND_ERRORS) or "keyval Error" in e.message
                      for e in errors)
                  or bool(re.search(r"Reference [`'][^']*\\relax", log)))
    if not suspicious:
        return None
    for text in sources:
        m = _TURKISH_BABEL.search(_code(text))
        if m and "shorthands" not in m.group(1):
            return ("Türkçe babel'in kısaltmaları (= : ! karakterleri) bu hatalara yol açıyor "
                    "olabilir: \\usepackage[turkish,shorthands=off]{babel} yazmayı dene.")
    return None


def _bitmap_font_warning(pdf: Path) -> list[str]:
    try:
        with pymupdf.open(pdf) as doc:
            for page in doc.pages(0, min(doc.page_count, 20)):
                if any(f[2] == "Type3" for f in page.get_fonts()):
                    fix = ("miktex packages install cm-super" if engines.on_windows()
                           else "sudo apt install cm-super")
                    return ["PDF'te bitmap (Type 3) yazı tipi var: yakınlaştırınca bulanık "
                            "görünür, Türkçe harfler aranamaz ya da kopyalanamaz. Çoğunlukla "
                            f"cm-super eksiktir ({fix}); ya da belgeye \\usepackage{{lmodern}} "
                            "ekle."]
    except Exception:  # yalnız bilgi amaçlı
        return []
    return []


# --- derleme -----------------------------------------------------------------------------------
# latexmk kullanılmaz: MiKTeX'teki latexmk Perl ister ve MiKTeX Perl getirmez (denendi: Git'in
# Perl'i PATH'te değilse "could not find the script engine 'perl'"). latexmk'nin -norc ile
# yaptığının aynısı burada: motor → (biber | bibtex) → makeindex → gerektikçe yeniden motor.

MAX_PASSES = 5
_RERUN = re.compile(r"Rerun to get|Label\(s\) may have changed|Please rerun LaTeX|"
                    r"Rerun LaTeX|Table widths have changed", re.IGNORECASE)
# biblatex "Please (re)run Biber ... and rerun LaTeX afterwards" der; biber zaten çalıştı (ya da
# başarısız oldu), yalnız TeX'i yeniden çalıştırmak bir şey değiştirmez.
_BIBER_REQUEST = re.compile(r"Please \(re\)run Biber.*?afterwards", re.DOTALL)


def _needs_rerun(log: str) -> bool:
    return bool(_RERUN.search(_BIBER_REQUEST.sub("", log)))


_BIBDATA = re.compile(r"\\bibdata\{")


class _Runner:
    """Derleme adımlarını tek süre sınırı içinde çalıştırır."""

    def __init__(self, tex: Path, cwd: Path, report: Progress) -> None:
        self.tex_path = tex
        self.bin = tex.parent
        self.cwd = cwd
        self.report = report
        self.deadline = time.monotonic() + TIMEOUT_S
        self.env = dict(os.environ)
        # Motor kendi yardımcılarını adıyla çağırır: yeni kurulan MiKTeX henüz PATH'te olmayabilir.
        self.env["PATH"] = str(self.bin) + os.pathsep + self.env.get("PATH", "")
        self.env["max_print_line"] = "1000"  # TeX Live: günlük satırları 79 karakterde bölünmesin
        self.miktex = engines.is_miktex(tex)
        self.steps = 0

    def tool(self, name: str) -> Path | None:
        return engines.latex_engine_path(self.tex_path, name)

    def run(self, exe: Path, args: list[str], label: str) -> tuple[int, str]:
        self.steps += 1
        self.report(min(0.9, 0.05 + 0.13 * self.steps), f"{label} ({self.steps}. adım)")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise proc.TimedOut()
        try:
            # stdin kapalı: TeX hiçbir durumda girdi beklerken takılmasın.
            return proc.run_lines([str(exe), *args], timeout=remaining, on_line=lambda _l: None,
                                  cwd=self.cwd, env=self.env, stdin=subprocess.DEVNULL)
        except FileNotFoundError as e:
            raise TooliaError(f"{exe.name} başlatılamadı: {exe}") from e

    def tex(self, exe: Path, main: Path) -> tuple[int, str]:
        args = ["-interaction=nonstopmode", "-file-line-error", "-no-shell-escape"]
        if self.miktex:
            # MiKTeX "eksik paketi sor" ayarındaysa görünmez pencerede takılır: sormadan kursun.
            args.append("--enable-installer")
            if exe.stem.lower() != "lualatex":  # MiKTeX'in lualatex'i bu seçeneği tanımıyor
                args.append("-max-print-line=1000")
        return self.run(exe, [*args, main.name], exe.stem)


def _read_log(main: Path) -> str:
    p = main.with_suffix(".log")
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


# --- MiKTeX ayarları ---------------------------------------------------------------------------
# Taze MiKTeX'te cm-super yok: T1 kodlamalı belgeler (Overleaf şablonlarının çoğu) bitmap
# yazı tipiyle çıkar, yakınlaştırınca bulanık görünür. MiKTeX'in "eksik paketi kur" ayarı da
# "önce sor" olabilir; motorlara --enable-installer verilir, bibtex/biber için ayar da açılır.

_CM_SUPER_CHECKED: set[str] = set()


def has_cm_super(tex: Path) -> bool | None:
    """cm-super kurulu mu? Bilinemiyorsa None."""
    kpse = engines.latex_engine_path(tex, "kpsewhich")
    if kpse is None:
        return None
    try:
        r = proc.run([str(kpse), "sfrm1000.pfb"], timeout=30, stdin=subprocess.DEVNULL)
    except (proc.TimedOut, OSError):
        return None
    return r.returncode == 0 and bool((r.stdout or b"").strip())


def install_miktex_package(tex: Path, package: str, timeout: float = 15 * 60) -> bool:
    """MiKTeX paketini kurar (zaten kuruluysa da True)."""
    attempts = []
    if miktex := engines.latex_engine_path(tex, "miktex"):
        attempts.append([str(miktex), "packages", "install", package])
    if mpm := engines.latex_engine_path(tex, "mpm"):
        attempts.append([str(mpm), f"--install={package}"])
    for args in attempts:
        try:
            r = proc.run(args, timeout=timeout, stdin=subprocess.DEVNULL)
        except (proc.TimedOut, OSError):
            continue
        text = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").lower()
        if r.returncode == 0 or "already installed" in text:
            return True
        logger.warning("MiKTeX paketi kurulamadı (%s): %s", package, text[-500:])
    return False


def configure_miktex(tex: Path) -> list[str]:
    """Yeni kurulan MiKTeX'i hazırlar: eksik paketler sormadan insin, cm-super kurulsun.
    Sorunları uyarı olarak döndürür (kurulumu başarısız saymaz)."""
    notes = []
    if initexmf := engines.latex_engine_path(tex, "initexmf"):
        try:
            proc.run([str(initexmf), "--set-config-value=[MPM]AutoInstall=1"], timeout=60,
                     stdin=subprocess.DEVNULL)
        except (proc.TimedOut, OSError):
            notes.append("MiKTeX'te eksik paketlerin kendiliğinden kurulması açılamadı; MiKTeX "
                         "Console → Ayarlar'dan 'Always install missing packages' seç.")
    if not install_miktex_package(tex, "cm-super"):
        notes.append(CM_SUPER_HINT)
    else:
        _CM_SUPER_CHECKED.add(str(tex))
    # biber ilk çalıştırmada kendini açar (~100 MB, birkaç dakika); bunu kurulumda yapalım ki
    # ilk kaynakçalı derleme takılmış gibi görünmesin. Başarısızlığı önemsiz.
    if biber := engines.latex_engine_path(tex, "biber"):
        with contextlib.suppress(proc.TimedOut, OSError):
            proc.run([str(biber), "--version"], timeout=10 * 60, stdin=subprocess.DEVNULL)
    return notes


CM_SUPER_HINT = ("cm-super yazı tipleri kurulamadı; T1 kodlamalı belgeler bulanık (bitmap) "
                 "yazı tipiyle çıkabilir. Elle: miktex packages install cm-super")


def _ensure_cm_super(runner: _Runner) -> list[str]:
    """MiKTeX'te cm-super yoksa ilk pdfLaTeX derlemesinden önce bir kez kurmayı dener."""
    key = str(runner.tex_path)
    if not runner.miktex or key in _CM_SUPER_CHECKED:
        return []
    _CM_SUPER_CHECKED.add(key)
    if has_cm_super(runner.tex_path) is not False:
        return []
    runner.report(0.03, "Yazı tipleri (cm-super) kuruluyor; yalnız ilk seferde")
    return [] if install_miktex_package(runner.tex_path, "cm-super") else [CM_SUPER_HINT]


# --- EPS şekiller ------------------------------------------------------------------------------
# pdfLaTeX / LuaLaTeX EPS'yi okuyamaz; epstopdf paketi çevirmek için kabuk komutu ister, o da
# kapalı. epstopdf, çevrilmiş dosya (`ad-eps-converted-to.pdf`) zaten varsa onu kullanır: biz
# Ghostscript ile (-dSAFER) önceden çeviririz.

MAX_EPS = 200


def _convert_eps(root: Path, ghostscript: str | Path | None, runner: _Runner) -> list[str]:
    eps_files = [p for p in root.rglob("*") if p.suffix.lower() == ".eps" and p.is_file()]
    todo = [p for p in eps_files
            if not p.with_name(p.stem + "-eps-converted-to.pdf").exists()]
    if not todo:
        return []
    if not ghostscript:
        return [f"Projede {len(todo)} EPS şekil var; çevirmek için Ghostscript gerekiyor (Ayarlar "
                "→ Motorlar). EPS şekiller PDF'te eksik olabilir."]
    failed = []
    runner.report(0.03, f"{len(todo)} EPS şekil PDF'e çevriliyor")
    for eps in todo[:MAX_EPS]:
        target = eps.with_name(eps.stem + "-eps-converted-to.pdf")
        try:
            r = proc.run([str(ghostscript), "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dEPSCrop",
                          "-sDEVICE=pdfwrite", f"-sOutputFile={target}", str(eps)],
                         timeout=120, stdin=subprocess.DEVNULL, cwd=eps.parent)
            if r.returncode != 0 or not _valid_pdf(target):
                failed.append(eps.name)
                target.unlink(missing_ok=True)
        except (proc.TimedOut, OSError):
            failed.append(eps.name)
            target.unlink(missing_ok=True)
    notes = []
    if failed:
        notes.append(f"EPS şekil çevrilemedi: {', '.join(failed[:5])}"
                     + (" …" if len(failed) > 5 else ""))
    if len(todo) > MAX_EPS:
        notes.append(f"Yalnız ilk {MAX_EPS} EPS şekil çevrildi.")
    return notes


def compile_project(root: Path, main: Path, out: Path, *, tex: str | Path,
                    engine: str = "auto", on_progress: Progress | None = None,
                    ghostscript: str | Path | None = None) -> TexResult:
    """`main`'i (root altında) derler, PDF'i `out`'a koyar. `tex`: pdflatex'in yolu (öbür
    motorlar ve bibtex/biber/makeindex onun yanında ya da PATH'te aranır). `ghostscript`: EPS
    şekilleri PDF'e çevirmek için."""
    report = on_progress or (lambda _f, _m: None)
    tex = Path(tex)
    chosen = pick_engine(_read(main)) if engine == "auto" else engine
    if chosen not in ENGINES:
        raise TooliaError(f"Bilinmeyen LaTeX motoru: {engine}")
    runner = _Runner(tex, main.parent, report)
    exe = runner.tool(chosen)
    if exe is None:
        raise TooliaError(f"{chosen} bu bilgisayarda yok; TeX dağıtımına ekle ya da başka "
                          "motor seç.")
    aux = _AuxState()
    pdf = main.with_suffix(".pdf")
    try:
        if chosen != "xelatex":  # XeLaTeX EPS'yi kendisi (xdvipdfmx) çevirir
            aux.notes += _convert_eps(root, ghostscript, runner)
        if chosen == "pdflatex":
            aux.notes += _ensure_cm_super(runner)
        code, tail = runner.tex(exe, main)
        passes = 1
        log = _read_log(main)
        if _valid_pdf(pdf):  # ölümcül hatada yeniden denemenin anlamı yok
            rerun = _aux_tools(runner, main, log, aux) or _needs_rerun(log)
            while rerun and passes < MAX_PASSES:
                code, tail = runner.tex(exe, main)
                passes += 1
                log = _read_log(main)
                # Yeni dizin dosyası çıktıysa (ilk geçişte yazılmamış) bir kez daha işle.
                rerun = _aux_tools(runner, main, log, aux, only_new=True) or _needs_rerun(log)
    except proc.TimedOut:
        raise TooliaError(f"LaTeX derlemesi {TIMEOUT_S // 60} dakikada bitmedi. Belgede sonsuz "
                          "döngü olabilir ya da MiKTeX çok sayıda paket indiriyordur; yeniden "
                          "dene.") from None

    errors = parse_errors(log, main.parent)
    tex_sources = [_read(p) for p in root.rglob("*.tex") if p.is_file()][:200]
    hint = babel_shorthand_hint(tex_sources, errors, log)
    if not _valid_pdf(pdf):
        logger.info("LaTeX PDF üretmedi (%s, çıkış %s). Çıktının sonu:\n%s", main.name, code,
                    tail)
        if errors:
            raise TooliaError("LaTeX derlenemedi. " + str(errors[0])
                              + (f" (+{len(errors) - 1} hata daha)" if len(errors) > 1 else "")
                              + (f" {hint}" if hint else ""))
        detail = _tail_hint(tail)
        raise TooliaError("LaTeX derlenemedi; PDF üretilmedi." + (f" {detail}" if detail else ""))
    if pdf.resolve() != Path(out).resolve():
        shutil.move(str(pdf), out)
    warnings = []
    if errors:
        warnings.append(f"Belgede {len(errors)} hata var; PDF yine de üretildi (Overleaf gibi). "
                        f"İlk hata: {errors[0]}")
    if hint:
        warnings.append(hint)
    warnings += aux.notes + log_warnings(log, bib_failed=aux.bib_failed)
    if chosen == "pdflatex":
        warnings += _bitmap_font_warning(out)
    if any((main.parent / n).is_file() for n in ("latexmkrc", ".latexmkrc")):
        warnings.append("Projedeki latexmkrc okunmadı (Perl kodu çalıştırılmaz); özel derleme "
                        "kuralı gerekiyorsa PDF eksik olabilir.")
    return TexResult(out, main.relative_to(root).as_posix(), chosen, warnings)


@dataclass
class _AuxState:
    notes: list[str] = field(default_factory=list)
    bib_failed: bool = False
    indexes_done: set[str] = field(default_factory=set)


_SAFE_NAME = re.compile(r"^[\w.-]+$")
# imakeidx (kabuk komutu kapalıyken) ne çalıştırılacağını yazar:
#   ... Remember to run (pdf)latex again after calling `makeindex -s x.ist kisiler.idx'.
_IMAKEIDX = re.compile(r"after calling\s+[`']makeindex\s+([^'\n]+)'")
_WRITING_IDX = re.compile(r"Writing index file\s+(\S+\.idx)")


def _index_jobs(main: Path, log: str) -> list[tuple[str, list[str]]]:
    """Çalıştırılacak makeindex işleri: (idx adı, ek seçenekler). Seçenekler belgeden geldiği
    için yalnız `-s stil.ist` (klasörsüz ad) ve birkaç zararsız bayrak geçer; `-o`, `-t` yok."""
    jobs: dict[str, list[str]] = {}
    for cmd in _IMAKEIDX.findall(log):
        tokens = cmd.split()
        if not tokens or not tokens[-1].endswith(".idx") or not _SAFE_NAME.match(tokens[-1]):
            continue
        opts: list[str] = []
        it = iter(tokens[:-1])
        for tok in it:
            if tok == "-s":
                style = next(it, "")
                if _SAFE_NAME.match(style) and style.endswith(".ist"):
                    opts += ["-s", style]
            elif tok in ("-l", "-g", "-q", "-c", "-r"):
                opts.append(tok)
        jobs[tokens[-1]] = opts
    for name in _WRITING_IDX.findall(log):
        name = Path(name).name
        if _SAFE_NAME.match(name):
            jobs.setdefault(name, [])
    if main.with_suffix(".idx").is_file():
        jobs.setdefault(main.stem + ".idx", [])
    return [(name, opts) for name, opts in jobs.items() if (main.parent / name).is_file()]


def _bib_errors(blg: Path, biber: bool) -> list[str]:
    text = blg.read_text(encoding="utf-8", errors="replace") if blg.is_file() else ""
    if biber:
        # "[366] Utils.pm:479> ERROR - BibTeX subsystem: C:\...\biber_tmp_x\<özet>.utf8, line 8,
        # syntax error: ..." — geçici kopyanın yerine (tek kaynak varsa) .bib'in adı yazılır.
        found = re.findall(r"ERROR - (.+)$", text, re.MULTILINE)
        sources = re.findall(r"Found BibTeX data source '([^']+)'", text)
        name = Path(sources[0]).name if len(sources) == 1 else "kaynak dosya"
        return [re.sub(r"\S+\.utf8", name, e).replace("BibTeX subsystem: ", "").strip()
                for e in found]
    return [ln.strip() for ln in text.splitlines()
            if re.search(r"---line \d+ of file|I couldn't open|I found no", ln)]


def _aux_tools(runner: _Runner, main: Path, log: str, state: _AuxState, *,
               only_new: bool = False) -> bool:
    """Kaynakça (biber ya da bibtex), dizinler (makeindex), sözlük ve kısaltma listesi. Bir şey
    çalıştıysa True. `only_new`: yeniden geçişten sonra yalnız henüz işlenmemiş dizinler."""
    ran = False
    stem = main.stem
    if not only_new:
        if main.with_suffix(".bcf").is_file():  # biblatex
            if biber := runner.tool("biber"):
                code, _ = runner.run(biber, [stem],
                                     "biber (ilk çalıştırmada birkaç dakika sürebilir)")
                ran = True
                if code != 0:
                    state.bib_failed = True
                    errs = _bib_errors(main.with_suffix(".blg"), biber=True)
                    state.notes.append("Kaynakça oluşturulamadı (biber): "
                                       + (errs[0] if errs else f"çıkış kodu {code}"))
            else:
                state.notes.append("biber bulunamadı; kaynakça boş kalabilir (biblatex biber "
                                   "ister).")
        else:
            aux = main.with_suffix(".aux")
            text = aux.read_text(encoding="utf-8", errors="replace") if aux.is_file() else ""
            if _BIBDATA.search(text):
                if bibtex := runner.tool("bibtex"):
                    code, _ = runner.run(bibtex, [stem], "bibtex")
                    ran = True
                    errs = _bib_errors(main.with_suffix(".blg"), biber=False)
                    if code >= 2 or errs:
                        state.bib_failed = True
                        state.notes.append("Kaynakça oluşturulamadı (bibtex): "
                                           + (errs[0] if errs else f"çıkış kodu {code}"))
                else:
                    state.notes.append("bibtex bulunamadı; kaynakça boş kalabilir.")
    makeindex = runner.tool("makeindex")
    if makeindex:
        for name, opts in _index_jobs(main, log):
            if name in state.indexes_done:
                continue
            state.indexes_done.add(name)
            runner.run(makeindex, [*opts, name], "makeindex")
            ran = True
    if only_new:
        return ran
    # glossaries: makeglossaries Perl ister; makeglossaries-lite (texlua) ya da makeindex.
    if main.with_suffix(".glo").is_file() or main.with_suffix(".acn").is_file():
        if lite := runner.tool("makeglossaries-lite"):
            runner.run(lite, [stem], "makeglossaries")
            ran = True
        elif makeindex and main.with_suffix(".ist").is_file():
            for src, out, glg in ((".glo", ".gls", ".glg"), (".acn", ".acr", ".alg")):
                if main.with_suffix(src).is_file():
                    runner.run(makeindex, ["-s", stem + ".ist", "-t", stem + glg,
                                           "-o", stem + out, stem + src], "makeindex")
            ran = True
        else:
            state.notes.append("Sözlük (glossaries) için makeglossaries-lite bulunamadı; sözlük "
                               "boş kalabilir.")
    if main.with_suffix(".nlo").is_file() and makeindex:  # nomencl
        runner.run(makeindex, [stem + ".nlo", "-s", "nomencl.ist", "-o", stem + ".nls"],
                   "makeindex")
        ran = True
    return ran


def _valid_pdf(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with pymupdf.open(path) as doc:
            return doc.page_count > 0
    except Exception:
        return False


def _tail_hint(tail: str) -> str:
    """Son adımın çıktısından okunur bir neden (ör. biber hatası)."""
    for line in reversed(tail.splitlines()):
        line = line.strip()
        if not line or "major issue" in line or "MiKTeX updates" in line:
            continue
        if re.search(r"error|not found|failed|hata", line, re.IGNORECASE):
            return line[:300]
    return ""
