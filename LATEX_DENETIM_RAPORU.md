# Toolia — LaTeX → PDF Bağımsız Güvenlik ve Kod Denetim Raporu

- **Tarih:** 2026-11-28
- **İncelenen değişiklik:** `git diff c734b0f..a6161a8` (commit `03706af`, birleştirme `a6161a8`, 33 dosya, `+1861/−44`)
- **Denetim kapsamı:** Arka uç güvenliği, ZIP açma, alt süreç/argüman güvenliği, derleme döngüsü ve günlük çözümleme, eşzamanlılık/zaman aşımı, ön yüz (React/TS/i18n/a11y), CLI, CI/testler ve belgeler.
- **Doğrulama ortamı:** Windows, MiKTeX 25.12 (`pdflatex`, `xelatex`, `lualatex`, `biber`, `bibtex`, `makeindex`, `makeglossaries-lite`), Ghostscript 10.08.0; `ruff`, `eslint`, `tsc --noEmit`, `vitest` (85/85), `web/scripts/i18n-eksik.mjs`, `pytest` (166/166) ve izole geçici klasörlerde çalıştırılan doğrulama senaryoları.

---

## Özet Tablo

| Kimlik | Önem | Başlık | Durum |
|---|---|---|---|
| **K1** | Kritik | `makeglossaries-lite` üzerinden `-no-shell-escape` atlatması ve keyfi komut çalıştırma (RCE) | Doğrulandı (kaynak kod) |
| **K2** | Kritik | `biber.conf` ile proje klasörü dışına keyfi dosya yazma | Doğrulandı (çalıştırıldı) |
| **K3** | Kritik | `biber` uzak kaynak (remote datasource) ile diskteki dosyaların internete sızdırılması | Doğrulandı (çalıştırıldı) |
| **Y1** | Yüksek | `toolia motorlar` isteğe bağlı (`optional`) motoru eksik sayıyor → Linux CI kırılacak | Doğrulandı (kod) |
| **Y2** | Yüksek | ZIP açmada NTFS ADS (`:`), çoklu ZIP / oran bombası ve yakalanmayan hatalar | Doğrulandı (çalıştırıldı) |
| **Y3** | Yüksek | Eski/hazır `main.pdf` varsa ölümcül hatada başarılı sayılıp eski PDF döndürülüyor | Doğrulandı (çalıştırıldı) |
| **Y4** | Yüksek | Argüman enjeksiyonu: `-` ile başlayan adlar ve Ghostscript `%` biçim belirteçleri | Doğrulandı (çalıştırıldı) |
| **O1** | Orta | Zaman aşımı bütçesi ihlali (`_convert_eps` ve `_ensure_cm_super` `deadline` yok sayıyor) | Doğrulandı (kod) |
| **O2** | Orta | Kuyruk eşzamanlılık sınırı (`LIMITS`) yok ve `_CM_SUPER_CHECKED` yarış durumu | Doğrulandı (kod) |
| **O3** | Orta | `engines.find_on_path` erişilemeyen PATH klasöründe `PermissionError` ile çöküyor | Doğrulandı (çalıştırıldı) |
| **O4** | Orta | `find_main` Linux'ta `.TEX` uzantısını kaçırıyor ve aynı kök adlı alt dosyada ana dosyayı eliyor | Doğrulandı (kod + çalıştırıldı) |
| **O5** | Orta | `Home.tsx` yönlendirmesi `.csv` / `.txt` içeren LaTeX projelerini reddediyor | Doğrulandı (kod) |
| **O6** | Orta | `CommandPalette` LaTeX dosyalarını PDF sanıyor; `Jobs.tsx`'te `tex_to_pdf` ikonu eksik | Doğrulandı (kod) |
| **O7** | Orta | Telefon modunda arayüz deneyimi ve `workers.install_engine` ikinci katman eksikliği | Doğrulandı (kod) |
| **O8** | Orta | MiKTeX `--enable-installer` / `AutoInstall=1` çevrimdışı vaadiyle çelişiyor; `ag_cikisi.py` kapsamıyor | Doğrulandı (kod) |
| **D1** | Düşük | `pick_engine` ve `_code` yorum/paket algılama eksikleri | Doğrulandı (çalıştırıldı) |
| **D2** | Düşük | Günlük çözümleme kenar durumları (LuaLaTeX 79 karakter sarma, sınıf seçeneği `turkish`, vb.) | Doğrulandı (çalıştırıldı) |
| **D3** | Düşük | CLI `toolia latex` girdi uzantı kontrolü ve `-o` üst klasör oluşturma eksikliği | Doğrulandı (kod) |
| **D4** | Düşük | Özel sözlük türleri (`nomain` + `\newglossary`) çalışmıyor | Doğrulandı (kod) |
| **D5** | Düşük | `Latex.tsx` erişilebilirlik eksikleri (`role="alert"`, `aria-describedby`) | Doğrulandı (kod) |
| **D6** | Düşük | CI'da hiçbir gerçek TeX derleme testi çalışmıyor; eksik regresyon testleri | Doğrulandı (kod) |
| **D7** | Düşük | Belge tutarsızlıkları (`config.example.toml`, "süre sınırı yok" ifadesi) | Doğrulandı (kod) |
| **N1–N3** | Not | Temiz Windows winget kurulumu, XeLaTeX `xdvipdfmx` EPS, LuaLaTeX okuma yüzeyi | Şüphe / Bilgi |

---

## 1. Bulgular (Önem Sırasıyla)

### KRİTİK

#### K1. `makeglossaries-lite` üzerinden `-no-shell-escape` atlatması ve keyfi komut çalıştırma (RCE) — **Doğrulandı (kaynak kod)**
- **Dosya:Satır:** `src/toolia/convert/latex.py:709-712` (ve sistemdeki `makeglossaries-lite.lua:210-248, 404-491`)
- **Ne yanlış:** `compile_project` ilk geçişte `.glo` veya `.acn` dosyası görünce `makeglossaries-lite` betiğini çalıştırıyor. MiKTeX ve TeX Live ile gelen `makeglossaries-lite.lua`, `.aux` dosyasından **doğrudan `.tex` belgesinin yazabildiği** alanları okuyup kabuk kaçışı yapmadan Lua'nın `os.execute(cmd)` (`cmd.exe /c` / `/bin/sh -c`) fonksiyonuna iletiyor:
  - `\@glsmakeindexappname{...}` (`makeglossaries-lite.lua:440` → doğrudan `cmd` başına çalıştırılacak program olarak ekleniyor)
  - `\@istfilename{...}` (`makeglossaries-lite.lua:404` → `-s <styfile>`)
  - `\@gls@extramakeindexopts{...}` (`makeglossaries-lite.lua:451` → doğrudan `cmd .. " " .. makeindex_extra`)
  - `\@newglossary{...}{glg}{gls}{glo}` (`makeglossaries-lite.lua:460` → `-t`, `-o` ve girdi adı)
  - `\@xdylanguage{...}` / `\@gls@codepage{...}` (`makeglossaries-lite.lua:482-489` → `doxindy` komutu)
- **Nasıl tetiklenir:** Tek bir `.tex` dosyası bile `-no-shell-escape` açıkken standart TeX `\immediate\openout` ile çalışma klasöründe boş bir `\jobname.glo` oluşturup `\immediate\write\@auxout` ile `.aux` içine `\@glsmakeindexappname{...}` (veya `\@istfilename` / `\@gls@extramakeindexopts` / `\@newglossary` içine kabuk metakarakterleri) yazabilir. Toolia `.glo` dosyasını görünce `makeglossaries-lite` çalıştırır ve kabuk komutu yürütülür.
- **Etkisi:** `-no-shell-escape` koruması hem Windows'ta (MiKTeX) hem Linux'ta (TeX Live) tamamen aşılır; güvenilmeyen bir `.tex` veya `.zip` dosyası kullanıcının haklarıyla keyfi OS komutu çalıştırabilir.
- **Önerilen düzeltme:** `makeglossaries-lite` betiğini **hiç çağırma**. Python tarafında `.aux` dosyasından `\@newglossary{ad}{glg}{gls}{glo}` ve `\@istfilename{...}` kayıtlarını sıkı ad doğrulamasıyla (klasörsüz, `-` ile başlamayan, yalnız güvenli karakterler içeren) okuyup `makeindex`'i doğrudan argüman listesiyle (`subprocess.Popen`, kabuksuz) çağır. Bu değişiklik aynı zamanda D4'teki özel sözlük türlerini de destekler.

---

#### K2. `biber.conf` ile proje klasörü dışına keyfi dosya yazma — **Doğrulandı (çalıştırıldı)**
- **Dosya:Satır:** `src/toolia/convert/latex.py:671-675`
- **Ne yanlış:** `biber` komutu `--noconf` verilmeden `[stem]` ile çalıştırılıyor. `biber` varsayılan olarak çalışma klasöründeki (`cwd` = açılmış proje klasörü) `biber.conf` veya `.biber.conf` dosyasını otomatik okur.
- **Nasıl tetiklenir:** Proje `.zip`'i içine (ya da tek bir `.tex` içinden `\immediate\openout\f=biber.conf` ile) `<config><output_file>C:/.../hedef.txt</output_file></config>` içeren bir `biber.conf` konur. MiKTeX 25.12 `biber` ile izole geçici klasörde test edildi: proje klasörünün üst dizinine `escaped_by_biber.txt` (1501 bayt) **yazıldı** (`biber rc: 0`). `--noconf` eklendiğinde yazma engellendi (`exists: False`).
- **Etkisi:** "Belge proje klasörü dışına yazamıyor" güvenlik sınırını doğrudan kırar; güvenilmeyen bir `.tex`/`.zip` kullanıcının yazabildiği herhangi bir yoldaki dosyanın üzerine `.bbl` içeriği yazabilir.
- **Önerilen düzeltme:** `biber` çağrısına mutlaka `--noconf` ve `--output-directory=.` (veya `--`) ekle. Proje klasöründe `biber.conf` / `.biber.conf` varsa `latexmkrc`'deki gibi okunmadığına dair uyarı göster.

---

#### K3. `biber` uzak kaynak (remote datasource) ile diskteki dosyaların internete sızdırılması — **Doğrulandı (çalıştırıldı)**
- **Dosya:Satır:** `src/toolia/convert/latex.py:671-675`
- **Ne yanlış:** `biblatex` / `biber`, `.bcf` dosyasındaki uzak HTTP/HTTPS kaynaklarını (`\addbibresource[location=remote]{http://...}`) indirir. `--noconf` ve `-no-shell-escape` açıkken dahi `127.0.0.1` üzerindeki yerel test dinleyicisine `GET /leak?secret=from_tex` isteği ulaştığı doğrulandı (`biber rc: 0`).
- **Nasıl tetiklenir:** TeX'in (`\openin`) veya LuaLaTeX'in (`io.open`, `lfs.dir`, `os.getenv` — hepsi `-no-shell-escape` altında açık olduğu doğrulandı) diskten okuduğu herhangi bir veri `\addbibresource[location=remote]{https://...}` içine (veya doğrudan `.bcf`'deki `<bcf:datasource>` öğesine) yazılır. Toolia `.bcf` görünce `biber` çalıştırır ve veri ağ üzerinden dışarı gider. Ayrıca UNC yolu (`\\sunucu\paylasim\a.bib`) verilmesi Windows'ta SMB/NTLM özeti sızıntısına yol açabilir (bkz. `GUVENLIK_PLANI.md` Adım 3).
- **Etkisi:** "Dosyalar internete çıkmaz" vaadini ve "okuma riski yalnızca yerel PDF ile sınırlıdır" varsayımını bozar; sessiz veri sızdırmaya (exfiltration) olanak verir.
- **Önerilen düzeltme:** `biber` çalışmadan önce `main.bcf` XML'ini Python'da ayrıştır; `http://`, `https://`, `ftp://`, `//`, `\\`, sürücü harfi veya `..` içeren herhangi bir `<bcf:datasource>` varsa `biber`'ı çalıştırmadan reddet (veya uyarıyla atla). Derinlemesine savunma olarak `biber` ortamına ölü proxy (`HTTP_PROXY`/`HTTPS_PROXY=http://127.0.0.1:1`, `NO_PROXY=""`) ver.

---

### YÜKSEK

#### Y1. `toolia motorlar` komutu `optional` motoru eksik sayıyor → Linux CI kırılacak — **Doğrulandı (kod)**
- **Dosya:Satır:** `src/toolia/cli.py:236-247` ve `.github/workflows/ci.yml:86-100`
- **Ne yanlış:** `engines.detect_all(settings)` artık `detect_latex` (`optional=True`) döndürüyor. `cli.py:243` ise `if not e.available: any_missing = True` diyerek `e.optional` alanını yok sayıyor ve çıkış kodunu `1` yapıyor.
- **Nasıl tetiklenir:** LaTeX kurulu olmayan herhangi bir makinede — özellikle `.github/workflows/ci.yml:100` adımındaki `linux` CI işinde — `uv run python -m toolia motorlar` çıkış kodu `1` ile biter.
- **Etkisi:** Commit'ler push edildiğinde GitHub Actions `linux` CI işi doğrudan başarısız olur.
- **Önerilen düzeltme:** `cli.py:243` satırını `if not e.available and not e.optional: any_missing = True` yap; isteğe bağlı motorun çıktıda `(isteğe bağlı)` olarak belirtilmesi okunurluğu da artırır.

---

#### Y2. ZIP açmada NTFS ADS (`:`), çoklu ZIP / oran bombası ve yakalanmayan hatalar — **Doğrulandı (çalıştırıldı)**
- **Dosya:Satır:** `src/toolia/convert/latex.py:57-90` ve `src/toolia/jobs/workers.py:605-616`
- **Ne yanlış:**
  1. **NTFS ADS (`:`):** Satır 75 yalnız `":" in parts[0]` denetliyor. `sub/a.tex:hidden` girişi kontrolü geçip Windows'ta NTFS Alternate Data Stream olarak **gerçekten yazıldı** (`ADS_WRITTEN: b'secret_ads'`).
  2. **Çoklu ZIP + sıkıştırma oranı eksikliği (DoS):** `TexToPdfRequest.files` en çok 500 dosya kimliği alıyor (tekrarlanan kimlikler engellenmiyor) ve `workers.py:607` her `.zip` için `extract_project`'i ayrı 1 GB / 5000 dosya kotasıyla çağırıyor. `office.py`'deki `MAX_RATIO = 100` sınırı burada yok: 1 MB'lık (1 GB açılan) tek bir zip 500 kez listelenerek **500 GB disk yazımı** yaptırılabilir. (Not: Python 3.11 `ZipExtFile._read1` DEFLATE için `self._left = info.file_size` uygular; fakat `ZIP_BZIP2`/`ZIP_LZMA` yöntemlerinde `decompress()` tüm bloğu dilimlemeden önce belleğe açar ve kopyalama döngüsü gerçek açılan baytı saymıyor.)
  3. **Yakalanmayan istisnalar → HTTP 500 / beklenmeyen hata:** Şifreli zip (`RuntimeError`, **doğrulandı**), bozuk CRC (`BadZipFile`/`zlib.error`, **doğrulandı**), dosya-klasör ad çakışması (`sub` + `sub/main.tex` → `FileExistsError`, **doğrulandı**), Windows ayrılmış aygıt adları (`NUL` → sessizce aygıta yazılıp kaybolduğu **doğrulandı**), yasak karakterler (`?`, `*`, `<`, `>`, `|`) ve 260 karakteri aşan yollar (`OSError`) `TooliaError`'a çevrilmiyor.
  4. **Ters eğik çizgili klasör girişi:** Satır 73 `name = info.filename.replace("\\", "/")` yaparken satır 84 `name.endswith("/")` yerine `info.is_dir()` (yalnız `/` kontrol eder) kullanıyor. Ham Windows zip'lerindeki `sub\` klasör girişi dosya sanılıp alt dosyalarla çakışır.
  5. **Yüklenen dosya ↔ ZIP klasörü çakışması:** `workers.py:613-616`'da `dest = root / m.name` zip içinden çıkan bir klasörle çakışırsa `shutil.copyfile` `PermissionError`/`IsADirectoryError` fırlatır.
- **Önerilen düzeltme:**
  - Tüm `parts` elemanlarında `:`, yasak Windows karakterleri (`<>:"|?*`, kontrol karakterleri), ayrılmış adlar (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`LPT9`) ve `.` denetimi yap.
  - `if name.endswith("/") or info.is_dir():` kullan.
  - Akışlı kopyalamada gerçek yazılan baytı say; sıkıştırma oranı sınırı (`MAX_RATIO`, ör. 100) uygula; birden çok `.zip` için ortak toplam dosya/bayt kotası kullan ve tekrarlanan `file_id`'leri tekilleştir.
  - Açma döngüsünü `(zipfile.BadZipFile, RuntimeError, OSError)` için yakalayıp anlaşılır `TooliaError` fırlat; `workers.py`'de `dest.is_dir()` kontrolü ekle.

---

#### Y3. Eski/hazır `main.pdf` varsa ölümcül derleme hatasında başarılı sayılıp eski PDF döndürülüyor — **Doğrulandı (çalıştırıldı)**
- **Dosya:Satır:** `src/toolia/convert/latex.py:558-593`
- **Ne yanlış:** `compile_project`, derleme öncesinde `pdf = main.with_suffix(".pdf")` dosyasını temizlemiyor veya PDF'in bu derlemede üretildiğini doğrulamıyor.
- **Nasıl tetiklenir:**
  1. Proje `.zip`'i önceden derlenmiş bir `main.pdf` içeriyorsa, **veya**
  2. CLI ile `toolia latex main.tex` daha önce derlenip sonra belgeye ölümcül bir hata (ör. olmayan paket) eklendiyse:
  `pdflatex` yeni PDF üretmeden durur; `latex.py:567` ve `583` eski `main.pdf`'i geçerli sayar, gereksiz aux/rerun geçişleri yapar ve kullanıcıya *"Belgede 1 hata var; PDF yine de üretildi (Overleaf gibi)"* diyerek **eski PDF'i** döndürür (MiKTeX 25.12 ile birebir doğrulandı).
- **Etkisi:** Kullanıcı derlemenin başarılı olduğunu sanıp güncel olmayan eski PDF'i indirir/teslim eder.
- **Önerilen düzeltme:** Geçici klasörde derleme öncesinde `pdf.unlink(missing_ok=True)` yap. CLI yerinde derlemede eski `main.pdf` varsa geçici bir yedeğe alıp derleme başarısız olursa geri koy (ya da derlemenin yeni PDF ürettiğini açıkça doğrula).

---

#### Y4. Argüman enjeksiyonu: `-` ile başlayan dosya adları ve Ghostscript `%` biçim belirteçleri — **Doğrulandı (çalıştırıldı)**
- **Dosya:Satır:** `src/toolia/convert/latex.py:415, 523-525, 616, 673, 689, 704, 716, 723` ve `src/toolia/cli.py:586-592`
- **Ne yanlış:**
  1. `_SAFE_NAME = re.compile(r"^[\w.-]+$")` tire (`-`) ile başlayan adları geçiriyor (`-o.idx`, `-s.ist` geçtiği doğrulandı); `makeindex` bunu seçenek sanıp bozuluyor (`Expected -o <ind>`).
  2. `pdflatex`/`xelatex`/`lualatex`, `biber`, `bibtex` ve `makeindex` çağrılarında dosya adından önce `--` (veya `./`) yok. `-output-directory=x.tex` adlı ana dosya `pdflatex` tarafından seçenek olarak yorumlandı ve derleme başarısız oldu (doğrulandı).
  3. **Ghostscript (`_convert_eps`):**
     - CLI'da `toolia latex .` (göreli yol) çağrıldığında `kaynak` resolve edilmediği için `str(eps)` `-h.eps` (veya `@...`) ile başlayabiliyor; Ghostscript `-h.eps`'i yardım seçeneği sanıp `rc=0` ile dönüşümü atladı (doğrulandı).
     - Dosya adında `%` varsa (ör. `fig%d.eps`), `-sOutputFile=...fig%d-eps-converted-to.pdf` içindeki `%d` Ghostscript tarafından sayfa numarası biçim belirteci olarak açılıyor (`fig1-eps-converted-to.pdf` oluştu, `rc=1` döndü ve artık dosya silinmedi — doğrulandı).
- **Önerilen düzeltme:**
  - `_SAFE_NAME = re.compile(r"^[A-Za-z0-9_][\w.-]*$")` (ilk karakter `-` veya `.` olamaz).
  - TeX motorları, `biber`, `bibtex` ve `makeindex` çağrılarında dosya/kök adından önce `--` geçir (veya `-` ile başlayan adları güvenli biçimde reddet/ön ekle).
  - `_convert_eps`: `eps = eps.resolve()`, `target = target.resolve()`, Ghostscript'te `--` kullan; `target` yolunda `%` varsa geçici temiz adla çevirip `target`'a `os.replace` ile taşı. `cli.py`'de `kaynak = kaynak.resolve()`.

---

### ORTA

#### O1. Zaman aşımı bütçesi ihlali (`_convert_eps` ve `_ensure_cm_super` `runner.deadline`'ı yok sayıyor) — **Doğrulandı (kod)**
- **Dosya:Satır:** `src/toolia/convert/latex.py:498, 523-525`
- **Ne yanlış:** `compile_project` tek 15 dakikalık bütçe (`TIMEOUT_S`) hedefliyor ancak:
  - `_convert_eps` her EPS için sabit `timeout=120` kullanıyor (`200 × 120 sn = 400 dk`).
  - `_ensure_cm_super` → `install_miktex_package` her deneme (`miktex`, `mpm`) için sabit `15 dk` (toplam 30 dk) kullanıyor ve `runner.deadline`'dan düşmüyor.
- **Etkisi:** Bozuk veya yavaş 200 EPS'li bir proje, bir iş parçacığını 6+ saat tutabilir.
- **Önerilen düzeltme:** Her iki adımda kalan süreyi `runner.deadline - time.monotonic()` üzerinden hesapla (`remaining <= 0` ise `proc.TimedOut` fırlat) ve alt süreç timeout'unu `min(step_limit, remaining)` yap.

---

#### O2. Kuyruk eşzamanlılık sınırı (`LIMITS`) yok ve `_CM_SUPER_CHECKED` yarış durumu — **Doğrulandı (kod)**
- **Dosya:Satır:** `src/toolia/jobs/manager.py:33` ve `src/toolia/convert/latex.py:428, 489-498`
- **Ne yanlış:**
  1. `LIMITS` sözlüğünde `tex_to_pdf` ve `install_engine` yok; genel havuzda 4 eşzamanlı LaTeX derlemesi veya paralel `winget` kurulumu çalışabilir. Eşzamanlı MiKTeX derlemeleri (`--enable-installer`) veya ilk `biber` açılışı aynı MiKTeX/PAR kilitlerine çarpabilir.
  2. `_ensure_cm_super` kilit kullanmadan `_CM_SUPER_CHECKED.add(key)` yaptıktan *sonra* kurulumu başlatıyor:
     - İş 1 `cm-super` kurarken İş 2 `key in _CM_SUPER_CHECKED` görüp kurulum bitmeden `pdflatex`'e girer (bitmap font veya MiKTeX veritabanı kilidi hatası).
     - Kurulum geçici ağ hatasıyla başarısız olursa `key` kümede kalır; sunucu yeniden başlayana kadar bir daha denenmez.
- **Önerilen düzeltme:** `LIMITS`'e `"tex_to_pdf": 1, "install_engine": 1` ekle; `_CM_SUPER_CHECKED` etrafına `threading.Lock` koy ve `key`'i yalnızca `cm-super` zaten kuruluysa ya da kurulum başarılı olduysa ekle.

---

#### O3. `engines.find_on_path` erişilemeyen PATH klasöründe `PermissionError` ile çöküyor — **Doğrulandı (çalıştırıldı)**
- **Dosya:Satır:** `src/toolia/engines.py:171`
- **Ne yanlış:** `candidate.is_file()` `OSError` / `PermissionError` yakalamıyor. Windows'ta `PATH` içinde okuma izni kısıtlı tek bir klasör varsa (denetim sırasında `AppData\Local\PowerToys\DSCModules` üzerinde tetiklendi), `find_on_path` ve dolayısıyla `detect_all()` / `/api/engines` çöküyor.
- **Önerilen düzeltme:** `try: ... except OSError: continue` ile sar.

---

#### O4. `find_main` Linux'ta `.TEX` uzantısını kaçırıyor ve aynı kök adlı alt dosyada ana dosyayı eliyor — **Doğrulandı (kod + çalıştırıldı)**
- **Dosya:Satır:** `src/toolia/convert/latex.py:120, 134-135, 581`
- **Ne yanlış:**
  1. `root.rglob("*.tex")` büyük/küçük harf duyarlıdır. Linux'ta (ext4) `MAIN.TEX` / `Thesis.Tex` bulunamaz ("Projede .tex dosyası yok"). Aynı durum satır 581'deki `tex_sources` için de geçerli.
  2. `included = {Path(ref.strip()).stem.lower() ...}` yalnızca dosya gövdesine (`stem`) bakıyor. Kök `main.tex` içinde `\input{sub/main}` varsa `"main"` kümesine giriyor ve kök `main.tex` kendi kendini dışlayıp başka bir dosyayı ana dosya seçiyor (doğrulandı).
- **Önerilen düzeltme:**
  - `p.suffix.lower() == ".tex"` ile büyük/küçük harf duyarsız tara (`_convert_eps:510` gibi).
  - `included` kontrolünde `(p.parent / ref).resolve()` (`.tex` ekli/eksiz) ile gerçek göreli dosya yollarını eşleştir.

---

#### O5. `Home.tsx` yönlendirmesi `.csv` / `.txt` içeren LaTeX projelerini reddediyor — **Doğrulandı (kod)**
- **Dosya:Satır:** `web/src/pages/Home.tsx:37` (karşılaştır: `web/src/pages/Latex.tsx:13`, `web/src/tools.ts:137`)
- **Ne yanlış:** `ACCEPT.latex` ve `Latex.tsx` `KINDS` listesi `.csv` (`"office"`) ve `.txt` (`"text"`) dosyalarını kabul ediyor; ancak `Home.tsx:37` yalnızca `all("tex", "zip", "image", "pdf", "other")` kontrolü yapıyor.
- **Nasıl tetiklenir:** Ana sayfaya (veya global bırakma alanına) `main.tex` + `veriler.csv` ya da `main.tex` + `not.txt` bırakıldığında "Bu dosya türleri birlikte işlenemiyor" hatası çıkar.
- **Önerilen düzeltme:** `Home.tsx:37`'yi `Latex.tsx`'le uyumlu yap (`"text"` ve `.csv`/veri dosyalarını kabul et) ve `web/src/home.test.ts`'ye test ekle.

---

#### O6. `CommandPalette` LaTeX dosyalarını PDF sanıyor; `Jobs.tsx`'te `tex_to_pdf` ikonu eksik — **Doğrulandı (kod)**
- **Dosya:Satır:** `web/src/components/CommandPalette.tsx:49` ve `web/src/pages/Jobs.tsx:43-62`
- **Ne yanlış:**
  1. `NON_PDF_ROUTES` içinde `"latex"` yok. `#/latex?dosya=<zip_id>` ekranında `Ctrl+K` açıldığında komut paleti `.zip`/`.tex` dosyasını "Aktif dosya" olarak tüm PDF araçlarına (Birleştir, Böl, OCR, Sıkıştır, Sayfa Düzenle…) aktarmayı öneriyor.
  2. `Jobs.tsx` `JOB_TOOL` tablosunda `tex_to_pdf: "latex"` eksik; İşler ekranında LaTeX işleri Sigma/Dönüştür tonu yerine varsayılan anahtar (Wrench) ikonuyla görünüyor.
- **Önerilen düzeltme:** `NON_PDF_ROUTES`'a `"latex"`, `JOB_TOOL`'a `tex_to_pdf: "latex"` ekle.

---

#### O7. Telefon modunda (LAN) arayüz deneyimi ve `install_engine` çalışan savunması — **Doğrulandı (kod)**
- **Dosya:Satır:** `web/src/pages/Latex.tsx:37-66`, `web/src/pages/Settings.tsx:639-642`, `src/toolia/jobs/workers.py:638`
- **Ne yanlış:**
  1. `Latex.tsx` `settings.local` bilgisini almıyor: telefondan `#/latex` açıldığında kapalı olduğuna dair hiçbir uyarı yok; kullanıcı dosyalarını yükleyip "PDF'e derle"ye basınca ancak sunucudan hata alıyor.
  2. Windows sunucuda MiKTeX (veya LibreOffice) eksikse hem `Latex.tsx:60` hem `Settings.tsx:639-642` `settings.local` kontrolü olmadan telefonda da kurulum düğmesini gösteriyor; onay penceresinden sonra sunucu 400 ile reddediyor.
  3. `workers.py:638` (`install_engine`), `tex_to_pdf`'in aksine ikinci katman olarak `if access.is_device():` denetimi yapmıyor (yalnız rota katmanı denetliyor).
- **Önerilen düzeltme:** `Latex`'e `local={settings?.local ?? true}` geçirip telefon modunda banner + devre dışı düğme göster; `InstallEngine`'i yalnızca `local` iken göster; `workers.install_engine` başına `if access.is_device(): raise TooliaError(...)` ekle.

---

#### O8. MiKTeX `--enable-installer` / `AutoInstall=1` çevrimdışı vaadiyle çelişiyor; `ag_cikisi.py` kapsamıyor — **Doğrulandı (kod)**
- **Dosya:Satır:** `src/toolia/convert/latex.py:410-412, 468`, `docs/KULLANIM.md:35-36`, `tests/guvenlik/ag_cikisi.py`
- **Ne yanlış:**
  - `README.md` ve `docs/KULLANIM.md` ("Bilinen istisna: Microsoft Edge… Diğer motorlar hiç bağlanmaz") MiKTeX'in derleme sırasında internetten paket indirdiğini güvenlik bölümünde belirtmiyor.
  - Güvenilmeyen bir `.tex` belgesi, kurulu olmayan büyük CTAN paketlerini kullanıcının MiKTeX kurulumuna sessizce indirtebilir (disk/ağ tüketimi ve kalıcı sistem değişikliği).
  - `tests/guvenlik/ag_cikisi.py` LaTeX derlemesini hiç ölçmüyor.
- **Önerilen düzeltme:** MiKTeX otomatik paket indirmesini güvenlik istisnaları arasında açıkça belgele; isteğe bağlı "çevrimdışı derle (eksik paket indirme)" seçeneği eklemeyi değerlendir; K3 kapatıldıktan sonra `ag_cikisi.py`'ye LaTeX (özellikle `biber` uzak kaynak) adımını ekle.

---

### DÜŞÜK

#### D1. `pick_engine` ve `_code` yorum/paket algılama eksikleri — **Doğrulandı (çalıştırıldı)**
- **Dosya:Satır:** `src/toolia/convert/latex.py:104-106, 165-176, 549`
- **Ne yanlış:**
  1. `pick_engine:169` `_code(source)` yerine `line.split("%", 1)[0]` kullanıyor; kaçışlı `\%` sonrası aynı satırdaki `\usepackage{fontspec}` atlanıyor (`pdflatex` dönüyor — doğrulandı).
  2. `_code:106` içindeki `(?<!\\)%` deseni `100\\% \usepackage{fontspec}` (çift ters eğik çizgi + gerçek yorum) durumunu yorum olarak kesmiyor (doğrulandı). Doğrusu `(?<!\\)(?:\\\\)*%`.
  3. `compile_project:549` yalnız `main.tex` içeriğine bakıyor; `fontspec`/`luacode` bir `preamble.tex` ya da özel `.cls`/`.sty` dosyasındaysa (Overleaf tez şablonlarında yaygın) yanlışlıkla `pdflatex` seçiliyor.
  4. `_MAGIC` tüm dosyayı tarıyor; TeX editörleri standart olarak yalnız ilk ~20 satıra bakar.

#### D2. Günlük çözümleme kenar durumları — **Doğrulandı (çalıştırıldı)**
- **Dosya:Satır:** `src/toolia/convert/latex.py:195-197, 272-276, 323, 366`
- **Ne yanlış:**
  1. **LuaLaTeX 79 karakter sarma:** MiKTeX'te `lualatex` `-max-print-line=1000` almadığı için uzun hata iletileri 79 karakterde kırılıyor; `(paket)` öneki olmayan devam satırları okunmadığından `_friendly` (ör. `The font "..." cannot be found`) eşleşmeyebiliyor (doğrulandı).
  2. **`babel_shorthand_hint`:** `_TURKISH_BABEL` yalnız `\usepackage[...turkish...]{babel}` yakalıyor; `\documentclass[turkish]{article}\usepackage{babel}` sınıf seçeneğini kaçırıyor (doğrulandı).
  3. **`_FILE_LINE`:** Uzantı listesi büyük/küçük harf duyarlı (`.TEX` yakalanmaz).
  4. **`_BIBER_REQUEST`:** Sınırsız `re.DOTALL`, `Please (re)run Biber` ile `afterwards` arasına giren bir `Rerun` uyarısını yutabiliyor (doğrulandı); en çok 3–4 satırla sınırlandırılmalı.

#### D3. CLI `toolia latex` girdi/çıktı kenar durumları — **Doğrulandı (kod)**
- **Dosya:Satır:** `src/toolia/cli.py:586-596`, `src/toolia/convert/latex.py:593`
- **Ne yanlış:**
  1. `kaynak` `.zip` ya da klasör değilse `.tex` uzantısı doğrulanmıyor (`toolia latex resim.png` doğrudan `pdflatex`'e gider).
  2. `-o yeni/klasor/out.pdf` verildiğinde `out.parent` yoksa `shutil.move` `FileNotFoundError` fırlatır (`out.parent.mkdir(parents=True, exist_ok=True)` eksik).

#### D4. Özel sözlük türleri (`nomain` + `\newglossary`) çalışmıyor — **Doğrulandı (kod)**
- **Dosya:Satır:** `src/toolia/convert/latex.py:709`
- **Ne yanlış:** Yalnız `.glo` veya `.acn` dosyasına bakılıyor; `\usepackage[nomain]{glossaries}` ile tanımlanan özel sözlükler (ör. `.syg`) işlenmiyor. (K1 düzeltmesiyle `.aux`'taki tüm `\@newglossary` kayıtları taranınca kendiliğinden çözülür.)

#### D5. `Latex.tsx` erişilebilirlik eksikleri — **Doğrulandı (kod)**
- **Dosya:Satır:** `web/src/pages/Latex.tsx:58, 101-103`
- **Ne yanlış:** Motor eksikliği banner'ında (`div.banner.error`) `role="alert"` yok; "Derleyici" alanının altındaki açıklama metni `aria-describedby` ile `<select>`'e bağlı değil.

#### D6. Test ve CI kapsam boşlukları — **Doğrulandı (kod)**
- **Dosya:Satır:** `.github/workflows/ci.yml:43-46, 86-103`, `tests/test_latex.py`
- **Ne yanlış:**
  - Ne Windows CI ne Linux CI TeX kuruyor; bu nedenle `tests/test_latex.py`'deki 13 gerçek derleme testi CI'da **hiç çalışmıyor**.
  - Eksik regresyon testleri: `makeglossaries-lite` / `.aux` enjeksiyonu, `biber.conf` yazma engeli, `biber` uzak HTTP kaynak engeli, NTFS ADS (`sub/a.tex:stream`), çoklu/oran zip bombası, eski `main.pdf` varken ölümcül hata, `-` ve `%` içeren EPS/TEX/IDX dosya adları, CLI `toolia latex`, iptalde süreç temizliği, `Latex.tsx` bileşen testi.

#### D7. Belge ve örnek yapılandırma eksikleri — **Doğrulandı (kod)**
- **Dosya:Satır:** `config.example.toml:18-23`, `README.md:19, 86`, `docs/KULLANIM.md:14`, `CHANGELOG.md:7`, `web/src/tools.ts:52`
- **Ne yanlış:**
  - `config.example.toml` `[engines]` bölümünde `# latex = ...` örneği yok (`KULLANIM.md` motor yolları için bu dosyayı gösteriyor).
  - "Süre sınırı yok" ifadesi `GUVENLIK_PLANI.md`'deki 15 dakikalık `TIMEOUT_S` ile çelişiyor; "Overleaf süre sınırına takılmadan" gibi daha net bir ifade kullanılmalı.

---

### NOT / ŞÜPHE (Test Edilmedi)

- **N1 (Şüphe — temiz Windows'ta winget MiKTeX kurulumu):** Temiz bir Windows'ta `winget install MiKTeX.MiKTeX --silent` kurulumunun kullanıcı/yönetici kapsamı, `initexmf --set-config-value=[MPM]AutoInstall=1` komutunun yönetici kurulumunda `--admin` isteyip istemediği ve ilk `miktex packages install cm-super` öncesinde `miktex packages update-package-database` gerekip gerekmediği (bu makinede MiKTeX zaten kurulu olduğu için) doğrulanmadı; temiz Windows VM'de denenmeli.
- **N2 (Şüphe — XeLaTeX EPS dönüşümü):** `compile_project:560` XeLaTeX'te EPS dönüşümünü `xdvipdfmx`'e bırakıyor. `xdvipdfmx`'in `dvipdfmx.cfg` üzerinden çağırdığı Ghostscript komutunda `-dSAFER` bayrağının her dağıtımda (MiKTeX / TeX Live) zorunlu olduğu ayrıca doğrulanmadı.
- **N3 (Bilgi — LuaLaTeX okuma yüzeyi):** `-no-shell-escape` altında LuaLaTeX'te `socket` / `socket.http` / `socket.dns` kapalı (doğrulandı), fakat `lfs` (dizin listeleme), `os.getenv` (ortam değişkenleri) ve `io.open(..., "r")` açık (doğrulandı). K3 kapatılmadığı sürece bunlar uzaktan sızdırma için kullanılabilir; K3 kapatıldığında risk yalnızca yerel PDF çıktısıyla sınırlı kalır.

---

## 2. Önceki İddialardan Yanlış veya Eksik Çıkanlar

1. **"Kabuk komutu (`\write18`) her motorda kapalı"** → **Eksik/Yanlış (K1):** Motorların kendisinde `-no-shell-escape` doğru uygulanmış, ancak `makeglossaries-lite` üzerinden `.aux` dosyasıyla `os.execute()` kabuk komutu çalıştırılabiliyor.
2. **"ÖLÇÜLDÜ: belge proje klasörü dışına YAZAMIYOR"** → **Yanlış (K2):** Yalnız TeX motorları ölçülmüş; `biber` çalışma klasöründeki `biber.conf` ile proje klasörü dışına dosya yazabiliyor (doğrulandı).
3. **"Dosyalar internete çıkmaz / Diğer motorlar hiç bağlanmaz"** → **Yanlış (K3 + O8):** `biber` uzak HTTP/HTTPS kaynaklarına istek atabiliyor (doğrulandı); ayrıca MiKTeX `--enable-installer` derleme sırasında internete bağlanıyor ve `ag_cikisi.py` bunu kapsamıyor.
4. **"Tek süre sınırı 15 dk (`TIMEOUT_S`)"** → **Yanlış (O1):** `_convert_eps` (en çok `200 × 120 sn`) ve `_ensure_cm_super` (`15 dk × 2`) `runner.deadline`'ı kullanmıyor.
5. **"Zip açmada güvensiz yollar reddedilir, 1 GB / 5000 dosya sınırı var"** → **Eksik (Y2):** Alt klasördeki NTFS ADS (`sub/a.tex:stream`) geçiyor, çoklu zip (500'e kadar) sınırı çarpıyor ve sıkıştırma oranı denetimi yok.
6. **"LaTeX `optional` işaretli; eksik diye sorun çıkarmaz"** → **Eksik (Y1):** `Welcome.tsx` ve `kurulum.py` bunu gözetiyor ama `cli.py:motorlar` gözetmiyor ve Linux CI'yı kıracak.

---

## 3. Kontrol Edilip Sorun Bulunmayan Alanlar

- **Telefon modu (LAN) rota ve iş kuyruğu yalıtımı:** `routes_jobs.py:50-52`, `security.py:202-210`, `manager.py:192-194, 264-268` ve `workers.py:593-596` incelendi. `SessionGuard` → `access.acting_as(owner)` → `Job.owner` → worker iş parçacığında `access.acting_as(job.owner)` akışı doğru taşınıyor; başka iş türlerinden TeX'e giden bir yol yok.
- **Ayarlar API'sinde `engines.latex` yüzeyi:** `routes_settings.py:74-116` ve `settings.py:167` incelendi. `SettingsBody` `extra="forbid"` kullanıyor; `engines` alanı API'den okunup değiştirilemiyor (yalnız diskteki `config.toml` ile).
- **TeX motorlarının kendi yazma ve ağ kısıtları:** MiKTeX 25.12 üzerinde `pdflatex` göreli `\openout\f=../outside.txt` reddedildi; `lualatex -no-shell-escape` altında `io.open('../outside.txt','w')` ve `socket`/`socket.http`/`socket.dns` kapalı olduğu doğrulandı.
- **Arayüz XSS koruması:** `Latex.tsx`, `JobPanel.tsx` ve `Jobs.tsx` incelendi; tüm günlük, hata, uyarı ve dosya adları React metin düğümü olarak basılıyor (`dangerouslySetInnerHTML` yok).
- **Home.tsx eski yönlendirmeleri:** PDF, çoklu PDF, resim, Office, HTML, TXT, Markdown (+ ekleri) ve PDF + resim (hata) senaryoları korunuyor (`homeRoute` sıralaması sağlam; yalnız O5'teki `.tex + .csv/.txt` eksiği var).
- **Mevcut testler ve kod kalitesi araçları:** Bu makinede `ruff` (0 hata), `eslint` (0 uyarı), `tsc --noEmit` (0 hata), `vitest` (85/85), `web/scripts/i18n-eksik.mjs` ("Eksik çeviri yok") ve `pytest` (`test_latex.py`, `test_guvenlik_lan.py`, `test_desktop.py`, `test_engines.py`, `test_robustness.py` — 166/166) hepsi geçti.
- **İptal / süreç ağacı sonlandırma mekanizması:** `proc.py:69-79, 178-216` incelendi; `run_lines` hem taşan hem sessiz kalan çıktılarda `POLL_S` (0.2 sn) içinde iptal ve zaman aşımını kontrol ediyor ve `kill_tree` özyinelemeli çocuk süreçleri (`biber` `par-*` çocukları dahil) önce öldürüyor.
