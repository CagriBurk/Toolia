# Linux planı

Durum: 2026-11-21, Toolia 0.13.0 + `dil-destegi` dalı. Bu belge yeni bir oturumun başlangıç noktası.

## Bugün ne var

| Konu | Windows | Linux |
|---|---|---|
| Kurulum | Release'teki zip → `Kur.cmd` (gömülü imzalı Python, motorlar paketin içinde, `%LOCALAPPDATA%\Programs\Toolia`, kısayollar, Kaldır) | **Yok.** Yalnız kaynak koddan: `git clone` + `uv` + `apt install …` (docs/KULLANIM.md "Linux") |
| Python | Pakette (`paket/derle.py`) | Kullanıcının kurduğu `uv`/Python |
| Motorlar | Tesseract + Ghostscript pakette; LibreOffice winget ile tek tık | Hepsi `apt` ile elle; ipuçları `engines.py` `_hint()` içinde |
| Uygulama penceresi | `toolia uygulama`: Edge `--app`, tek örnek, Job Object ile öksüz süreç yok (`desktop.py`) | Tarayıcıda `toolia serve`; pencere kipi, tek örnek, ileti kutusu yok (`os.name != "nt"` dalları boş) |
| Kısayol / menü | Masaüstü, Başlat, Gönder menüsü (`kurulum.py`, `gonder_menu.py`) | Yok (`.desktop` dosyası yok) |
| Klasör seç / Klasörde göster | PowerShell / explorer (`native.py`) | Düğmeler gizli (`desktop: os.name == "nt"`) |
| Veri klasörü | `%LOCALAPPDATA%\Toolia` | `~/.local/share/Toolia` (`settings.py:30`) |
| Testler / CI | Var | Var: GitHub Actions ubuntu-latest bütün testleri koşuyor (PLAN.md Faz D3) |

Yani kod Linux'ta **çalışıyor ve CI'da test ediliyor**, eksik olan **paketleme, masaüstü bütünleşmesi ve gerçek kullanıcı ortamlarındaki farklar**.

## Bilinen / olası Linux sorunları (doğrulanmadı, ilk iş bunları yeniden üretmek)

Arkadaşların gördüğü hataların tam metni yok; aşağıdakiler koddan çıkan güçlü şüpheliler:

1. **Telefon modu, yanlış IP**: `lan.py:lan_ips()` tüm IPv4 arayüzlerini topluyor. Linux'ta Docker (`docker0` 172.17.x), libvirt (`virbr0` 192.168.122.x), VPN (`tun0`), Tailscale (100.x) da çıkar; QR kod telefonun erişemediği bir adresi gösterebilir. Çözüm: sanal arayüzleri ele, varsayılan rota arayüzünü kesin önce koy, ekranda seçilebilir liste.
2. **Telefon modu, güvenlik duvarı**: Ubuntu'da `ufw` açıksa port kapalı; telefon bağlanamaz, uygulama bunu söylemez. Çözüm: Ayarlar'da "telefon bağlanamıyorsa: `sudo ufw allow <port>/tcp`" ipucu; mümkünse bağlantı testi (telefon tarafı istek gelmediyse uyarı).
3. **Snap Chromium / snap LibreOffice**: Ubuntu'da `chromium` ve bazen `libreoffice` snap paketidir; snap sandbox'ı gizli klasörleri (`~/.local/share/Toolia`) ve `/tmp`'yi farklı görür → Markdown→PDF baskısı ve Office dönüştürme "dosya bulunamadı" ile düşebilir. Doğrula; çözüm: iş klasörünü snap'in okuyabildiği yere almak ya da snap tespit edip uyarmak / Chrome .deb önermek.
4. **Yeniden başlatma**: Telefon modu / port değişince sunucu kendini yeniden başlatıyor (`desktop.py _Server`, `/api/settings/restart`); Linux'ta `toolia serve` altında bu yol gerçek kullanımda denenmedi.
5. **Python sürümü**: kaynak koddan kurulumda dağıtımın Python'u eski olabilir (pyproject `requires-python`'a bak); `uv` bunu çözüyor ama arkadaşlar `uv` kurmakta zorlanabilir.
6. **Yazı tipleri**: `core/fonts.py` Windows klasörlerine bakıyor (`LOCALAPPDATA`); Linux'ta `~/.local/share/fonts`, `/usr/share/fonts` taranıyor mu kontrol et (Arial yok → Noto).
7. **Tesseract Türkçe dili**: `tesseract-ocr-tur` kurulmamışsa OCR Türkçe seçeneğinde düşer; motor durumu bunu "Hazır" gösterebilir. Dil paketini de denetle.

## Hedef: Windows'taki kadar kolay kurulum

Önerilen yol (Windows'taki modelin aynısı, yeni araç öğrenmeden):

**`Toolia-<sürüm>-linux-x86_64.tar.gz`** → aç → `./kur.sh` çift tık / terminalden.

- İçinde **gömülü Python**: python-build-standalone (Astral'ın `uv`'nin de kullandığı derleme; glibc 2.17+, dağıtımdan bağımsız) + `site-packages` (kilit dosyasındaki bağımlılıklar + toolia + derlenmiş arayüz). Windows'taki `python/` klasörünün karşılığı.
- `kur.sh`:
  - `~/.local/share/Toolia/uygulama/` (ya da `~/.local/opt/toolia`) altına kopyalar, yönetici izni istemez.
  - `~/.local/bin/toolia` başlatıcısı, `~/.local/share/applications/toolia.desktop` + simge (uygulama menüsünde görünür), isteğe bağlı masaüstü kısayolu.
  - Motorları denetler (`soffice`, `tesseract` + `tur` dili, `gs`, Chrome/Chromium/Edge); eksikse dağıtıma göre **tek komut** gösterir ve onaylarsa `sudo` ile çalıştırır (apt / dnf / pacman). Snap Chromium varsa uyarır.
  - `kaldir.sh`: Windows'taki gibi veriyi bırakır, istenirse siler.
- `toolia uygulama` Linux'ta da çalışsın: Chrome/Chromium/Edge `--app` penceresi + ayrı profil; tek örnek (`calisiyor.json` zaten platformdan bağımsız); öksüz süreç için `prctl(PR_SET_PDEATHSIG)` ya da süreç grubu; hata için `zenity`/`notify-send` varsa onunla, yoksa günlük.
- `paket/derle.py`'ye `--linux` hedefi; GitHub Actions'ta ubuntu işinde tar.gz üretip Release'e ekle.

Alternatifler (şimdilik değil): **AppImage** (tek dosya, ama motorlar yine sistemden; FUSE sorunu), **.deb** (apt bağımlılıkları otomatik çözer, en temiz deneyim ama yalnız Debian/Ubuntu ve depo/imza işi), **Flatpak** (sandbox, LibreOffice/Tesseract'ı paketlemek ağır). tar.gz + kur.sh oturursa ikinci adımda .deb düşünülebilir.

## Adımlar (oturum başına küçük parçalar)

1. **Yeniden üretme** (önce bu): Arkadaşlardan hata metni/ekran görüntüsü + dağıtım (`cat /etc/os-release`) + tarayıcı/LibreOffice snap mi (`snap list`). Elde Linux yoksa: WSL2 Ubuntu ya da sanal makine; telefon modu için gerçek ağ gerekir (WSL2 NAT'ı telefon testini bozar, sanal makinede köprü ağ).
2. **Telefon modu düzeltmeleri**: madde 1–2 (+ testleri `tests/test_lan*.py`).
3. **Snap / yazı tipi / Tesseract dili**: madde 3, 6, 7.
4. **`toolia uygulama` Linux'ta**: `desktop.py` Linux dalları.
5. **Paket**: `derle.py --linux`, `kur.sh`, `kaldir.sh`, `.desktop`, OKUBENI; CI'da üret.
6. **Belgeler**: README/KULLANIM Linux bölümü "kaynak koddan" yerine "tar.gz indir, kur.sh".
7. Sürüm: 0.14.0 (İngilizce) ile birlikte ya da ayrı 0.15.0.

## Kullanıcıya açık sorular

- Arkadaşların hangi dağıtımı kullanıyor (Ubuntu mu, sürümü)? Yalnız Ubuntu/Debian'ı hedeflersek iş yarıya iner.
- Gördükleri hataların metni / ekran görüntüsü var mı? Telefon modu "bağlanamıyor" mu, "QR açılıyor ama sayfa gelmiyor" mu?
- Elinde bir Linux makinesi var mı, yoksa WSL2 / sanal makineyle mi deneyeceğiz?
- Motorlar (LibreOffice, Tesseract, Ghostscript) pakete gömülsün mü, yoksa `kur.sh` apt ile mi kursun? (Öneri: apt; LibreOffice zaten gömülemeyecek kadar büyük.)
