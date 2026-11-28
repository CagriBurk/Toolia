import { Check, ChevronRight, CircleX, FolderOpen, LoaderCircle, Monitor, Moon, RefreshCw, Sun, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  api,
  errorMessage,
  type EngineStatus,
  type EnginesResponse,
  type LanInfo,
  type SettingsResponse,
  type SettingsValues,
  type UpdateInfo,
} from "../api";
import Icon from "../components/Icon";
import InstallLibreOffice, { InstallEngine } from "../components/InstallLibreOffice";
import Modal from "../components/Modal";
import { useJobActivity } from "../hooks";
import { restartApp } from "../restart";
import { type Lang, setLang, storedLang, t } from "../i18n";
import { resetTheme, setTheme as setAppTheme, useStoredTheme } from "../theme";
import { toast } from "../toast";

interface Props {
  data: EnginesResponse | null;
  refreshing: boolean;
  onRefresh: () => void;
  settings: SettingsResponse | null;
  onSettings: (s: SettingsResponse) => void;
  onShowWelcome: () => void;
}

const THEME_LABEL: Record<string, string> = { ders: "Ders notu", rapor: "Rapor", sade: "Sade" };
const RETENTION_PRESETS = [
  [6, "6 saat"],
  [24, "1 gün"],
  [72, "3 gün"],
  [168, "1 hafta"],
  [720, "30 gün"],
] as const;

function statusLabel(e: EngineStatus): { text: string; cls: string } {
  if (e.ok) return { text: t("Hazır"), cls: "ok" };
  if (e.available) return { text: t("Eksik parça"), cls: "warn" };
  return { text: t("Kurulu değil"), cls: "bad" };
}

const STATUS_ICON = { ok: Check, warn: TriangleAlert, bad: CircleX } as const;

/** Ayar kaydı + (gerekiyorsa) yeniden başlatma; hata bildirim olarak gösterilir. */
function useSave(onSettings: (s: SettingsResponse) => void) {
  const [busy, setBusy] = useState(false);
  const save = async (changes: Partial<SettingsValues>, okText = t("Ayarlar kaydedildi.")) => {
    setBusy(true);
    try {
      const s = await api.saveSettings(changes);
      onSettings(s);
      toast.ok(okText);
      return s;
    } catch (e) {
      toast.error(errorMessage(e));
      return null;
    } finally {
      setBusy(false);
    }
  };
  return { save, busy };
}

function RestartLine({ settings }: { settings: SettingsResponse }) {
  const [restarting, setRestarting] = useState(false);
  if (!settings.restart_pending) return null;
  if (!settings.restart_available) {
    return (
      <div className="banner warn" role="status">
        {t("Port ya da telefon modu değişikliği uygulama yeniden başlatılınca geçerli olur: uygulamayı kapatıp yeniden aç.")}
      </div>
    );
  }
  return (
    <div className="banner warn restart-banner" role="status">
      {t("Port ya da telefon modu değişikliğinin geçerli olması için uygulama yeniden başlamalı (pencere açık kalır, açık işler varsa bitmesini bekle).")}{" "}
      <button
        type="button"
        className="primary small"
        disabled={restarting}
        onClick={() => {
          setRestarting(true);
          restartApp().catch((e) => {
            setRestarting(false);
            toast.error(errorMessage(e));
          });
        }}
      >
        {restarting ? t("Yeniden başlatılıyor…") : t("Şimdi yeniden başlat")}
      </button>
    </div>
  );
}

function GeneralSettings({ settings, onSettings }: { settings: SettingsResponse; onSettings: Props["onSettings"] }) {
  const v = settings.values;
  const [retention, setRetention] = useState(String(v.retention_hours));
  const [vault, setVault] = useState(v.vault_path);
  const [theme, setTheme] = useState(v.default_theme);
  const [paper, setPaper] = useState(v.default_paper);
  const [picking, setPicking] = useState(false);
  const { save, busy } = useSave(onSettings);
  const hours = Number(retention);
  const retentionValid = Number.isInteger(hours) && hours >= 1 && hours <= 8760;
  const dirty =
    hours !== v.retention_hours || vault.trim() !== v.vault_path || theme !== v.default_theme || paper !== v.default_paper;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!retentionValid) return;
    const s = await save({ retention_hours: hours, vault_path: vault.trim(), default_theme: theme, default_paper: paper });
    if (s) setVault(s.values.vault_path);
  };

  const pick = async () => {
    setPicking(true);
    try {
      const r = await api.pickFolder(vault || undefined);
      if (r.path) setVault(r.path);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setPicking(false);
    }
  };

  return (
    <form className="card settings-card settings-form" onSubmit={submit} aria-labelledby="genel-baslik">
      <div className="section-head">
        <h2 id="genel-baslik">{t("Genel")}</h2>
      </div>
      <div className="setting-row">
        <div className="setting-label">
          <label htmlFor="ayar-saklama">{t("Dosyaları sakla")}</label>
          <p id="ayar-saklama-not" className="muted small">
            {t("Bu süreden uzun açılmamış, sabitlenmemiş dosyalar ve iş kayıtları silinir. Saklamak istediklerini İşler ve dosyalar'da sabitle.")}
          </p>
        </div>
        <div className="setting-control">
          <span className="input-unit">
            <input
              id="ayar-saklama"
              className="input narrow"
              type="number"
              min={1}
              max={8760}
              value={retention}
              aria-describedby="ayar-saklama-not"
              aria-invalid={!retentionValid}
              onChange={(e) => setRetention(e.target.value)}
            />{" "}
            {t("saat")}
          </span>
          <span className="preset-row">
            {RETENTION_PRESETS.map(([h, label]) => (
              <button
                key={h}
                type="button"
                className={`small preset${hours === h ? " on" : ""}`}
                onClick={() => setRetention(String(h))}
              >
                {t(label)}
              </button>
            ))}
          </span>
          {!retentionValid && <p className="error-text small">{t("1 ile 8760 saat (1 yıl) arasında bir tam sayı yaz.")}</p>}
        </div>
      </div>

      <div className="setting-row">
        <div className="setting-label">
          <label htmlFor="ayar-kasa">{t("Obsidian kasası")}</label>
          <p id="ayar-kasa-not" className="muted small">
            {t("Markdown → PDF'te")} <code>![[resim.png]]</code>{" "}
            {t("resimleri kasanın her yerinde adıyla aranır. Yalnızca bu klasörün altı okunur.")}
          </p>
        </div>
        <div className="setting-control">
          <div className="input-with-button">
            <input
              id="ayar-kasa"
              className="input"
              placeholder={t("Tanımlı değil")}
              value={vault}
              aria-describedby="ayar-kasa-not"
              onChange={(e) => setVault(e.target.value)}
            />
            {settings.desktop && (
              <button type="button" onClick={() => void pick()} disabled={picking}>
                <Icon icon={FolderOpen} size={17} />
                {picking ? t("Pencere açık…") : t("Klasör seç…")}
              </button>
            )}
            {vault && (
              <button type="button" className="link-button" onClick={() => setVault("")}>
                {t("Kaldır")}
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="setting-row">
        <div className="setting-label">
          <label htmlFor="ayar-tema">{t("Varsayılan tema")}</label>
          <p className="muted small">{t("Markdown → PDF belge teması (notun ön bilgisinde belirtilmemişse).")}</p>
        </div>
        <div className="setting-control">
          <select id="ayar-tema" value={theme} onChange={(e) => setTheme(e.target.value)}>
            {settings.themes.map((th) => (
              <option key={th} value={th}>
                {t(THEME_LABEL[th] ?? th)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="setting-row">
        <div className="setting-label">
          <label htmlFor="ayar-kagit">{t("Varsayılan kağıt")}</label>
          <p className="muted small">{t("Markdown → PDF'te notun ön bilgisinde ya da ekranda seçilmemişse kullanılır.")}</p>
        </div>
        <div className="setting-control">
          <select id="ayar-kagit" value={paper} onChange={(e) => setPaper(e.target.value)}>
            {settings.papers.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="form-actions">
        <button type="submit" className="primary" disabled={!dirty || !retentionValid || busy || !settings.local}>
          {busy ? t("Kaydediliyor…") : t("Kaydet")}
        </button>
        {!settings.local && <span className="muted small">{t("Ayarlar yalnızca bilgisayarın kendisinden değiştirilebilir.")}</span>}
      </div>
    </form>
  );
}

function PhoneQr({ windows, port }: { windows: boolean; port: number }) {
  const [info, setInfo] = useState<LanInfo | null>(null);
  const [selectedIp, setSelectedIp] = useState<string | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => {
    api
      .lan(selectedIp)
      .then(setInfo)
      .catch((e: Error) => setError(e.message));
  }, [selectedIp]);

  // QR kod tek kullanımlık: bir cihaz eşleşince yenisi çıkar, bağlı cihaz listesi de değişir.
  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  if (error) return <p className="muted small">{error}</p>;
  if (!info?.enabled) return null;
  if (!info.urls?.length) return <p className="warn-line">{t("Yerel ağ adresi bulunamadı. Wi-Fi'ye bağlı mısın?")}</p>;
  const ips = info.ips ?? [];
  const activeIp = info.selected_ip ?? ips[0];
  const activeUrl = (activeIp && info.urls.find((u) => u.startsWith(`http://${activeIp}:`))) || info.urls[0];
  const activePort = info.port ?? port;
  return (
    <div className="phone-mode">
      {info.qr_svg && (
        <img
          className="qr"
          alt={t("Telefonla bağlanmak için QR kod")}
          src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(info.qr_svg)}`}
        />
      )}
      <div className="phone-info">
        <p>{t("Telefonun kamerasıyla QR kodu okut ya da adresi yaz:")}</p>
        {ips.length > 1 && (
          <div className="preset-row" role="group" aria-label={t("Ağ adresi seç")}>
            {ips.map((ip) => (
              <button
                key={ip}
                type="button"
                className={`small preset mono${ip === activeIp ? " on" : ""}`}
                aria-pressed={ip === activeIp}
                onClick={() => setSelectedIp(ip)}
              >
                {ip}
              </button>
            ))}
          </div>
        )}
        <p className="mono small break phone-url">{activeUrl}</p>
        <p className="muted small">{t("Kod tek kullanımlık; her cihaz için yenisi çıkar.")}</p>
        {!windows && (
          <p className="muted small">
            {t("Telefon bağlanamıyorsa güvenlik duvarında portu aç:")}{" "}
            <code>sudo ufw allow {activePort}/tcp</code>
          </p>
        )}
        {!!info.devices?.length && (
          <>
            <p>{t("Bağlı cihazlar: {ips}", { ips: info.devices.map((d) => d.ip).join(", ") })}</p>
            <button
              type="button"
              className="danger"
              onClick={() =>
                api
                  .revokeDevices()
                  .then(refresh)
                  .catch((e: Error) => setError(e.message))
              }
            >
              {t("Hepsinin bağlantısını kes")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

const PHONE_SECTION = "telefon";

/** Yeniden başlatmadan sonra sayfa yeniden yüklenir: telefon modu kartına dönülsün diye adreste
 * işaret bırakılır (aynı portta `reload`, yeni portta `restartApp` karmayı taşır). Geçmişe kayıt
 * eklenmez. */
function markPhoneSection(on: boolean) {
  history.replaceState(null, "", on ? `#/ayarlar?bolum=${PHONE_SECTION}` : "#/ayarlar");
}

type Phase = "ask" | "saving" | "restarting" | "failed";

/** Telefon modunu açıp kapatmadan önce sorar; onaylanınca ayarı kaydeder ve uygulamayı kendisi
 * yeniden başlatır (telefon modu sunucunun yerel ağdan da dinlemesi demek: açılışta seçilir). */
function PhoneModeDialog({
  enable,
  windows,
  port,
  onSettings,
  onClose,
}: {
  enable: boolean;
  windows: boolean;
  port: number;
  onSettings: Props["onSettings"];
  onClose: () => void;
}) {
  const { running: jobs } = useJobActivity();
  const [phase, setPhase] = useState<Phase>("ask");
  const [error, setError] = useState<string | null>(null);
  // Tarayıcı Esc'e ikinci kez basılınca pencereyi yine de kapatabilir; iş sürer, sonuç bildirimle.
  const [hidden, setHidden] = useState(false);
  const hiddenRef = useRef(false);
  const busy = phase === "saving" || phase === "restarting";
  const failText = t("Ayar kaydedildi, ama uygulama yeniden başlatılamadı. Telefon modu, uygulama yeniden açılınca {durum}.", {
    durum: enable ? t("açılır") : t("kapanır"),
  });

  const confirm = async () => {
    setPhase("saving");
    setError(null);
    let s: SettingsResponse;
    try {
      s = await api.saveSettings({ lan: enable });
    } catch (e) {
      setPhase("ask");
      setError(errorMessage(e));
      return;
    }
    onSettings(s);
    if (!s.restart_available) {
      toast.ok(t("Kaydedildi. Geçerli olması için uygulamayı kapatıp yeniden aç."));
      onClose();
      return;
    }
    setPhase("restarting");
    markPhoneSection(true);
    try {
      await restartApp(); // başarılıysa sayfa yeni sunucudan yeniden yüklenir
    } catch (e) {
      markPhoneSection(false);
      if (hiddenRef.current) {
        toast.error(`${failText} ${errorMessage(e)}`);
        onClose();
        return;
      }
      setPhase("failed");
      setError(errorMessage(e));
    }
  };

  if (hidden) return null;
  return (
    <Modal
      title={enable ? t("Telefon modu açılsın mı?") : t("Telefon modu kapatılsın mı?")}
      busy={busy}
      onClose={() => {
        if (!busy) return onClose();
        hiddenRef.current = true;
        setHidden(true);
      }}
    >
      <div className="phone-dialog">
        {enable ? (
          <>
            <p>
              {t("Aynı Wi-Fi'deki telefon ve tabletler, bu bilgisayarda gösterilen QR kodu okutarak Toolia'yı kullanabilir.")}
            </p>
            <p>
              {t("Telefon modu açık başlasın diye uygulama birkaç saniyeliğine yeniden başlatılacak. Pencere açık kalır; uygulama açılınca QR kod bu sayfada görünür.")}
            </p>
            <ul className="phone-notes muted small">
              <li>{t("Bağlantı yerel ağda şifresizdir (HTTP): yalnızca güvendiğin Wi-Fi'de aç, işin bitince kapat.")}</li>
              <li>{t("Yalnızca QR kodu okutan cihazlar bağlanabilir; kod tek kullanımlıktır.")}</li>
              <li>
                {windows ? (
                  t("Windows güvenlik duvarı ilk seferde izin isteyebilir: \"Özel ağlar\" için izin ver. Wi-Fi'n Windows'ta \"Ortak ağ\" olarak görünüyorsa telefon bağlanamaz; güvendiğin ağsa ağ ayarlarından \"Özel\" yap.")
                ) : (
                  <>
                    {t("Linux'ta güvenlik duvarı (ufw / firewalld) açıksa telefon bağlanamaz; portu açmak için:")}{" "}
                    <code>sudo ufw allow {port}/tcp</code>
                  </>
                )}
              </li>
            </ul>
          </>
        ) : (
          <>
            <p>{t("Telefon ve tabletler artık bağlanamaz; bağlı cihazların bağlantısı kesilir.")}</p>
            <p>{t("Bunun için uygulama birkaç saniyeliğine yeniden başlatılacak. Pencere açık kalır.")}</p>
          </>
        )}
        {jobs > 0 && phase !== "failed" && (
          <div className="banner warn" role="alert">
            {t("Şu an {isler} çalışıyor. Yeniden başlatma çalışan işleri durdurur: bitmelerini beklemen önerilir.", {
              isler: jobs === 1 ? t("bir iş") : t("{n} iş", { n: jobs }),
            })}
          </div>
        )}
        {phase === "restarting" && (
          <p className="phone-restarting" role="status">
            <Icon icon={LoaderCircle} className="spin" />
            {t("Uygulama yeniden başlatılıyor… Birkaç saniye sürer, sayfa kendiliğinden yenilenir.")}
          </p>
        )}
        {phase === "failed" && (
          <div className="banner error" role="alert">
            <strong>{failText}</strong> {error}
          </div>
        )}
        {phase !== "failed" && error && (
          <div className="banner error" role="alert">
            {t("Kaydedilemedi: {hata}", { hata: error })}
          </div>
        )}
        <div className="modal-actions">
          {phase === "failed" ? (
            <button type="button" data-autofocus onClick={onClose}>
              {t("Kapat")}
            </button>
          ) : (
            <>
              <button type="button" data-autofocus disabled={busy} onClick={onClose}>
                {t("Vazgeç")}
              </button>
              <button type="button" className="primary" disabled={busy} onClick={() => void confirm()}>
                {phase === "restarting"
                  ? t("Yeniden başlatılıyor…")
                  : phase === "saving"
                    ? t("Kaydediliyor…")
                    : enable
                      ? t("Aç ve yeniden başlat")
                      : t("Kapat ve yeniden başlat")}
              </button>
            </>
          )}
        </div>
      </div>
    </Modal>
  );
}

function PhoneMode({
  settings,
  windows,
  onSettings,
}: {
  settings: SettingsResponse;
  windows: boolean;
  onSettings: Props["onSettings"];
}) {
  const { save, busy } = useSave(onSettings);
  const [asking, setAsking] = useState<boolean | null>(null);
  const card = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const wanted = settings.values.lan;
  const running = settings.running.lan;

  // Yeniden başlatmadan dönüldü: kart görünsün, odak başlığında, sonuç duyurulsun. İşaret hemen
  // silinir; etki yeniden çalışsa da bir daha bir şey yapmaz.
  useEffect(() => {
    const q = new URLSearchParams(window.location.hash.split("?")[1] ?? "");
    if (q.get("bolum") !== PHONE_SECTION) return;
    markPhoneSection(false);
    card.current?.scrollIntoView({ block: "start" });
    heading.current?.focus({ preventScroll: true });
    toast.ok(running ? t("Telefon modu açık: telefonla QR kodu okut.") : t("Telefon modu kapandı."));
  }, [running]);

  return (
    <section ref={card} className="card settings-card phone-card" aria-labelledby="telefon-baslik">
      <div className="section-head">
        <h2 id="telefon-baslik" ref={heading} tabIndex={-1}>
          {t("Telefon modu")}
        </h2>
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={wanted}
          disabled={busy || asking !== null || !settings.local}
          onChange={(e) => {
            const next = e.target.checked;
            // Çalışan sunucu zaten böyle (ör. bekleyen değişiklik geri alınıyor): yeniden başlatma yok.
            if (next === running) void save({ lan: next });
            else setAsking(next);
          }}
        />
        {t("Aynı Wi-Fi'deki telefon ve tabletler bu bilgisayardaki Toolia'yı kullanabilsin")}
      </label>
      <p className="muted small">
        {t("Açıkken uygulama yerel ağdan da erişilebilir; yalnızca burada gösterilen QR kodu okutan cihazlar bağlanır. Bağlantı yerel ağda şifresizdir (HTTP): yalnızca güvendiğin Wi-Fi'de aç, işin bitince kapat. Açıp kapatınca uygulama birkaç saniyeliğine yeniden başlar.")}
      </p>
      {running && <PhoneQr windows={windows} port={settings.running.port} />}
      {asking !== null && (
        <PhoneModeDialog
          enable={asking}
          windows={windows}
          port={settings.values.port}
          onSettings={onSettings}
          onClose={() => setAsking(null)}
        />
      )}
    </section>
  );
}

function VersionInfo({ data }: { data: EnginesResponse }) {
  const [info, setInfo] = useState<UpdateInfo | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const check = async () => {
    setChecking(true);
    setError(null);
    try {
      setInfo(await api.checkUpdate());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setChecking(false);
    }
  };
  return (
    <section className="card settings-card" aria-labelledby="surum-baslik">
      <div className="section-head">
        <h2 id="surum-baslik">{t("Sürüm")}</h2>
        <button type="button" onClick={() => void check()} disabled={checking}>
          <Icon icon={RefreshCw} size={17} className={checking ? "spin" : undefined} />
          {checking ? t("Denetleniyor…") : t("Güncellemeleri denetle")}
        </button>
      </div>
      <p>
        Toolia <strong>{data.version}</strong>
        {" "}
        {data.installed ? t("(masaüstü kurulumu)") : t("(geliştirme)")}
      </p>
      <p className="muted small">
        {t("Denetim yalnızca bu düğmeye basınca yapılır: GitHub'a tek bir istek gider, hiçbir dosya gönderilmez.")}
      </p>
      {error && <p className="error-text">{error}</p>}
      {info && (
        <p className={info.newer ? "warn-line" : "muted"}>
          {info.message}{" "}
          {info.newer && (
            <>
              <a href={info.url} target="_blank" rel="noreferrer">
                {t("Sürüm sayfası")}
              </a>
              {data.windows ? (
                <>
                  {t(": yeni paketi indir, içindeki")} <strong>{t("Kur")}</strong>
                  {t("'a çift tıkla (belgelerin ve ayarların korunur).")}
                </>
              ) : (
                <>
                  {t(": yeni paketi indir, ayıkla ve")} <code>./kur.sh</code>{" "}
                  {t("komutunu çalıştır (belgelerin ve ayarların korunur).")}
                </>
              )}
            </>
          )}
        </p>
      )}
    </section>
  );
}

/** Motorların durumu. Kurulum düğmeleri yalnız bilgisayarın kendisinden (`local`); sunucu telefondan kurulumu reddeder. */
export function EngineList({ data, local, onRefresh }: { data: EnginesResponse; local?: boolean; onRefresh: () => void }) {
  return (
    <div className="engine-list">
      {data.engines.map((e) => {
        const s = statusLabel(e);
        return (
          <article key={e.key} className="engine">
            <div className="engine-main">
              <div className="engine-name">
                <h3>{e.name}</h3>
                <span className="mono muted">{e.version ?? "—"}</span>
              </div>
              <span className={`chip small ${s.cls}`}>
                <Icon icon={STATUS_ICON[s.cls as keyof typeof STATUS_ICON]} size={14} />
                {s.text}
              </span>
            </div>
            <p className="muted">
              {e.key === "libreoffice" ? t("Word / Excel / PowerPoint → PDF ve Office biçim dönüştürme") : t(e.needed_for)}
            </p>
            {e.problems.map((p) => (
              <p key={p} className="warn-line">
                {p}
              </p>
            ))}
            {local && !e.available && e.key === "libreoffice" && data.windows && (
              <InstallLibreOffice onInstalled={onRefresh} />
            )}
            {local && !e.available && e.key === "latex" && data.windows && <InstallEngine engine="miktex" onInstalled={onRefresh} />}
            {!e.ok && e.install_hint && (
              <p className="engine-hint">
                {t("Elle kurulum:")} <code>{e.install_hint}</code>
              </p>
            )}
          </article>
        );
      })}
    </div>
  );
}

function PortSetting({ settings, onSettings }: { settings: SettingsResponse; onSettings: Props["onSettings"] }) {
  const [port, setPort] = useState(String(settings.values.port));
  const { save, busy } = useSave(onSettings);
  const n = Number(port);
  const valid = Number.isInteger(n) && n >= 1024 && n <= 65535;
  return (
    <form
      className="setting-row"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) void save({ port: n });
      }}
    >
      <div className="setting-label">
        <label htmlFor="ayar-port">{t("Port")}</label>
        <p className="muted small">
          {t("Şu an {port} portunda çalışıyor. Masaüstü uygulaması port doluysa kendiliğinden boş bir port seçer; değiştirmen genellikle gerekmez.", { port: settings.running.port })}
        </p>
      </div>
      <div className="setting-control">
        <span className="input-unit">
          <input
            id="ayar-port"
            className="input narrow"
            type="number"
            min={1024}
            max={65535}
            value={port}
            aria-invalid={!valid}
            onChange={(e) => setPort(e.target.value)}
          />{" "}
          <button type="submit" disabled={!valid || n === settings.values.port || busy || !settings.local}>
            {t("Kaydet")}
          </button>
        </span>
      </div>
    </form>
  );
}

function LanguageSetting() {
  const stored = storedLang();
  const options: [Lang | null, string][] = [
    [null, t("Sistem")],
    ["tr", "Türkçe"],
    ["en", "English"],
  ];
  return (
    <div className="setting-row">
      <div className="setting-label">
        <span className="setting-title">{t("Dil")}</span>
        <p className="muted small">{t("Seçince arayüz yeniden yüklenir. Sistem seçiliyse işletim sistemi diline uyar.")}</p>
      </div>
      <div className="setting-control">
        <div className="segmented seg-track" role="group" aria-label={t("Dil")}>
          {options.map(([value, label]) => (
            <button
              key={label}
              type="button"
              className={stored === value ? "on" : undefined}
              aria-pressed={stored === value}
              onClick={() => stored !== value && setLang(value)}
            >
              {value === null && <Icon icon={Monitor} size={16} />}
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function AppearanceSetting() {
  const stored = useStoredTheme();
  return (
    <section className="card settings-card" aria-labelledby="gorunum-baslik">
      <div className="section-head">
        <h2 id="gorunum-baslik">{t("Görünüm")}</h2>
      </div>
      <div className="setting-row">
        <div className="setting-label">
          <span className="setting-title">{t("Arayüz teması")}</span>
          <p className="muted small">
            {t("Sistem seçiliyse sistem/tarayıcı tercihini izler; bu tarayıcıda saklanır.")}
          </p>
        </div>
        <div className="setting-control">
          <div className="segmented seg-track" role="group" aria-label={t("Arayüz teması")}>
            <button type="button" className={stored === null ? "on" : undefined} aria-pressed={stored === null} onClick={resetTheme}>
              <Icon icon={Monitor} size={16} />
              {t("Sistem")}
            </button>
            <button type="button" className={stored === "light" ? "on" : undefined} aria-pressed={stored === "light"} onClick={() => setAppTheme("light")}>
              <Icon icon={Sun} size={16} />
              {t("Açık")}
            </button>
            <button type="button" className={stored === "dark" ? "on" : undefined} aria-pressed={stored === "dark"} onClick={() => setAppTheme("dark")}>
              <Icon icon={Moon} size={16} />
              {t("Koyu")}
            </button>
          </div>
        </div>
      </div>
      <LanguageSetting />
    </section>
  );
}

export default function Settings({ data, refreshing, onRefresh, settings, onSettings, onShowWelcome }: Props) {
  return (
    <div className="settings">
      <header className="screen-head">
        <h1>{t("Ayarlar")}</h1>
        <p>{t("Dosya saklama, görünüm, Markdown varsayılanları, telefon modu ve motorlar.")}</p>
      </header>
      {/* Yapışkan: port "Gelişmiş" altında değişse de uyarı ekranda kalır. */}
      {settings && <RestartLine settings={settings} />}
      {settings && <GeneralSettings key={settings.config_file} settings={settings} onSettings={onSettings} />}
      <AppearanceSetting />
      {settings && <PhoneMode settings={settings} windows={data?.windows ?? true} onSettings={onSettings} />}

      <section className="card settings-card" aria-labelledby="motorlar-baslik">
        <div className="section-head">
          <h2 id="motorlar-baslik">{t("Motorlar")}</h2>
          <button type="button" onClick={onRefresh} disabled={refreshing}>
            <Icon icon={RefreshCw} size={17} className={refreshing ? "spin" : undefined} />
            {refreshing ? t("Taranıyor…") : t("Yeniden tara")}
          </button>
        </div>
        {!data ? <p className="muted">{t("Yükleniyor…")}</p> : <EngineList data={data} local={settings?.local} onRefresh={onRefresh} />}
      </section>

      {data && <VersionInfo data={data} />}

      <p className="settings-more">
        <button type="button" className="link-button" onClick={onShowWelcome}>
          {t("Tanıtımı yeniden göster")}
        </button>
      </p>

      {data && (
        <details className="card advanced">
          <summary>
            <Icon icon={ChevronRight} className="advanced-caret" />
            {t("Gelişmiş")}
          </summary>
          <div className="advanced-body">
            {settings && <PortSetting settings={settings} onSettings={onSettings} />}
            <h3>{t("Klasörler")}</h3>
            <dl className="kv">
              <div>
                <dt>{t("Veri klasörü")}</dt>
                <dd className="mono">{data.data_dir}</dd>
              </div>
              <div>
                <dt>{t("Ayar dosyası")}</dt>
                <dd className="mono">{settings?.config_file ?? data.config_file ?? "—"}</dd>
              </div>
              <div>
                <dt>{t("Günlük dosyası")}</dt>
                <dd className="mono">{data.log_file}</dd>
              </div>
              {data.install_dir && (
                <div>
                  <dt>{t("Kurulum klasörü")}</dt>
                  <dd className="mono">{data.install_dir}</dd>
                </div>
              )}
            </dl>
            <h3>{t("Motor yolları")}</h3>
            <dl className="kv">
              {data.engines.map((e) => (
                <div key={e.key}>
                  <dt>{e.name}</dt>
                  <dd className="mono">{e.path ?? t("bulunamadı")}</dd>
                </div>
              ))}
            </dl>
            <h3>{t("Kütüphaneler")}</h3>
            <dl className="kv">
              {Object.entries(data.libraries).map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd className="mono">{v ?? t("yok")}</dd>
                </div>
              ))}
            </dl>
            <p className="muted small">
              {t("Sınırlar ve motor yolları gibi diğer ayarlar ayar dosyasından değiştirilebilir (açıklamalı örnek: config.example.toml).")}
            </p>
          </div>
        </details>
      )}
    </div>
  );
}
