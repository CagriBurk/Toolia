"""Bu bilgisayarın masaüstüyle tümleşme: klasör seçme penceresi, Gezgin'de gösterme.

Arayüz tarayıcıda çalıştığı için dosya yolu göremez/seçemez; bu işler sunucuda, yalnızca sunucunun
çalıştığı bilgisayardan gelen isteklerle (telefon modundaki cihazlar değil) yapılır. Her şey
Windows'un kendi imzalı araçlarıyla (powershell.exe, explorer.exe): Akıllı Uygulama Denetimi
engellemez, yeni bir .exe gerekmez.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
from pathlib import Path

from toolia import engines
from toolia.errors import TooliaError

log = logging.getLogger("toolia.native")
PICK_TIMEOUT_S = 600  # kullanıcı pencereyi açık bırakabilir; sonsuza dek beklenmez
REVEAL_DIR = "Dışa aktarılanlar"

# Seçim penceresi her zaman en üstte açılsın: uygulama penceresinin arkasında kalmasın.
_PICK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = '__ACIKLAMA__'
$d.ShowNewFolderButton = $false
$start = '__BASLANGIC__'
if ($start -and (Test-Path -LiteralPath $start -PathType Container)) { $d.SelectedPath = $start }
if ($d.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { $d.SelectedPath }
"""


class NativeUnavailableError(TooliaError):
    def __init__(self) -> None:
        super().__init__(
            "Bu özellik yalnızca uygulamanın çalıştığı masaüstü bilgisayarda var "
            "(Linux'ta zenity/kdialog veya xdg-open gerekir)."
        )


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def is_available() -> bool:
    """Klasör seçme veya dosya yöneticisinde gösterme bu ortamda destekleniyor mu?"""
    if engines.on_windows():
        return True
    if not _has_display():
        return False
    return any(engines.find_on_path(t) for t in ("zenity", "kdialog", "dbus-send", "xdg-open"))


def _ps_literal(text: str) -> str:
    return text.replace("'", "''")


def _clean_env() -> dict:
    # pwsh içinden çağrılan powershell.exe devraldığı PSModulePath ile modül yükleyemez (#57).
    env = dict(os.environ)
    env.pop("PSModulePath", None)
    return env


def _pick_folder_linux(initial: str | None, description: str) -> str | None:
    if not _has_display():
        raise NativeUnavailableError()
    start = initial if initial and Path(initial).is_dir() else None
    if zenity := engines.find_on_path("zenity"):
        cmd = [str(zenity), "--file-selection", "--directory", f"--title={description}"]
        if start:
            cmd.append(f"--filename={start.rstrip('/')}/")
    elif kdialog := engines.find_on_path("kdialog"):
        cmd = [str(kdialog), "--getexistingdirectory", start or str(Path.home()),
               "--title", description]
    else:
        raise NativeUnavailableError()
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=PICK_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return None
    if out.returncode == 1:  # kullanıcı vazgeçti
        return None
    if out.returncode != 0:
        log.warning("Klasör seçme penceresi açılamadı: %s",
                    out.stderr.decode("utf-8", "replace")[-500:])
        raise TooliaError("Klasör seçme penceresi açılamadı; yolu elle yaz.")
    return out.stdout.decode("utf-8", "replace").strip() or None


def pick_folder(initial: str | None = None, description: str = "Klasör seç") -> str | None:
    """Masaüstünün klasör seçme penceresini açar; seçilen yol ya da vazgeçilirse None."""
    if not engines.on_windows():
        return _pick_folder_linux(initial, description)
    script = (_PICK_SCRIPT.replace("__ACIKLAMA__", _ps_literal(description))
              .replace("__BASLANGIC__", _ps_literal(initial or "")))
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy",
             "Bypass", "-EncodedCommand", encoded],
            capture_output=True, timeout=PICK_TIMEOUT_S, env=_clean_env(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    except subprocess.TimeoutExpired:
        return None
    if out.returncode != 0:
        log.warning("Klasör seçme penceresi açılamadı: %s",
                    out.stderr.decode("utf-8", "replace")[-500:])
        raise TooliaError("Klasör seçme penceresi açılamadı; yolu elle yaz.")
    path = out.stdout.decode("utf-8-sig", "replace").strip()
    return path or None


def _reveal_linux(path: Path) -> None:
    if not _has_display():
        raise NativeUnavailableError()
    # Freedesktop FileManager1: dosyayı dosya yöneticisinde seçili gösterir (GNOME/KDE/XFCE).
    if dbus := engines.find_on_path("dbus-send"):
        try:
            r = subprocess.run(
                [str(dbus), "--session", "--dest=org.freedesktop.FileManager1",
                 "--type=method_call", "/org/freedesktop/FileManager1",
                 "org.freedesktop.FileManager1.ShowItems",
                 f"array:string:{path.resolve().as_uri()}", "string:"],
                capture_output=True, timeout=5, check=False,
            )
            if r.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
    if xdg := engines.find_on_path("xdg-open"):
        subprocess.Popen([str(xdg), str(path.parent)], start_new_session=True)
        return
    raise NativeUnavailableError()


def reveal(path: Path) -> None:
    """Dosyayı dosya yöneticisinde seçili gösterir."""
    if not engines.on_windows():
        _reveal_linux(path)
        return
    # explorer.exe hemen döner (işi çalışan Gezgin'e devreder); çıkış kodu anlamsızdır.
    subprocess.Popen(reveal_command(path),
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def reveal_command(path: Path) -> str:
    """Gezgin'in komut satırı. Liste yerine dize: yolda boşluk varsa (`Dışa aktarılanlar` hep
    var) Python bağımsız değişkenin tamamını tırnağa alır, Gezgin `"/select,…"` biçimini
    tanımaz ve Belgeler'i açar. Tırnak yalnızca yolu sarmalı."""
    return f'explorer.exe /select,"{path}"'


def export_copy(store, data_dir: Path, file_id: str) -> Path:
    """Depodaki dosyanın güncel sürümünü kullanıcının gördüğü adıyla dışa aktarma klasörüne
    kopyalar (depodaki `v3.pdf` gibi iç dosyalar gösterilmez, kullanıcı onlara dokunamaz).
    Depodan silinmiş dosyaların kopyaları her çağrıda temizlenir."""
    meta = store.get(file_id)
    root = data_dir / REVEAL_DIR
    root.mkdir(parents=True, exist_ok=True)
    known = {m.id for m in store.list()}
    for d in root.iterdir():
        if d.is_dir() and d.name not in known:
            shutil.rmtree(d, ignore_errors=True)
    target_dir = root / file_id
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / meta.name
    shutil.copyfile(store.path(file_id), target)
    return target


def loopback_peer_is_same_user(ip: str, port: int) -> bool:
    """127.0.0.1'e bağlanan süreç bu Windows kullanıcısına mı ait?

    Sunucu loopback'te dinler; aynı bilgisayardaki BAŞKA bir Windows kullanıcısı (paylaşılan ya
    da uzak masaüstü bilgisayarı) da 127.0.0.1:8790'a bağlanıp oturum çerezini alabilirdi
    (GUVENLIK_PLANI.md, adım 8). Bağlantının istemci ucu tabloda aranır; sahibi bu kullanıcı
    değilse ya da okunamıyorsa (başka kullanıcının süreci: erişim reddedilir) False.
    Bağlantı tabloda yoksa (gerçek soket değil: testler) True. Windows dışında her zaman True.
    """
    if os.name != "nt":
        return True
    import psutil

    try:
        conns = psutil.net_connections(kind="tcp")
    except psutil.Error:
        return False
    owners = {c.pid for c in conns if c.laddr and c.laddr.ip == ip and c.laddr.port == port}
    if not owners:
        return True
    try:
        me = psutil.Process().username()
        return all(pid and psutil.Process(pid).username() == me for pid in owners)
    except psutil.Error:
        return False
