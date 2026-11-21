import { ArrowLeftRight, ArrowRight, ChevronRight, FileText, Sparkles, Star, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { EnginesResponse, FileMeta } from "../api";
import DropZone from "../components/DropZone";
import Icon from "../components/Icon";
import RecentFiles from "../components/RecentFiles";
import { toggleFavorite, useFavorites } from "../favorites";
import { useUpload } from "../hooks";
import { t } from "../i18n";
import { navigate } from "../router";
import { commonConvertTargets, GROUP_TONE, GROUPS, TOOLS, type ToolGroup } from "../tools";

type Query = Record<string, string | string[]>;
type Dropped = Pick<FileMeta, "id" | "name" | "kind">;

/** Bırakılan dosyalar için yapılacak iş: doğrudan bir araca git, PDF ile başka biçim arasında
 * seçtir ya da birlikte işlenemediklerini söyle. */
export type HomeRoute =
  | { type: "go"; path: string; query?: Query }
  | { type: "choose"; pdfPath: string; ids: string[]; targets: string[]; what: string }
  | { type: "error"; message: string };

/** Bırakılan dosyaların türüne göre en uygun araç. Hepsi resim ya da hepsi Office belgesiyse ve
 * ortak bir dönüştürme hedefi varsa PDF ile başka biçim arasında seçim sorulur. */
export function homeRoute(files: Dropped[]): HomeRoute {
  const md = files.find((f) => f.kind === "markdown");
  if (md) {
    const ek = files.filter((f) => f.id !== md.id).map((f) => f.id);
    return { type: "go", path: "md", query: ek.length ? { dosya: md.id, ek } : { dosya: md.id } };
  }
  const ids = files.map((f) => f.id);
  const all = (...kinds: FileMeta["kind"][]) => files.every((f) => kinds.includes(f.kind));
  if (all("pdf")) {
    return ids.length === 1 ? { type: "go", path: `duzenle/${ids[0]}` } : { type: "go", path: "birlestir", query: { dosya: ids } };
  }
  const pdfPath = all("image") ? "resimden" : all("office", "html", "text") ? "office" : null;
  if (!pdfPath) return { type: "error", message: t("Bu dosya türleri birlikte işlenemiyor. PDF, resim, Office belgesi ya da Markdown bırak.") };
  // HTML / TXT'nin dönüştürme hedefi yok; yalnız saf resim ya da saf Office seçimi sorulur.
  const targets = pdfPath === "resimden" || all("office") ? commonConvertTargets(files.map((f) => f.name)) : [];
  if (!targets.length) return { type: "go", path: pdfPath, query: { dosya: ids } };
  const n = files.length;
  const what = pdfPath === "resimden" ? t("{n} resim yüklendi.", { n }) : n === 1 ? t("Belge yüklendi.") : t("{n} belge yüklendi.", { n });
  return { type: "choose", pdfPath, ids, targets, what };
}

/** Hedeflerin kısa adları: [".jpg", ".png"] → "JPG, PNG". */
export function targetNames(targets: string[]): string {
  return targets.map((t) => t.replace(/^\./, "").toUpperCase()).join(", ");
}

// `homeRoute`un sırasıyla aynı: Markdown varsa yanındakiler eki sayılır.
const ROUTES: [string, string][] = [
  ["Tek PDF", "düzenleyicide açılır"],
  ["Birden çok PDF", "birleştirilir"],
  ["Resimler", "tek PDF ya da başka biçim"],
  ["Markdown (+ resimleri)", "PDF'e dönüşür"],
  ["Word, Excel, PowerPoint", "PDF ya da başka biçim"],
  ["HTML, TXT", "PDF olur"],
];

export default function Home({ engines, onSearch }: { engines: EnginesResponse | null; onSearch: () => void }) {
  const { upload, uploading, progress, error } = useUpload();
  const [notice, setNotice] = useState<string | null>(null);
  const [choice, setChoice] = useState<Extract<HomeRoute, { type: "choose" }> | null>(null);
  const [uploads, setUploads] = useState(0);
  const [groupFilter, setGroupFilter] = useState<ToolGroup | "all">("all");
  const favorites = useFavorites();
  const hero = useRef<HTMLElement>(null);
  const toPdf = useRef<HTMLButtonElement>(null);
  const favTools = TOOLS.filter((t) => favorites.includes(t.id));
  const visibleGroups = groupFilter === "all" ? GROUPS : GROUPS.filter((g) => g === groupFilter);

  // "/" araç aramasını (komut paleti) açar; yazı alanında ya da açık pencerede değilken.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "/" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        if (document.querySelector("dialog[open], .modal")) return;
        const target = e.target as HTMLElement | null;
        const tag = target?.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target?.isContentEditable) {
          return;
        }
        e.preventDefault();
        onSearch();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onSearch]);

  const closeChoice = useCallback(() => {
    // Odak karttaysa kaybolmasın: bırakma alanına döner.
    const inside = hero.current?.querySelector(".home-choice")?.contains(document.activeElement);
    setChoice(null);
    if (inside) hero.current?.querySelector<HTMLElement>(".dropzone")?.focus();
  }, []);

  // Seçim kartı: odak birincil düğmede (Enter = PDF'e çevir); Esc kapatır.
  useEffect(() => {
    if (!choice) return;
    toPdf.current?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || document.querySelector("dialog[open], .modal")) return;
      e.preventDefault();
      closeChoice();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [choice, closeChoice]);

  const missing = (keys: string[] = []) =>
    engines ? engines.engines.filter((e) => keys.includes(e.key) && !e.ok).map((e) => e.name) : [];

  const onFiles = async (files: File[]) => {
    setNotice(null);
    setChoice(null);
    const metas = await upload(files);
    if (!metas.length) return;
    setUploads((n) => n + 1);
    const next = homeRoute(metas);
    if (next.type === "go") navigate(next.path, next.query);
    else if (next.type === "choose") setChoice(next);
    else setNotice(next.message);
  };

  return (
    <div className="home">
      <div className="home-top">
        <section ref={hero} className="card home-hero" aria-labelledby="home-baslik">
          <div>
            <h1 id="home-baslik">{t("Dönüştür veya düzenle")}</h1>
            <p className="home-lead">{t("Dosyayı bırak, uygun araç kendiliğinden açılsın. Hiçbir dosya bu bilgisayardan çıkmaz.")}</p>
          </div>
          <DropZone
            hero
            onFiles={onFiles}
            disabled={uploading}
            title={uploading ? t("Yükleniyor… %{p}", { p: Math.round((progress ?? 0) * 100) }) : t("Dosyayı buraya bırak")}
            hint={t("PDF, Word, Excel, PowerPoint, Markdown ya da fotoğraf · birden çok dosya olur")}
          />
          {choice && (
            <section className="home-choice" aria-labelledby="home-secim">
              <div className="home-choice-head">
                <div>
                  <h2 id="home-secim">{t("Ne yapmak istiyorsun?")}</h2>
                  <p className="muted small">{choice.what}</p>
                </div>
                <button type="button" className="icon-button" aria-label={t("Kapat (Esc)")} title={t("Kapat (Esc)")} onClick={closeChoice}>
                  <Icon icon={X} />
                </button>
              </div>
              <div className="home-choice-actions">
                <button
                  ref={toPdf}
                  type="button"
                  className="primary"
                  onClick={() => navigate(choice.pdfPath, { dosya: choice.ids })}
                >
                  <Icon icon={FileText} />
                  {t("PDF'e çevir")}
                </button>
                <button
                  type="button"
                  aria-describedby="home-secim-hedef"
                  onClick={() => navigate("donustur", { dosya: choice.ids })}
                >
                  <Icon icon={ArrowLeftRight} />
                  {t("Başka biçime dönüştür")}
                </button>
              </div>
              <div id="home-secim-hedef" className="home-choice-quick">
                <span className="muted small">{t("Hızlı hedef:")}</span>
                {choice.targets.map((target) => (
                  <button
                    key={target}
                    type="button"
                    className="small"
                    onClick={() => navigate("donustur", { dosya: choice.ids, hedef: target })}
                  >
                    {target.replace(/^\./, "").toUpperCase()}
                  </button>
                ))}
              </div>
            </section>
          )}
          {(error || notice) && (
            <div className="banner error" role="alert">
              {error ?? notice}
            </div>
          )}
          <details className="route-drawer">
            <summary>
              <Icon icon={Sparkles} size={15} className="route-drawer-icon" />
              <span>
                <strong>{t("Akıllı yönlendirme:")}</strong> {t("PDF, resim, Office ya da Markdown bırakınca uygun araç açılır")}
              </span>
              <Icon icon={ChevronRight} size={15} className="route-drawer-caret" />
            </summary>
            <ul className="route-list" aria-label={t("Bırakınca ne olur")}>
              {ROUTES.map(([what, result]) => (
                <li key={what} className="route">
                  <b>{t(what)}</b> <Icon icon={ArrowRight} size={14} /> {t(result)}
                </li>
              ))}
            </ul>
          </details>
        </section>
        <RecentFiles retentionHours={engines?.retention_hours} refreshKey={uploads} />
      </div>

      <section aria-labelledby="home-araclar">
        <div className="home-tools-head">
          <div>
            <h2 id="home-araclar">{t("Tüm araçlar")}</h2>
            <p className="muted">
              {t("{tools} araç, {groups} başlıkta. Birine tıkla ya da dosyanı yukarı bırak.", { tools: TOOLS.length, groups: GROUPS.length })}
            </p>
          </div>
          <div className="home-tools-controls">
            <div className="segmented seg-track home-filter" role="group" aria-label={t("Kategori süzgeci")}>
              <button
                type="button"
                className={groupFilter === "all" ? "on" : undefined}
                aria-pressed={groupFilter === "all"}
                onClick={() => setGroupFilter("all")}
              >
                {t("Tümü")}
              </button>
              {GROUPS.map((g) => (
                <button
                  key={g}
                  type="button"
                  className={groupFilter === g ? "on" : undefined}
                  aria-pressed={groupFilter === g}
                  onClick={() => setGroupFilter(g)}
                >
                  {g === "Optimize ve güvenlik" ? t("Optimize") : t(g)}
                </button>
              ))}
            </div>
            <p className="home-keys">
              <kbd>Ctrl</kbd>
              <kbd>K</kbd> {t("ya da")} <kbd>/</kbd>
            </p>
          </div>
        </div>

        {favTools.length > 0 && groupFilter === "all" && (
          <div className="fav-strip" aria-label={t("Sık kullanılan araçlar")}>
            <span className="fav-strip-label">
              <Icon icon={Star} size={14} />
              {t("Sık kullanılanlar")}
            </span>
            <div className="fav-strip-items">
              {favTools.map((tool) => (
                <a key={tool.id} className="fav-pill" href={`#/${tool.route}`}>
                  <span className={`tile sm ${tool.tone}`}>
                    <Icon icon={tool.icon} size={15} />
                  </span>
                  <span>{t(tool.title)}</span>
                </a>
              ))}
            </div>
          </div>
        )}

        <div className={`tool-groups${visibleGroups.length === 1 ? " single-group" : ""}`}>
          {visibleGroups.map((group) => {
            const tools = TOOLS.filter((t) => t.group === group);
            const tone = GROUP_TONE[group];
            const featured = group === "Dönüştür" || visibleGroups.length === 1;
            return (
              <div key={group} className={`card tool-group${featured ? " featured" : ""}`}>
                <div className="tool-group-head">
                  <span className={`dot ${tone}`} aria-hidden="true" />
                  <h3 id={`grup-${tone}`}>{t(group)}</h3>
                  <span className="tool-group-count" aria-hidden="true">
                    {tools.length}
                  </span>
                </div>
                <ul className={`tool-list${featured ? " featured-grid" : ""}`} aria-labelledby={`grup-${tone}`}>
                  {tools.map((tool) => {
                    const lacking = missing(tool.needs);
                    const isFav = favorites.includes(tool.id);
                    const title = t(tool.title);
                    return (
                      <li key={tool.id} className={`tool-item${tool.id === "convert" ? " tool-card-lead" : ""}`}>
                        <a className="tool-card active" href={`#/${tool.route}`}>
                          <span className={`tile ${tool.tone}`}>
                            <Icon icon={tool.icon} size={19} strokeWidth={1.9} />
                          </span>
                          <span className="tool-card-text">
                            <span className="tool-card-title">
                              {title}
                              {tool.id === "convert" && <span className="chip accent small">{t("Tümü tek yerde")}</span>}
                            </span>
                            <span className="tool-card-desc">{t(tool.description)}</span>
                            {lacking.length > 0 && <span className="chip warn small">{t("Eksik: {list}", { list: lacking.join(", ") })}</span>}
                          </span>
                          <Icon icon={ChevronRight} size={16} className="go" />
                        </a>
                        <button
                          type="button"
                          className={`tool-fav${isFav ? " on" : ""}`}
                          aria-label={isFav ? t("{tool} sık kullanılanlardan çıkar", { tool: title }) : t("{tool} sık kullanılanlara ekle", { tool: title })}
                          aria-pressed={isFav}
                          title={isFav ? t("Sık kullanılanlardan çıkar") : t("Sık kullanılanlara ekle")}
                          onClick={() => toggleFavorite(tool.id)}
                        >
                          <Icon icon={Star} size={15} fill={isFav ? "currentColor" : "none"} />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
      </section>

      <footer className="home-foot">
        <span>Toolia{engines ? ` ${engines.version}` : ""}</span>
        <span>{t("Dosyaların bu bilgisayarda kalır · kayıt yok, reklam yok")}</span>
      </footer>
    </div>
  );
}
