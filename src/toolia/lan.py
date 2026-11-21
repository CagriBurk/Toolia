"""Telefon / LAN modu yardımcıları: yerel ağ adresleri ve QR kod.

LAN modunda sunucu 0.0.0.0'a bağlanır. Oturum çerezi yalnızca bu bilgisayara (loopback) ya da
QR koddaki eşleştirme belirteciyle (`?t=...`) gelen cihaza verilir; belirteçsiz istek reddedilir.
"""

from __future__ import annotations

import io
import ipaddress
import socket

import psutil

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

# Konteyner, sanal makine köprüsü ve VPN tünelleri: telefon Wi-Fi'den bunlara ulaşamaz.
_VIRTUAL_PREFIXES = (
    "lo", "docker", "br-", "veth", "virbr", "lxc", "lxd", "podman",
    "cni", "flannel", "cali", "kube", "tun", "tap", "wg", "tailscale",
    "zt", "utun", "vmnet", "vboxnet", "vethernet", "wsl", "ham",
)
_VIRTUAL_KEYWORDS = (
    "virtual", "vmware", "vbox", "hyper-v", "wsl", "loopback", "docker",
    "tailscale", "zerotier", "wireguard", "vpn", "tap-windows", "teredo",
)
_PREFERRED_PREFIXES = ("wl", "wi-fi", "wifi", "en", "eth", "ethernet")


def is_virtual_interface(name: str) -> bool:
    """Konteyner, sanal makine veya VPN tünel arayüzü mü?"""
    low = name.strip().lower()
    return any(low.startswith(p) for p in _VIRTUAL_PREFIXES) or any(
        k in low for k in _VIRTUAL_KEYWORDS
    )


def _default_route_ip() -> str | None:
    """Varsayılan çıkış arayüzünün IPv4 adresi (UDP connect paket göndermez)."""
    for target in (("10.255.255.255", 1), ("8.8.8.8", 80)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(target)
                return s.getsockname()[0]
        except OSError:
            continue
    return None


def _is_lan_ipv4(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.version == 4 and addr.is_private and not addr.is_loopback and not addr.is_link_local


def _iface_rank(iface: str, ip: str, default_ip: str | None) -> tuple[int, int, str]:
    low = iface.strip().lower()
    is_default = 0 if ip == default_ip else 1
    preferred = 0 if any(low.startswith(p) for p in _PREFERRED_PREFIXES) else 1
    return (is_default, preferred, low)


def lan_ips() -> list[str]:
    """Bu bilgisayarın yerel ağdaki IPv4 adresleri; varsayılan fiziksel arayüz önce.

    Docker (`docker0`), libvirt (`virbr0`), WSL ve VPN (`tun0`, `wg0`) gibi sanal arayüzler ile
    kapalı arayüzler elenir; hiç fiziksel arayüz bulunamazsa özel IPv4'lere geri düşülür.
    """
    default_ip = _default_route_ip()
    try:
        stats = psutil.net_if_stats()
    except OSError:
        stats = {}

    physical: list[tuple[tuple[int, int, str], str]] = []
    fallback: list[tuple[tuple[int, int, str], str]] = []
    seen: set[str] = set()

    for iface, addrs in psutil.net_if_addrs().items():
        st = stats.get(iface)
        if st is not None and not st.isup:
            continue
        virtual = is_virtual_interface(iface)
        for a in addrs:
            if a.family != socket.AF_INET or not _is_lan_ipv4(a.address) or a.address in seen:
                continue
            seen.add(a.address)
            entry = (_iface_rank(iface, a.address, default_ip), a.address)
            (fallback if virtual else physical).append(entry)

    # Varsayılan rota adresi psutil listesinde görünmediyse (ör. kısıtlı ortam) ekle.
    if default_ip and _is_lan_ipv4(default_ip) and default_ip not in seen:
        physical.append(((0, 0, ""), default_ip))

    chosen = physical if physical else fallback
    chosen.sort(key=lambda item: item[0])
    return [ip for _, ip in chosen]


def qr_svg(text: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    return img.to_string(encoding="unicode")


def qr_text(text: str) -> str:
    """Terminale basılacak QR (blok karakterleriyle)."""
    import qrcode

    qr = qrcode.QRCode(border=1)
    qr.add_data(text)
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    return buf.getvalue()
