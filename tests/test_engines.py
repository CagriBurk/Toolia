import sys
from pathlib import Path

import pytest

from toolia import engines
from toolia.settings import EnginePaths, Settings


def test_detect_all_reports_every_engine(settings: Settings):
    keys = [e.key for e in engines.detect_all(settings)]
    assert keys == ["libreoffice", "browser", "tesseract", "ghostscript"]


def test_missing_override_path_means_unavailable(tmp_path: Path):
    s = Settings(engines=EnginePaths(libreoffice=str(tmp_path / "yok.exe")))
    status = engines.detect_libreoffice(s)
    assert not status.available
    assert not status.ok
    assert status.install_hint


def test_tesseract_missing_language_is_a_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    exe = tmp_path / "tesseract.exe"
    exe.write_bytes(b"")
    outputs = {
        "--version": "tesseract v5.4.0.20240606\n leptonica-1.84.1\n",
        "--list-langs": 'List of available languages in "C:\\tessdata/" (2):\neng\nosd\n',
    }
    monkeypatch.setattr(engines, "_run", lambda args: outputs[args[1]])

    status = engines.detect_tesseract(Settings(engines=EnginePaths(tesseract=str(exe))))
    assert status.available
    assert status.version == "5.4.0.20240606"
    assert status.problems == ["Eksik dil paketi: tur"]
    assert not status.ok
    assert status.to_dict()["ok"] is False


def test_tesseract_with_all_languages_is_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    exe = tmp_path / "tesseract.exe"
    exe.write_bytes(b"")
    outputs = {
        "--version": "tesseract 5.5.0\n",
        "--list-langs": "List of available languages (3):\neng\nosd\ntur\n",
    }
    monkeypatch.setattr(engines, "_run", lambda args: outputs[args[1]])
    status = engines.detect_tesseract(Settings(engines=EnginePaths(tesseract=str(exe))))
    assert status.ok


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sürüm kaynağı")
def test_file_version_reads_windows_exe():
    version = engines._file_version(Path(sys.executable))
    assert version is not None
    assert version.count(".") == 3


def test_python_libraries_are_installed():
    libs = engines.python_libraries()
    assert libs["pymupdf"]
    assert libs["pikepdf"]


def test_install_hints_match_the_platform(monkeypatch):
    """Linux'ta winget yok: ipucu dağıtımın paket adlarıyla."""
    from toolia.settings import Settings

    monkeypatch.setattr(engines, "on_windows", lambda: False)
    monkeypatch.setattr(engines, "_find_executable", lambda *a, **k: None)
    s = Settings()
    assert "apt install libreoffice" in engines.detect_libreoffice(s).install_hint
    assert "tesseract-ocr-tur" in engines.detect_tesseract(s).install_hint
    assert "apt install ghostscript" in engines.detect_ghostscript(s).install_hint
    assert "Chromium" in engines.detect_browser(s).install_hint
    monkeypatch.setattr(engines, "on_windows", lambda: True)
    assert "winget" in engines.detect_libreoffice(s).install_hint


def test_snap_detection_paths_and_wrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(engines, "on_windows", lambda: False)
    assert engines.snap_package_name("/snap/bin/chromium") == "chromium"
    assert engines.snap_package_name("/snap/bin/libreoffice.soffice") == "libreoffice"
    assert engines.snap_package_name("/snap/libreoffice/300/program/soffice.bin") == "libreoffice"
    assert engines.snap_package_name("/var/lib/snapd/snap/bin/chromium") == "chromium"
    assert engines.snap_package_name("/usr/bin/google-chrome") is None

    wrapper = tmp_path / "chromium-browser"
    wrapper.write_text("#!/bin/sh\nexec /snap/bin/chromium \"$@\"\n", encoding="utf-8")
    assert engines.snap_package_name(wrapper) == "chromium"
    assert engines.is_snap_executable(wrapper) is True

    normal = tmp_path / "chrome"
    normal.write_bytes(b"\x7fELF" + b"\x00" * 64)
    assert engines.snap_package_name(normal) is None


def test_libreoffice_linux_version_reads_versionrc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    prog = tmp_path / "libreoffice" / "program"
    prog.mkdir(parents=True)
    soffice = prog / "soffice"
    soffice.write_text("", encoding="utf-8")
    (prog / "versionrc").write_text(
        "[Version]\nOOOPackageVersion=24.8.4.2\nProductKey=LibreOffice 24.8\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(engines, "on_windows", lambda: False)
    monkeypatch.setattr(engines, "_run", lambda args: pytest.fail("versionrc varken çalışmamalı"))
    st = engines.detect_libreoffice(Settings(engines=EnginePaths(libreoffice=str(soffice))))
    assert st.available and st.version == "24.8.4.2"


def test_tesseract_missing_language_linux_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    exe = tmp_path / "tesseract"
    exe.write_bytes(b"")
    outputs = {
        "--version": "tesseract 5.3.4\n",
        "--list-langs": "List of available languages:\neng\nosd\n",
    }
    monkeypatch.setattr(engines, "on_windows", lambda: False)
    monkeypatch.setattr(engines, "_run", lambda args: outputs[args[1]])
    st = engines.detect_tesseract(Settings(engines=EnginePaths(tesseract=str(exe))))
    assert st.available and not st.ok
    assert st.install_hint == "sudo apt install tesseract-ocr-tur"


def test_office_installed_fonts_fontconfig(monkeypatch: pytest.MonkeyPatch):
    import subprocess

    from toolia.convert import office

    monkeypatch.setattr(office, "_installed_cache", None)
    monkeypatch.setattr(engines, "on_windows", lambda: False)
    monkeypatch.setattr(engines, "find_on_path", lambda name: Path("/usr/bin/fc-list"))
    monkeypatch.setattr(
        office.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 0, "Noto Sans,Noto Sans Regular\nLiberation Serif\nDejaVu Sans Mono\n", ""
        ),
    )
    fams = office.installed_fonts()
    assert fams is not None
    assert {"notosans", "liberationserif", "dejavusansmono"} <= fams
    monkeypatch.setattr(office, "_installed_cache", None)


def test_linux_font_search_finds_subdir_ttf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from toolia.core import fonts

    sub = tmp_path / "truetype" / "liberation"
    sub.mkdir(parents=True)
    ttf = sub / "LiberationSans-Regular.ttf"
    ttf.write_bytes(b"fake")
    monkeypatch.setattr(engines, "on_windows", lambda: False)
    monkeypatch.setattr(fonts, "_linux_index", None)
    monkeypatch.setattr(fonts, "_search_dirs", lambda: [tmp_path / "empty", tmp_path])
    assert fonts.font_path("liberation-sans") == ttf
    monkeypatch.setattr(fonts, "_linux_index", None)
