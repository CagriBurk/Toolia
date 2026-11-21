/** Arayüz dili. Kaynak dil Türkçe: koddaki Türkçe metnin kendisi anahtardır (`t("Kapat")`),
 * `i18n/en/*.json` Türkçe → İngilizce eşlemesidir (sayfa başına bir dosya; hepsi birleştirilir).
 * Çevirisi olmayan metin Türkçe görünür. Eksik çeviri denetimi: `node scripts/i18n-eksik.mjs`.
 *
 * Değişkenler `{ad}` ile yazılır: `t("{n} resim yüklendi.", { n })`. İngilizcede tekil/çoğul
 * ayrımı gerekiyorsa çeviri `|` ile iki biçim verir ("{n} image uploaded.|{n} images uploaded.");
 * `n` 1 ise ilki, değilse ikincisi seçilir.
 *
 * Dil değişince sayfa yeniden yüklenir; bu yüzden `t` sıradan bir fonksiyondur, bileşen dışında da
 * (araç listesi, hata iletileri) kullanılabilir. */
export type Lang = "tr" | "en";

const KEY = "toolia-dil";
const en: Record<string, string> = Object.assign(
  {},
  ...Object.values(import.meta.glob<Record<string, string>>("./i18n/en/*.json", { eager: true, import: "default" })),
);
const DICT: Record<Lang, Record<string, string> | null> = { tr: null, en };

export function storedLang(): Lang | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "tr" || v === "en" ? v : null;
  } catch {
    return null; // depolama kapalı: sistem dili
  }
}

function detectLang(): Lang {
  // Birim testleri Türkçe metinleri sınar; jsdom'un dili "en-US".
  if (import.meta.env.MODE === "test") return "tr";
  const stored = storedLang();
  if (stored) return stored;
  const nav = typeof navigator !== "undefined" ? navigator.language : "tr";
  return nav.toLowerCase().startsWith("tr") ? "tr" : "en";
}

let lang: Lang = detectLang();

export function currentLang(): Lang {
  return lang;
}

/** Tarih/sayı biçimlendirmesi için yerel ayar (`toLocaleString(locale())`). */
export function locale(): string {
  return lang === "en" ? "en-US" : "tr-TR";
}

/** Testler için: dili sayfa yüklemeden değiştirir. */
export function _setLangForTest(l: Lang): void {
  lang = l;
}

/** Seçimi saklar ve arayüzü yeni dille yeniden yükler. `null`: sistem diline dön. */
export function setLang(l: Lang | null): void {
  try {
    if (l) window.localStorage.setItem(KEY, l);
    else window.localStorage.removeItem(KEY);
  } catch {
    // Saklanamadı: yine de bu oturumda geçerli olsun.
    if (l) lang = l;
  }
  window.location.reload();
}

export function t(text: string, vars?: Record<string, string | number>): string {
  const translated = DICT[lang]?.[text];
  let out = translated ?? text;
  // `|` yalnız sayaçlı metinde (n verilmişse) tekil/çoğul ayracıdır; Markdown tablo satırları da `|` içerir.
  if (translated?.includes("|") && vars && "n" in vars) {
    const [one, other] = out.split("|");
    out = vars && Number(vars.n) === 1 ? one : other;
  }
  if (vars) out = out.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
  return out;
}
