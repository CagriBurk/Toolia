"""Masaüstü kurulumu ve kaldırma (Windows ve Linux).

- **Windows**: `Kur.cmd` / `Kaldir.cmd` → `%LOCALAPPDATA%\\Programs\\Toolia`, masaüstü ve Başlat
  kısayolu, Gönder menüsü ("PDF'e çevir", "JPG'ye çevir"), "Uygulamalar" kaldırma kaydı.
  Neden .exe değil: Windows Akıllı Uygulama Denetimi (PLAN.md tuzak #52). Kopyalama
  `shutil.copyfile` iledir (Zone.Identifier akışı taşınmaz).
- **Linux**: `kur.sh` / `kaldir.sh` → `~/.local/opt/toolia` (kullanıcı verisi
  `~/.local/share/Toolia` ayrı kalır), `~/.local/bin/toolia`,
  `~/.local/share/applications/toolia.desktop` + simge, eksik motorlar için dağıtıma göre
  (`apt`/`dnf`/`pacman`) tek komut.

Kullanıcı verisi kuruluma dokunulmadan kalır; kaldırırken silinip silinmeyeceği sorulur.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP_NAME = "Toolia"
OLD_APP_NAME = "PDF Atölyesi"  # 0.12.0'dan önceki görünen ad (eski kısayolları silmek için)
DIR_NAME = "Toolia"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Toolia"
MARKER = "toolia-kurulum.json"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
BREAKAWAY = 0x01000000


def default_target() -> Path:
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "Programs" / DIR_NAME
    return Path.home() / ".local" / "opt" / "toolia"


def package_root() -> Path:
    """Çalışan Python'un ait olduğu paket/kurulum kökü (`toolia-kurulum.json` taşıyan üst klasör).
    Windows'ta `python/python.exe` (2 düzey), Linux'ta `python/bin/python3` (3 düzey)."""
    exe = Path(sys.executable).resolve()
    for parent in exe.parents[:4]:
        if (parent / MARKER).is_file():
            return parent
    return exe.parent.parent


def spawn_detached(args: list[str], **kw) -> None:
    """Bağımsız süreç: bizim süreç (ve varsa iş nesnemiz) kapanınca kapanmasın. Üst süreç
    ayrılmaya izin vermeyen bir iş nesnesindeyse (bazı terminaller) bayraksız yeniden dener."""
    if os.name != "nt":
        kw.setdefault("stdin", subprocess.DEVNULL)
        kw.setdefault("stdout", subprocess.DEVNULL)
        kw.setdefault("stderr", subprocess.DEVNULL)
        subprocess.Popen(args, start_new_session=True, **kw)
        return
    try:
        subprocess.Popen(args, creationflags=DETACHED | BREAKAWAY | NO_WINDOW, **kw)
    except OSError:
        subprocess.Popen(args, creationflags=DETACHED | NO_WINDOW, **kw)


def _say(text: str = "") -> None:
    print(text, flush=True)


def _ask(question: str) -> bool:
    try:
        answer = input(f"{question} (E/H): ").strip().casefold()
    except EOFError:
        return False
    return answer in ("e", "evet", "y", "yes")


# --- Windows kısayolları (WScript.Shell) ------------------------------------------------------

def _powershell(script: str) -> None:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    # PowerShell 7'den devralınan PSModulePath Windows PowerShell'in modüllerini bozar.
    env = {k: v for k, v in os.environ.items() if k.upper() != "PSMODULEPATH"}
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                   check=True, creationflags=NO_WINDOW, capture_output=True, env=env)


def _ps_str(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def shortcut_paths() -> dict[str, Path]:
    import ctypes
    from ctypes import wintypes

    def known(csidl: int) -> Path:
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
        return Path(buf.value)

    # 0x10 masaüstü, 0x02 Başlat menüsü\Programlar, 0x09 Gönder (SendTo)
    desktop, start, sendto = known(0x10), known(0x02), known(0x09)
    return {"masaustu": desktop / f"{APP_NAME}.lnk",
            "baslat": start / f"{APP_NAME}.lnk",
            "gonder": sendto / "PDF'e çevir.lnk",
            "gonder_jpg": sendto / "JPG'ye çevir.lnk",
            # 0.12.0'a kadarki ad: güncellemede ve kaldırmada silinir (iki simge kalmasın).
            "eski_masaustu": desktop / f"{OLD_APP_NAME}.lnk",
            "eski_baslat": start / f"{OLD_APP_NAME}.lnk"}


# Gönder menüsü kısayolları: anahtar → (`toolia.gonder_menu` türü, açıklama). Kısayol doğrudan
# python.exe'yi çalıştırır, .cmd değil: Gezgin boşluksuz yolları tırnaklamaz ve cmd.exe dosya
# adındaki `&`'den sonrasını komut olarak çalıştırırdı (GUVENLIK_PLANI.md, adım 1).
SENDTO_COMMANDS = {
    "gonder": ("pdf", "Seçili dosyaları Toolia ile PDF'e çevirir"),
    "gonder_jpg": ("jpg", "Seçili resimleri JPG'ye çevirir"),
}


def sendto_arguments(kind: str) -> str:
    """Gönder kısayolunun argümanları; Gezgin seçili dosyaların yollarını sonuna ekler."""
    return f"-I -m toolia.gonder_menu {kind}"


def icon_path(target: Path) -> Path:
    """Paketteki simge. Adı sürümü taşır (`toolia-0.12.2.ico`): Windows simgeleri dosya yoluna
    göre önbelleğe alır; yol aynı kalınca güncellemeden sonra masaüstünde eski simge görünürdü
    (0.12.1). 0.12.2'den eski paketlerde `toolia.ico`."""
    found = sorted((target / "simgeler").glob("toolia-*.ico"))
    return found[-1] if found else target / "simgeler" / "toolia.ico"


def refresh_icon_cache() -> None:
    """Windows'un simge önbelleğini yeniler (kısayollar yeni simgeyi hemen göstersin). Olmazsa
    sorun değil: sürüm adlı simge yolu zaten yeni."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["ie4uinit.exe", "-show"], timeout=30, creationflags=NO_WINDOW,
                       capture_output=True)


def create_shortcuts(target: Path) -> None:
    """Her kurulumda (güncelleme dahil) baştan yazılır: eski sürümün üzerine kurulunca yeni
    eklenen kısayollar da oluşur, eski addaki kısayollar silinir."""
    pyw = target / "python" / "pythonw.exe"
    py = target / "python" / "python.exe"  # Gönder: konsollu, ilerleme ve hata görünsün
    icon = icon_path(target)
    links = shortcut_paths()
    for key, path in links.items():
        if key.startswith("eski_"):
            path.unlink(missing_ok=True)
    lines = ["$s = New-Object -ComObject WScript.Shell"]
    for key in ("masaustu", "baslat"):
        lines += [f"$l = $s.CreateShortcut({_ps_str(links[key])})",
                  f"$l.TargetPath = {_ps_str(pyw)}",
                  "$l.Arguments = '-I -m toolia uygulama'",
                  f"$l.WorkingDirectory = {_ps_str(target)}",
                  f"$l.IconLocation = {_ps_str(str(icon) + ',0')}",
                  "$l.Description = 'Toolia: çevrimdışı PDF ve dosya araçları'",
                  "$l.Save()"]
    for key, (kind, description) in SENDTO_COMMANDS.items():
        lines += [f"$l = $s.CreateShortcut({_ps_str(links[key])})",
                  f"$l.TargetPath = {_ps_str(py)}",
                  f"$l.Arguments = {_ps_str(sendto_arguments(kind))}",
                  f"$l.WorkingDirectory = {_ps_str(target)}",
                  f"$l.IconLocation = {_ps_str(str(icon) + ',0')}",
                  "$l.WindowStyle = 7",
                  f"$l.Description = {_ps_str(description)}",
                  "$l.Save()"]
    _powershell("\n".join(lines))
    refresh_icon_cache()


def remove_shortcuts() -> None:
    for path in shortcut_paths().values():
        path.unlink(missing_ok=True)


# --- Linux kısayolları ve motor denetimi ------------------------------------------------------

def _linux_desktop_dir(home: Path) -> Path | None:
    from toolia import engines

    if xdg := engines.find_on_path("xdg-user-dir"):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            r = subprocess.run([str(xdg), "DESKTOP"], capture_output=True, text=True, timeout=5)
            p = Path(r.stdout.strip())
            if r.returncode == 0 and p.is_dir() and p.resolve() != home.resolve():
                return p
    for name in ("Desktop", "Masaüstü"):
        cand = home / name
        if cand.is_dir():
            return cand
    return None


def linux_shortcut_paths(home: Path | None = None) -> dict[str, Path]:
    base = Path(home) if home is not None else Path.home()
    paths = {
        "bin": base / ".local" / "bin" / "toolia",
        "desktop_entry": base / ".local" / "share" / "applications" / "toolia.desktop",
        "icon": base / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "toolia.png",
    }
    if desk := _linux_desktop_dir(base):
        paths["masaustu"] = desk / "Toolia.desktop"
    return paths


def _desktop_exec_quote(arg: str) -> str:
    """Freedesktop Desktop Entry Exec= alanı için güvenli kaçış."""
    if not any(ch in arg for ch in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    return f'"{escaped}"'


def linux_desktop_entry(target: Path, icon: str = "toolia") -> str:
    py = _desktop_exec_quote(str(target / "python" / "bin" / "python3"))
    return (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "GenericName=PDF Toolkit\n"
        "GenericName[tr]=PDF Araç Seti\n"
        "Comment=Offline PDF and document toolkit\n"
        "Comment[tr]=Çevrimdışı PDF ve dosya araçları\n"
        f"Exec={py} -I -m toolia uygulama\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Office;Utility;\n"
        "StartupNotify=true\n"
        "StartupWMClass=Toolia\n"
    )


def linux_bin_launcher(target: Path) -> str:
    py = shlex.quote(str(target / "python" / "bin" / "python3"))
    return f'#!/bin/sh\nexec {py} -I -m toolia "$@"\n'


def create_linux_shortcuts(target: Path, *, home: Path | None = None,
                           desktop_shortcut: bool = False) -> None:
    from toolia import engines

    links = linux_shortcut_paths(home)
    links["bin"].parent.mkdir(parents=True, exist_ok=True)
    links["bin"].write_text(linux_bin_launcher(target), encoding="utf-8", newline="\n")
    links["bin"].chmod(0o755)

    icon_value = "toolia"
    src_icon = target / "simgeler" / "toolia-256.png"
    if src_icon.is_file():
        links["icon"].parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_icon, links["icon"])
    else:
        icon_value = str(src_icon)

    entry_text = linux_desktop_entry(target, icon=icon_value)
    links["desktop_entry"].parent.mkdir(parents=True, exist_ok=True)
    links["desktop_entry"].write_text(entry_text, encoding="utf-8", newline="\n")
    links["desktop_entry"].chmod(0o644)

    if desktop_shortcut and "masaustu" in links:
        links["masaustu"].write_text(entry_text, encoding="utf-8", newline="\n")
        links["masaustu"].chmod(0o755)
        if gio := engines.find_on_path("gio"):
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run([str(gio), "set", str(links["masaustu"]),
                                "metadata::trusted", "true"],
                               capture_output=True, timeout=5)

    if upd := engines.find_on_path("update-desktop-database"):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run([str(upd), str(links["desktop_entry"].parent)],
                           capture_output=True, timeout=10)
    if gtk_ic := engines.find_on_path("gtk-update-icon-cache"):
        hicolor = links["icon"].parents[2]
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run([str(gtk_ic), "-q", "-t", "-f", str(hicolor)],
                           capture_output=True, timeout=10)


def remove_linux_shortcuts(*, home: Path | None = None) -> None:
    for path in linux_shortcut_paths(home).values():
        path.unlink(missing_ok=True)


def detect_linux_pkg_manager(os_release: str | None = None) -> str | None:
    """`/etc/os-release` ya da PATH üzerinden paket yöneticisini (`apt`/`dnf`/`pacman`) bulur."""
    text = os_release
    if text is None:
        p = Path("/etc/os-release")
        text = p.read_text(encoding="utf-8", errors="ignore") if p.is_file() else ""
    low = text.lower()
    if any(k in low for k in ("ubuntu", "debian", "linuxmint", "pop", "elementary", "kali")):
        return "apt"
    if any(k in low for k in ("fedora", "rhel", "centos", "rocky", "almalinux")):
        return "dnf"
    if any(k in low for k in ("arch", "manjaro", "endeavouros", "cachyos")):
        return "pacman"
    from toolia import engines

    for mgr, exe in (("apt", "apt-get"), ("dnf", "dnf"), ("pacman", "pacman")):
        if engines.find_on_path(exe):
            return mgr
    return None


_LINUX_ENGINE_PKGS: dict[str, dict[str, list[str]]] = {
    "apt": {
        "libreoffice": ["libreoffice-writer", "libreoffice-calc", "libreoffice-impress"],
        "tesseract": ["tesseract-ocr", "tesseract-ocr-tur", "tesseract-ocr-eng"],
        "ghostscript": ["ghostscript"],
        "browser": ["chromium"],
    },
    "dnf": {
        "libreoffice": ["libreoffice-writer", "libreoffice-calc", "libreoffice-impress"],
        "tesseract": ["tesseract", "tesseract-langpack-tur", "tesseract-langpack-eng"],
        "ghostscript": ["ghostscript"],
        "browser": ["chromium"],
    },
    "pacman": {
        "libreoffice": ["libreoffice-fresh"],
        "tesseract": ["tesseract", "tesseract-data-tur", "tesseract-data-eng"],
        "ghostscript": ["ghostscript"],
        "browser": ["chromium"],
    },
}


def linux_missing_engine_command(statuses: list, pkg_manager: str | None) -> list[str] | None:
    """Eksik motorlar için tek paket yöneticisi komutu (`['sudo', ...]`). Eksik yoksa None."""
    if pkg_manager not in _LINUX_ENGINE_PKGS:
        return None
    table = _LINUX_ENGINE_PKGS[pkg_manager]
    pkgs: list[str] = []
    for st in statuses:
        if st.ok:
            continue
        if st.key == "tesseract" and st.available:
            # Yalnızca eksik dil paketleri.
            if pkg_manager == "apt":
                pkgs.extend(["tesseract-ocr-tur", "tesseract-ocr-eng"])
            elif pkg_manager == "dnf":
                pkgs.extend(["tesseract-langpack-tur", "tesseract-langpack-eng"])
            elif pkg_manager == "pacman":
                pkgs.extend(["tesseract-data-tur", "tesseract-data-eng"])
        elif st.key in table:
            pkgs.extend(table[st.key])
    pkgs = list(dict.fromkeys(pkgs))
    if not pkgs:
        return None
    if pkg_manager == "apt":
        return ["sudo", "apt-get", "install", "-y", *pkgs]
    if pkg_manager == "dnf":
        return ["sudo", "dnf", "install", "-y", *pkgs]
    return ["sudo", "pacman", "-S", "--needed", *pkgs]


def _check_linux_engines() -> None:
    from toolia import engines
    from toolia.settings import Settings

    statuses = engines.detect_all(Settings())
    _say("\nMotor durumu:")
    for st in statuses:
        mark = "[OK]" if st.ok else ("[!!]" if st.available else "[--]")
        _say(f"  {mark} {st.name:<16} {st.version or '-'}")
        for note in st.problems + st.warnings:
            _say(f"       -> {note}")
    mgr = detect_linux_pkg_manager()
    cmd = linux_missing_engine_command(statuses, mgr)
    if not cmd:
        return
    pretty = " ".join(cmd)
    _say(f"\nEksik motorları kurmak için tek komut:\n  {pretty}")
    if os.environ.get("TOOLIA_KURULUM_MOTOR_SORMA") == "0":
        return
    if _ask("Bu komutu şimdi sudo ile çalıştırayım mı?"):
        if mgr == "apt":
            subprocess.run(["sudo", "apt-get", "update"], check=False)
        subprocess.run(cmd, check=False)


# --- Windows kaldırma kaydı -------------------------------------------------------------------

def register_uninstall(target: Path, version: str) -> None:
    import winreg

    size_kb = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) // 1024
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        values = {
            "DisplayName": APP_NAME,
            "DisplayVersion": version,
            "Publisher": "Toolia",
            "InstallLocation": str(target),
            "DisplayIcon": str(icon_path(target)),
            "UninstallString": f'"{target / "Kaldir.cmd"}"',
            "URLInfoAbout": "https://github.com/CagriBurk/Toolia",
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name, value in {"NoModify": 1, "NoRepair": 1, "EstimatedSize": size_kb}.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)


def unregister_uninstall(key: str = UNINSTALL_KEY) -> None:
    import winreg

    with contextlib.suppress(FileNotFoundError):
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)


# --- 0.12.0 öncesi kurulum (PDF Atölyesi) ----------------------------------------------------

LEGACY_DIR_NAME = "PdfAtolyesi"
LEGACY_MARKER = "pdfatolye-kurulum.json"
LEGACY_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PdfAtolyesi"


def legacy_install(target: Path) -> Path | None:
    """Yeni kurulumun yanındaki eski "PDF Atölyesi" kurulumu. Yalnız kendi işaret dosyasını
    taşıyan klasör sayılır: başka bir klasör asla silinmez."""
    old = target.parent / LEGACY_DIR_NAME
    return old if (old / LEGACY_MARKER).is_file() else None


def remove_legacy_install(old: Path) -> None:
    """Eski kurulum klasörünü ve "Uygulamalar" kaydını kaldırır. Kullanıcı verisine
    (veri klasörü) dokunmaz; o, uygulama ilk açıldığında yeni ada taşınır."""
    shutil.rmtree(old, ignore_errors=True)
    if old.exists():
        _say(f"Eski kurulum klasörü tamamen silinemedi, elle silebilirsin: {old}")
    unregister_uninstall(LEGACY_UNINSTALL_KEY)


# --- çalışan uygulama -------------------------------------------------------------------------

def _running_app(target: Path) -> bool:
    """Kurulu klasörden çalışan bir uygulama var mı (dosyalar kilitli olur)?"""
    import psutil

    for p in psutil.process_iter(["exe"]):
        try:
            exe = p.info["exe"]
            inside = exe and Path(exe).resolve().is_relative_to(target.resolve())
            if inside and p.pid != os.getpid():
                return True
        except (psutil.Error, OSError, ValueError):
            continue
    return False


# --- kur / kaldır -----------------------------------------------------------------------------

def install(source: Path, target: Path, *, launch: bool = True, shortcuts: bool = True,
            check_engines: bool = True) -> int:
    info = json.loads((source / MARKER).read_text(encoding="utf-8"))
    version = info.get("version", "?")
    _say(f"{APP_NAME} {version} kuruluyor → {target}")
    old = legacy_install(target) if os.name == "nt" else None
    if old is not None and _running_app(old):
        _say("Eski sürüm (PDF Atölyesi) açık. Pencereyi kapatıp kurulumu yeniden çalıştır.")
        return 1
    if source.resolve() == target.resolve():
        _say("Paket zaten kurulu klasörde; yalnızca kısayollar yenileniyor.")
    else:
        if target.exists():
            if _running_app(target):
                _say("Uygulama açık. Pencereyi kapatıp kurulumu yeniden çalıştır.")
                return 1
            _say("Önceki sürüm kaldırılıyor (belgelerin ve ayarların korunur)...")
            shutil.rmtree(target)
        _say("Dosyalar kopyalanıyor (bir iki dakika sürebilir)...")
        target.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            # Zone.Identifier (MOTW) akışı kopyaya taşınmasın.
            shutil.copytree(source, target, copy_function=shutil.copyfile)
        else:
            # Linux'ta yürütme izinleri (+x) ve Python iç sembolik bağları korunmalı.
            shutil.copytree(source, target, symlinks=True)
    marker = info | {"installed": time.time(), "source": str(source)}
    (target / MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    if shortcuts:
        _say("Kısayollar oluşturuluyor...")
        if os.name == "nt":
            create_shortcuts(target)
            register_uninstall(target, version)
            if old is not None:
                _say("Eski sürüm (PDF Atölyesi) kaldırılıyor (belgelerin korunur)...")
                remove_legacy_install(old)
        else:
            create_linux_shortcuts(target)
    if os.name == "nt":
        _say("Kurulum tamam. Masaüstündeki \"Toolia\" simgesiyle açabilirsin.")
        if launch:
            spawn_detached([str(target / "python" / "pythonw.exe"), "-I", "-m", "toolia",
                            "uygulama"], cwd=target)
    else:
        if check_engines:
            _check_linux_engines()
        _say("\nKurulum tamam. Uygulama menüsünden \"Toolia\" ile ya da terminalden "
             "`~/.local/bin/toolia uygulama` komutuyla açabilirsin.")
        if launch and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            spawn_detached([str(target / "python" / "bin" / "python3"), "-I", "-m", "toolia",
                            "uygulama"], cwd=target)
    return 0


def uninstall(target: Path, *, assume_yes: bool = False, remove_data: bool | None = None,
              data_dir: Path | None = None) -> int:
    """`data_dir` verilmezse ayarlardaki veri klasörü (kullanıcıya sorulur)."""
    from toolia.settings import load_settings

    if not assume_yes and not _ask(f"{APP_NAME} kaldırılsın mı?"):
        _say("Vazgeçildi.")
        return 1
    if _running_app(target):
        _say("Uygulama açık. Pencereyi kapatıp yeniden dene.")
        return 1
    data_dir = Path(data_dir) if data_dir is not None else load_settings().data_dir
    if remove_data is None:
        remove_data = _ask(f"Belgelerin, imzaların ve ayarların da silinsin mi? ({data_dir})")
    if os.name == "nt":
        remove_shortcuts()
        unregister_uninstall()
    else:
        remove_linux_shortcuts()
    if remove_data:
        shutil.rmtree(data_dir, ignore_errors=True)
        _say("Veriler silindi.")
    else:
        _say(f"Veriler korundu: {data_dir}")
    # Çalışan Python kurulum klasöründe: klasörü, bu süreç çıktıktan sonra ayrı bir kabuk siler.
    if os.name == "nt":
        script = Path(tempfile.gettempdir()) / "toolia-kaldir.cmd"
        script.write_text(
            "@echo off\r\n"
            f"timeout /t 2 /nobreak >nul\r\nrmdir /s /q \"{target}\"\r\n"
            "del \"%~f0\"\r\n", encoding="mbcs")
        spawn_detached(["cmd", "/c", str(script)])
    else:
        spawn_detached(["sh", "-c", 'sleep 1; rm -rf -- "$1"', "toolia-kaldir", str(target)])
    _say(f"{APP_NAME} kaldırıldı.")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("kur", "kaldir"):
        _say("Kullanım: python -m toolia.kurulum kur [hedef] | kaldir")
        return 2
    try:
        if argv[0] == "kur":
            target = Path(argv[1]) if len(argv) > 1 else default_target()
            return install(package_root(), target)
        return uninstall(package_root())
    except Exception as e:  # kullanıcı konsolda okusun; yığın izi değil
        _say(f"Hata: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    # Çıktı bir boruya/dosyaya giderse Windows kod sayfası (cp1252/cp857) "→", "ğ" yazamaz.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    code = main(sys.argv[1:])
    if os.environ.get("TOOLIA_KURULUM_BEKLEME") != "0":
        with contextlib.suppress(EOFError):
            input("\nKapatmak için Enter'a bas...")
    sys.exit(code)
