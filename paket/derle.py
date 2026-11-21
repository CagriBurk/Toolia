"""Masaüstü paketini üretir:
- Windows: `build/Toolia-<sürüm>/` ve `build/Toolia-<sürüm>.zip` (+ `.sha256`)
- Linux:   `build/Toolia-<sürüm>/` ve `build/Toolia-<sürüm>-linux-x86_64.tar.gz` (+ `.sha256`)

    uv run python paket/derle.py                # bu platform için paket
    uv run python paket/derle.py --motorsuz     # Windows: Tesseract/Ghostscript'siz (CI)
    uv run python paket/derle.py --linux        # Linux x86_64 tar.gz (Linux'ta çalıştır)

İçerik (kullanıcıda uv, Node, git gerekmez):
- python/        Windows: python.org İMZALI gömülü Python; Linux: python-build-standalone (Astral)
                 + site-packages (kilit dosyasındaki çalışma bağımlılıkları + toolia + web)
- motorlar/      Windows: tesseract/ + ghostscript/ (Linux'ta sistem paket yöneticisiyle kurulur)
- simgeler/      uygulama simgeleri (.ico / .png / .svg)
- Kur.cmd / Kaldir.cmd (Windows) veya kur.sh / kaldir.sh (Linux),
  OKUBENI.txt, LISANSLAR.txt, LICENSE.txt (AGPL-3.0), toolia-kurulum.json

Neden PyInstaller / Inno Setup değil: bkz. PLAN.md tuzak #52 (Akıllı Uygulama Denetimi).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "paket"))
from pe_bagimlilik import local_closure  # noqa: E402

PY_VERSION = "3.11.9"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
LINUX_PY_SPEC = "cpython-3.11-linux-x86_64-gnu"
# Bütünlük: Windows'ta HTTPS + PSF Authenticode imzası (check_signature); Linux'ta uv'nin
# yerleşik SHA-256 doğrulamalı python-build-standalone dağıtımı.
TESSERACT = Path(r"C:\Program Files\Tesseract-OCR")
GS_GLOB = r"C:\Program Files\gs\gs*"
OCR_LANGS = ("tur", "eng", "osd")

# .cmd başlatıcıları hiçbir argüman aktarmaz (`%*` yok): cmd.exe argümandaki `&`'den sonrasını
# komut olarak çalıştırır (GUVENLIK_PLANI.md, adım 1). Başka hedef klasöre kurmak için:
# python\python.exe -I -m toolia.kurulum kur <hedef>. Gönder menüsü .cmd kullanmaz; kısayolu
# doğrudan python.exe'yi çalıştırır (`kurulum.SENDTO_COMMANDS`).
KUR_CMD = """@echo off
chcp 65001 >nul
rem Toolia kurulumu: imzali Python ile kurar (yonetici izni gerekmez).
"%~dp0python\\python.exe" -I -m toolia.kurulum kur
"""
KALDIR_CMD = """@echo off
chcp 65001 >nul
"%~dp0python\\python.exe" -I -m toolia.kurulum kaldir
"""
LAUNCHERS = {"Kur.cmd": KUR_CMD, "Kaldir.cmd": KALDIR_CMD}

KUR_SH = """#!/bin/sh
set -eu
DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$DIR/python/bin/python3" -I -m toolia.kurulum kur
"""
KALDIR_SH = """#!/bin/sh
set -eu
DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$DIR/python/bin/python3" -I -m toolia.kurulum kaldir
"""
LINUX_LAUNCHERS = {"kur.sh": KUR_SH, "kaldir.sh": KALDIR_SH}

OKUBENI = """Toolia {version} — kurulum
=================================

1. Bu klasördeki "Kur" (Kur.cmd) dosyasına çift tıkla.
   Windows "Bilinmeyen yayımcı" ya da "Windows bilgisayarınızı korudu" derse:
   "Daha fazla bilgi" → "Yine de çalıştır" (dosya imzalı değil, ama içinde çalışan Python
   python.org imzalıdır). Yönetici izni istemez.
2. Kurulum bitince uygulama açılır; sonra masaüstündeki "Toolia" simgesini kullan.
3. Bu klasörü (ve indirdiğin zip'i) silebilirsin.

Kaldırmak: Ayarlar → Uygulamalar → "Toolia" → Kaldır (belgelerin silinsin mi diye sorar).
Güncellemek: yeni sürümün paketinde yine "Kur"a çift tıkla; belgelerin ve ayarların korunur.

Word / Excel / PowerPoint → PDF için LibreOffice gerekir; uygulamanın Ayarlar sayfasındaki
"LibreOffice'i kur" düğmesi kurar (ya da: winget install TheDocumentFoundation.LibreOffice).
Dosyaların bilgisayarından çıkmaz; uygulama internete bağlanmaz (yalnızca sen "Güncellemeleri
denetle" dersen GitHub'a sorar). Tek istisna: Markdown / HTML baskısında kullanılan Microsoft
Edge kendi Microsoft hizmetlerine bağlanabilir; belgenin içeriği bu bağlantıda yoktur.
"""

OKUBENI_LINUX = """Toolia {version} — Linux kurulumu
=======================================

1. Bu klasörde bir terminal aç ve kurulum betiğini çalıştır:

     ./kur.sh

   Yönetici izni istemez; uygulama ~/.local/opt/toolia altına kurulur, uygulama menüsüne
   "Toolia" simgesi ve ~/.local/bin/toolia komutu eklenir.
2. Kurulum sonunda eksik dış motorlar (LibreOffice, Tesseract + Türkçe, Ghostscript,
   Chromium/Chrome) denetlenir ve dağıtımına uygun tek kurulum komutu gösterilir.
3. Kurulum bitince bu geçici klasörü ve indirdiğin .tar.gz dosyasını silebilirsin.

Kaldırmak: ~/.local/opt/toolia/kaldir.sh (belgelerin silinsin mi diye sorar).
Güncellemek: yeni sürümün paketinde yine ./kur.sh çalıştır; belgelerin (~/.local/share/Toolia)
ve ayarların korunur.

Not (Ubuntu): Chromium veya LibreOffice Snap paketi olarak kuruluysa sandbox kısıtları sorun
çıkarabilir; Google Chrome (.deb) ve apt ile kurulu LibreOffice önerilir.
"""

LISANSLAR = """Toolia paketindeki bileşenler ve lisansları
=================================================

- Toolia: GNU AGPL v3 (LICENSE.txt), kaynak kod: https://github.com/CagriBurk/Toolia
- Python {py} (python.org, imzalı gömülü dağıtım): PSF License
- PyMuPDF / MuPDF: GNU AGPL v3 (ticari lisans ayrıca Artifex'ten)
- pikepdf / qpdf: MPL 2.0 / Apache 2.0
- OCRmyPDF: MPL 2.0
- Tesseract OCR (UB Mannheim derlemesi) ve tessdata_fast dil dosyaları: Apache 2.0
- Ghostscript (Artifex): GNU AGPL v3
- Playwright (Microsoft): Apache 2.0 — tarayıcı indirilmez, kurulu Edge kullanılır
- Noto Sans / Serif / Sans Mono (Google, Noto Project): SIL Open Font License 1.1
- KaTeX: MIT; pdf.js: Apache 2.0; React: MIT; Konva: MIT; dnd-kit: MIT
- Diğer Python kütüphaneleri: python/Lib/site-packages altında her birinin *.dist-info/
  klasöründeki LICENSE dosyaları

Toolia ve AGPL bileşenleri (PyMuPDF, Ghostscript) nedeniyle bu paketi başkasına
verirken kaynak kod erişilebilir olmalıdır: https://github.com/CagriBurk/Toolia
"""

LISANSLAR_LINUX = """Toolia Linux paketindeki bileşenler ve lisansları
=======================================================

- Toolia: GNU AGPL v3 (LICENSE.txt), kaynak kod: https://github.com/CagriBurk/Toolia
- Python {py} (python-build-standalone / Astral): PSF License
- PyMuPDF / MuPDF: GNU AGPL v3 (ticari lisans ayrıca Artifex'ten)
- pikepdf / qpdf: MPL 2.0 / Apache 2.0
- OCRmyPDF: MPL 2.0
- Playwright (Microsoft): Apache 2.0 — tarayıcı indirilmez, kurulu Chrome/Chromium/Edge kullanılır
- Noto Sans / Serif / Sans Mono (Google, Noto Project): SIL Open Font License 1.1
- KaTeX: MIT; pdf.js: Apache 2.0; React: MIT; Konva: MIT; dnd-kit: MIT
- Diğer Python kütüphaneleri: python/lib/python3.11/site-packages altında her birinin
  *.dist-info/ klasöründeki LICENSE dosyaları

Toolia ve AGPL bileşeni (PyMuPDF) nedeniyle bu paketi başkasına verirken kaynak kod
erişilebilir olmalıdır: https://github.com/CagriBurk/Toolia
"""


def log(msg: str) -> None:
    print(msg, flush=True)


class StepFailed(Exception):
    pass


def run(args: list, **kw) -> None:
    """Komutu çalıştırır; başarısızsa çıktısının sonunu hatayla birlikte verir (CI günlüğü
    kimliksiz okunamıyor: hata `::error::` annotation'ı olarak da yazılır)."""
    log("  $ " + " ".join(map(str, args)))
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", **kw)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        tail = "\n".join(out.strip().splitlines()[-25:])
        raise StepFailed(f"Komut başarısız (çıkış {r.returncode}): {Path(str(args[0])).name} "
                         f"{' '.join(map(str, args[1:4]))}...\n{tail}")
    if out.strip():
        log("\n".join("    " + ln for ln in out.strip().splitlines()[-5:]))


def ci_error(message: str) -> None:
    """GitHub Actions'ta hatayı annotation olarak yaz (API'den kimliksiz okunur)."""
    if os.environ.get("GITHUB_ACTIONS"):
        esc = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title=Paket derlenemedi::{esc}", flush=True)


def project_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"]


def fetch_python(cache: Path) -> Path:
    zip_path = cache / Path(PY_URL).name
    if not zip_path.is_file():
        log(f"İndiriliyor: {PY_URL}")
        cache.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(PY_URL, timeout=120) as resp:
            zip_path.write_bytes(resp.read())
    log(f"  sha256 {hashlib.sha256(zip_path.read_bytes()).hexdigest()}")
    return zip_path


def check_signature(exe: Path) -> None:
    """python.exe python.org (PSF) imzalı mı? Akıllı Uygulama Denetimi buna güvenir."""
    # pwsh (PowerShell 7) içinden çağrılınca devralınan PSModulePath, Windows PowerShell 5.1'in
    # güvenlik modülünü yükletmiyor (CI): temizlenir.
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"$s = Get-AuthenticodeSignature '{exe}'; "
         "\"$($s.Status)|$($s.SignerCertificate.Subject)\""],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    out = r.stdout.strip()
    status, _, subject = out.partition("|")
    if status != "Valid" or "Python Software Foundation" not in subject:
        raise SystemExit(f"{exe.name} imzası geçersiz: {out} {r.stderr.strip()[-500:]}")
    log(f"  imza: {status} ({subject.split(',')[0]})")


def build_python(dest: Path, cache: Path) -> Path:
    py = dest / "python"
    with zipfile.ZipFile(fetch_python(cache)) as zf:
        zf.extractall(py)
    check_signature(py / "python.exe")
    check_signature(py / "pythonw.exe")
    # ._pth: site-packages yolu + `import site` (.pth dosyaları işlensin). -I ile çalıştırılır:
    # kullanıcının PYTHONPATH'i ve kullanıcı site klasörü karışmaz.
    pth = next(py.glob("python*._pth"))
    pth.write_text("python311.zip\n.\nLib\\site-packages\nimport site\n", encoding="utf-8")
    return py / "Lib" / "site-packages"


def build_python_linux(dest: Path, cache: Path) -> tuple[Path, Path, str]:
    """Astral python-build-standalone CPython 3.11 (Linux x86_64, uv'nin SHA-256 doğrulamasıyla).
    Dönüş: (site_packages, python3_exe, python_version)."""
    py_cache = cache / "linux-py"
    py_cache.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "UV_PYTHON_INSTALL_DIR": str(py_cache)}
    run(["uv", "python", "install", LINUX_PY_SPEC, "--managed-python"], cwd=ROOT, env=env)
    installed = sorted(p for p in py_cache.glob("cpython-3.11*") if p.is_dir())
    if not installed:
        raise StepFailed(f"Gömülü Linux Python bulunamadı: {py_cache}")
    src = installed[-1]
    py = dest / "python"
    shutil.copytree(src, py, symlinks=True)
    py_exe = py / "bin" / "python3"
    if not py_exe.is_file():
        raise StepFailed(f"python3 çalıştırılabilir dosyası yok: {py_exe}")
    ver = subprocess.run(
        [str(py_exe), "-I", "-c", "import platform; print(platform.python_version())"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    site = py / "lib" / "python3.11" / "site-packages"
    log(f"  python-build-standalone {ver} ({src.name})")
    return site, py_exe, ver


def _requirement_names(req: Path) -> set[str]:
    import re

    from packaging.markers import Marker

    names = set()
    for line in req.read_text(encoding="utf-8").splitlines():
        spec, _, marker = line.strip().partition(";")
        m = re.match(r"^([A-Za-z0-9_.-]+)==", spec.strip())
        # İşaretçiler bu yorumlayıcıya göre (Windows, CPython 3.11) değerlendirilir.
        if m and (not marker.strip() or Marker(marker.strip()).evaluate()):
            names.add(re.sub(r"[-_.]+", "-", m.group(1)).lower())
    return names


def copy_from_venv(site: Path, req: Path) -> None:
    """Ağ yavaşken: kilit dosyasıyla eşitlenmiş yerel .venv'den yalnızca çalışma paketlerini
    (kilitteki sürümler) RECORD dosyalarına göre kopyalar. Geliştirme araçları ve düzenlenebilir
    toolia kurulumu alınmaz."""
    import re
    from importlib.metadata import distributions

    venv_site = ROOT / ".venv" / "Lib" / "site-packages"
    wanted = _requirement_names(req)
    found = set()
    for dist in distributions(path=[str(venv_site)]):
        name = re.sub(r"[-_.]+", "-", dist.metadata["Name"]).lower()
        if name not in wanted:
            continue
        found.add(name)
        for f in dist.files or []:
            src = Path(dist.locate_file(f)).resolve()
            if not src.is_file() or not src.is_relative_to(venv_site.resolve()):
                continue  # Scripts\*.exe gibi site-packages dışındakiler
            dest = site / src.relative_to(venv_site.resolve())
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
    missing = wanted - found
    if missing:
        raise SystemExit(f".venv'de olmayan çalışma paketleri: {sorted(missing)} (uv sync)")
    log(f"  .venv'den {len(found)} paket kopyalandı")


def install_packages(site: Path, work: Path, *, from_venv: bool = False) -> None:
    site.mkdir(parents=True, exist_ok=True)
    req = work / "gereksinimler.txt"
    run(["uv", "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project",
         "--format", "requirements-txt", "-o", req], cwd=ROOT)
    target = ["--target", site, "--python-version", "3.11",
              "--python-platform", "x86_64-pc-windows-msvc", "--only-binary", ":all:"]
    if from_venv:
        copy_from_venv(site, req)
    else:
        run(["uv", "pip", "install", "--quiet", *target, "-r", req], cwd=ROOT)
    wheel_dir = work / "teker"
    run(["uv", "build", "--wheel", "--out-dir", wheel_dir], cwd=ROOT)
    wheel = next(wheel_dir.glob("toolia-*.whl"))
    run(["uv", "pip", "install", "--quiet", "--no-deps", *target, wheel], cwd=ROOT)
    # Derlenmiş arayüz paketin içine: kullanıcıda Node gerekmez (paths.web_dist).
    dist = ROOT / "web" / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("Arayüz derlenmemiş: npm --prefix web run build")
    shutil.copytree(dist, site / "toolia" / "web")
    # Paket içinde çalıştırılabilir başlatıcılar gereksiz (SAC engeller, kullanılmaz).
    shutil.rmtree(site / "bin", ignore_errors=True)
    for cache_dir in site.rglob("__pycache__"):
        shutil.rmtree(cache_dir, ignore_errors=True)


def install_packages_linux(site: Path, py_exe: Path, work: Path) -> None:
    site.mkdir(parents=True, exist_ok=True)
    req = work / "gereksinimler.txt"
    run(["uv", "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project",
         "--format", "requirements-txt", "-o", req], cwd=ROOT)
    run(["uv", "pip", "install", "--quiet", "--python", py_exe, "--only-binary", ":all:",
         "-r", req], cwd=ROOT)
    wheel_dir = work / "teker"
    run(["uv", "build", "--wheel", "--out-dir", wheel_dir], cwd=ROOT)
    wheel = next(wheel_dir.glob("toolia-*.whl"))
    run(["uv", "pip", "install", "--quiet", "--no-deps", "--python", py_exe, wheel], cwd=ROOT)
    dist = ROOT / "web" / "dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("Arayüz derlenmemiş: npm --prefix web run build")
    shutil.copytree(dist, site / "toolia" / "web")
    for cache_dir in site.rglob("__pycache__"):
        shutil.rmtree(cache_dir, ignore_errors=True)


def copy_tesseract(dest: Path) -> None:
    exe = TESSERACT / "tesseract.exe"
    if not exe.is_file():
        raise SystemExit(f"Tesseract yok: {exe} (ya da --motorsuz)")
    out = dest / "tesseract"
    (out / "tessdata").mkdir(parents=True)
    shutil.copyfile(exe, out / exe.name)
    for dll in local_closure(exe):
        shutil.copyfile(dll, out / dll.name)
    for lang in OCR_LANGS:
        src = TESSERACT / "tessdata" / f"{lang}.traineddata"
        if not src.is_file():
            raise SystemExit(f"Dil dosyası yok: {src}")
        shutil.copyfile(src, out / "tessdata" / src.name)
    for sub in ("configs", "tessconfigs"):
        if (TESSERACT / "tessdata" / sub).is_dir():
            shutil.copytree(TESSERACT / "tessdata" / sub, out / "tessdata" / sub)


def copy_ghostscript(dest: Path) -> None:
    import glob

    found = sorted(glob.glob(GS_GLOB), reverse=True)
    if not found:
        raise SystemExit("Ghostscript yok (ya da --motorsuz)")
    gs = Path(found[0])
    out = dest / "ghostscript"
    (out / "bin").mkdir(parents=True)
    for name in ("gswin64c.exe", "gsdll64.dll"):
        shutil.copyfile(gs / "bin" / name, out / "bin" / name)
    for sub in ("lib", "Resource", "iccprofiles"):
        if (gs / sub).is_dir():
            shutil.copytree(gs / sub, out / sub)
    lic = gs / "doc" / "COPYING"
    if lic.is_file():
        shutil.copyfile(lic, out / "COPYING")


def make_icon(dest: Path, version: str) -> None:
    """Kelebek simgesi (tek kaynak `paket/simge.py`). Adı sürümü taşır: Windows simgeleri yola
    göre önbelleğe alır; aynı yol güncellemeden sonra eski simgeyi gösterirdi
    (`kurulum.icon_path`)."""
    from simge import write_ico

    write_ico(dest / f"toolia-{version}.ico")


def make_linux_icons(dest: Path) -> None:
    from simge import write_linux_icons

    write_linux_icons(dest)


# Pakette kullanılmayan, yalnızca yer kaplayan parçalar (site-packages'a göre, glob). Kurulu
# kütüphanelerin kendi bağımlılıklarıdır; uygulama bunlara hiç dokunmaz (~140 MB):
# - PyMuPDF 2.0'ın yapay zekâ sayfa düzeni modülü ve onun getirdikleri: tablo bulma
#   `use_layout=False` ile çalışır (to_excel.py; PLAN tuzak #78), modül yoksa PyMuPDF onu atlar.
# - PyMuPDF'in C başlık dosyaları (yalnızca derleme için).
# - OpenCV'nin video okuma kütüphanesi (ffmpeg): pdf2docx yalnız resim işler.
# smoke_test bunların gerçekten gittiğini ve Word / Excel dönüşümünün yine çalıştığını denetler.
PRUNE = (
    "pymupdf/layout", "pymupdf/mupdf-devel",
    "onnxruntime", "onnxruntime-*.dist-info",
    "networkx", "networkx-*.dist-info",
    "flatbuffers", "flatbuffers-*.dist-info",
    "google/protobuf", "google/_upb", "protobuf-*.dist-info",
    "cv2/opencv_videoio_ffmpeg*.dll",
    "cv2/opencv_videoio_ffmpeg*.so*",
)


def prune_unused(site: Path) -> int:
    """PRUNE'dakileri siler; kazanılan baytı döndürür. Eşleşmeyen kalıp hata değildir (kütüphane
    sürümü değişince parça kalkmış olabilir)."""
    freed = 0
    for pattern in PRUNE:
        for path in site.glob(pattern):
            if path.is_dir():
                freed += sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                shutil.rmtree(path)
            else:
                freed += path.stat().st_size
                path.unlink()
    google = site / "google"
    if google.is_dir() and not any(google.iterdir()):
        google.rmdir()
    return freed


def write_launchers(pkg: Path) -> None:
    """Paket kökündeki .cmd başlatıcıları: CRLF ve ASCII (cmd.exe UTF-8 BOM'u komut sanar)."""
    for fname, text in LAUNCHERS.items():
        (pkg / fname).write_bytes(text.replace("\n", "\r\n").encode("ascii"))


def write_linux_launchers(pkg: Path) -> None:
    """Linux paket kökündeki kabuk başlatıcıları: LF, UTF-8 ve +x."""
    for fname, text in LINUX_LAUNCHERS.items():
        path = pkg / fname
        path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
        path.chmod(0o755)


def write_checksum(archive: Path) -> Path:
    """`<arşiv>.sha256` (sha256sum biçimi: "<özet> *<ad>"). Release'e arşivle birlikte yüklenir;
    indiren, dosyanın değiştirilmediğini doğrulayabilir (GUVENLIK_PLANI.md, adım 9)."""
    digest = hashlib.sha256()
    with archive.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    out = archive.with_name(archive.name + ".sha256")
    out.write_text(f"{digest.hexdigest()} *{archive.name}\n", encoding="ascii", newline="\n")
    return out


def _smoke_test_with(py: Path) -> None:
    """Paketin kendi Python'uyla: bütün bağımlılıklar yükleniyor mu, motorlar bulunuyor mu?"""
    code = ("import pymupdf, pikepdf, PIL, ocrmypdf, playwright, fastapi, uvicorn, toolia;"
            "from toolia import paths, engines, settings;"
            "assert paths.install_root() is not None, 'kurulum kökü bulunamadı';"
            "assert (paths.web_dist() / 'index.html').is_file(), 'arayüz yok';"
            "assert (paths.fonts_dir() / 'NotoSans-Regular.ttf').is_file();"
            "print('sürüm', toolia.__version__, 'arayüz', paths.web_dist());"
            "[print(' ', e.name, e.ok, e.path) for e in engines.detect_all(settings.Settings())]")
    run([py, "-I", "-c", code])
    # Budanan parçalar gerçekten yok; budama yükleyici ve resim/HEIC yolunu bozmamış.
    code = ("import importlib.util as u;"
            "gone = [m for m in ('onnxruntime', 'networkx', 'flatbuffers', 'pymupdf.layout',"
            " 'google') if u.find_spec(m) is not None];"
            "assert not gone, f'budanmadı: {gone}';"
            "import cv2, pillow_heif;"
            "from toolia.convert.image_format import convert_image;"
            "print('budama tamam; cv2', cv2.__version__)")
    run([py, "-I", "-c", code])
    # PDF → Word / Excel: pdf2docx opencv'nin yerel kütüphanelerini yükler; pakette çalışsın.
    code = ("import pathlib, tempfile, pymupdf;"
            "from toolia.convert.to_word import pdf_to_word;"
            "from toolia.convert.to_excel import pdf_to_excel;"
            "d = pathlib.Path(tempfile.mkdtemp());"
            "doc = pymupdf.open(); p = doc.new_page();"
            "[p.insert_text((72 + 120 * c, 100 + 20 * r), f'h{r}{c}') for r in range(3)"
            " for c in range(2)];"
            "[p.draw_line((60, 85 + 20 * r), (300, 85 + 20 * r)) for r in range(4)];"
            "[p.draw_line((60 + 120 * c, 85), (60 + 120 * c, 145)) for c in range(3)];"
            "doc.save(d / 'a.pdf');"
            "print('word', pdf_to_word(d / 'a.pdf', d / 'a.docx').output.stat().st_size > 0);"
            "print('excel', pdf_to_excel(d / 'a.pdf', d / 'a.xlsx').table_count)")
    run([py, "-I", "-c", code])


def smoke_test(pkg: Path) -> None:
    _smoke_test_with(pkg / "python" / "python.exe")


def smoke_test_linux(pkg: Path) -> None:
    _smoke_test_with(pkg / "python" / "bin" / "python3")


def _build_windows(version: str, build: Path, work: Path, args: argparse.Namespace) -> None:
    name = f"Toolia-{version}"
    out = build / name
    shutil.rmtree(out, ignore_errors=True)
    log(f"Toolia {version} Windows paketi → {out}")

    log("1/5 Python (python.org, imzalı)")
    site = build_python(out, build / "onbellek")
    log("2/5 Python paketleri ve arayüz")
    install_packages(site, work, from_venv=args.yerel_ortam)
    log(f"  kullanılmayan parçalar çıkarıldı: {prune_unused(site) / 1024 / 1024:.0f} MB")
    log("3/5 Motorlar")
    engines_dir = out / "motorlar"
    engines_dir.mkdir()
    if not args.motorsuz:
        copy_tesseract(engines_dir)
        copy_ghostscript(engines_dir)
    log("4/5 Başlatıcılar ve belgeler")
    make_icon(out / "simgeler", version)
    write_launchers(out)
    (out / "OKUBENI.txt").write_text(OKUBENI.format(version=version), encoding="utf-8-sig")
    (out / "LISANSLAR.txt").write_text(LISANSLAR.format(py=PY_VERSION), encoding="utf-8-sig")
    (out / "LICENSE.txt").write_bytes(
        (ROOT / "LICENSE").read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    (out / "toolia-kurulum.json").write_text(json.dumps(
        {"version": version, "python": PY_VERSION, "engines": not args.motorsuz,
         "platform": "windows"}), "utf-8")
    log("5/5 Deneme")
    smoke_test(out)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    log(f"Paket: {size / 1024 / 1024:.0f} MB")
    if args.zip:
        archive = build / f"{name}.zip"
        archive.unlink(missing_ok=True)
        shutil.make_archive(str(archive.with_suffix("")), "zip", build, name)
        log(f"Zip: {archive} ({archive.stat().st_size / 1024 / 1024:.0f} MB)")
        log(f"SHA-256: {write_checksum(archive)}")


def _build_linux(version: str, build: Path, work: Path, args: argparse.Namespace) -> None:
    if os.name == "nt":
        raise SystemExit("Linux paketi Linux (veya WSL2 / CI ubuntu-latest) üzerinde üretilmeli.")
    name = f"Toolia-{version}-linux-x86_64"
    out = build / name
    shutil.rmtree(out, ignore_errors=True)
    log(f"Toolia {version} Linux paketi → {out}")

    log("1/4 Python (python-build-standalone, x86_64-linux)")
    site, py_exe, py_ver = build_python_linux(out, build / "onbellek")
    log("2/4 Python paketleri ve arayüz")
    install_packages_linux(site, py_exe, work)
    log(f"  kullanılmayan parçalar çıkarıldı: {prune_unused(site) / 1024 / 1024:.0f} MB")
    log("3/4 Başlatıcılar, simgeler ve belgeler")
    make_linux_icons(out / "simgeler")
    write_linux_launchers(out)
    (out / "OKUBENI.txt").write_text(OKUBENI_LINUX.format(version=version),
                                     encoding="utf-8", newline="\n")
    (out / "LISANSLAR.txt").write_text(LISANSLAR_LINUX.format(py=py_ver),
                                       encoding="utf-8", newline="\n")
    (out / "LICENSE.txt").write_bytes((ROOT / "LICENSE").read_bytes().replace(b"\r\n", b"\n"))
    (out / "toolia-kurulum.json").write_text(json.dumps(
        {"version": version, "python": py_ver, "engines": False, "platform": "linux-x86_64"}),
        "utf-8")
    log("4/4 Deneme")
    smoke_test_linux(out)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file() and not f.is_symlink())
    log(f"Paket: {size / 1024 / 1024:.0f} MB")
    if args.zip:
        archive = build / f"{name}.tar.gz"
        archive.unlink(missing_ok=True)
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(out, arcname=name)
        log(f"Arşiv: {archive} ({archive.stat().st_size / 1024 / 1024:.0f} MB)")
        log(f"SHA-256: {write_checksum(archive)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--linux", action="store_true", help="Linux x86_64 .tar.gz paketi üret")
    ap.add_argument("--motorsuz", action="store_true",
                    help="Windows: Tesseract/Ghostscript ekleme")
    ap.add_argument("--zip", action=argparse.BooleanOptionalAction, default=True,
                    help="Arşiv (.zip / .tar.gz) üret")
    ap.add_argument("--yerel-ortam", action="store_true",
                    help="Windows: bağımlılıkları ağdan değil kilitle eşit .venv'den al")
    args = ap.parse_args()

    version = project_version()
    build = ROOT / "build"
    work = build / "is"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        if args.linux or os.name != "nt":
            _build_linux(version, build, work, args)
        else:
            _build_windows(version, build, work, args)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    import traceback

    # CI'da konsol cp1252: "→", "ö" yazdırmak UnicodeEncodeError verir (hata yakalayıcısı da).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    try:
        main()
    except SystemExit as e:
        if e.code not in (0, None):
            ci_error(str(e.code))
        raise
    except Exception as e:
        detail = str(e) if isinstance(e, StepFailed) else traceback.format_exc()[-3000:]
        log(detail)
        ci_error(detail)
        sys.exit(1)
