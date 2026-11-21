import { afterEach, describe, expect, it } from "vitest";
import { _setLangForTest, t } from "./i18n";

const en: Record<string, string> = Object.assign(
  {},
  ...Object.values(import.meta.glob<Record<string, string>>("./i18n/en/*.json", { eager: true, import: "default" })),
);

afterEach(() => _setLangForTest("tr"));

describe("t", () => {
  it("Türkçede metni olduğu gibi döndürür, değişkenleri doldurur", () => {
    expect(t("Tüm araçlar")).toBe("Tüm araçlar");
    expect(t("{n} resim yüklendi.", { n: 3 })).toBe("3 resim yüklendi.");
  });

  it("İngilizcede çevirir; tekil/çoğul n'e göre seçilir", () => {
    _setLangForTest("en");
    expect(t("Tüm araçlar")).toBe("All tools");
    expect(t("{n} resim yüklendi.", { n: 1 })).toBe("1 image uploaded.");
    expect(t("{n} resim yüklendi.", { n: 4 })).toBe("4 images uploaded.");
  });

  it("çevirisi olmayan metin Türkçe kalır ('|' içerse bile)", () => {
    _setLangForTest("en");
    expect(t("Çevrilmemiş | metin")).toBe("Çevrilmemiş | metin");
  });

  it("sayaçsız çevirideki '|' (Markdown tablosu) ayraç sayılmaz", () => {
    _setLangForTest("en");
    expect(t("| Hız | Konumun zamana göre değişimi | $v = \\frac{dx}{dt}$ |")).toBe(
      "| Velocity | Rate of change of position over time | $v = \\frac{dx}{dt}$ |",
    );
  });

  it("çeviriler anahtardaki değişkenleri korur", () => {
    const vars = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");
    for (const [tr, value] of Object.entries(en)) {
      const forms = tr.includes("{n}") ? value.split("|") : [value];
      for (const form of forms) expect(vars(form), tr).toBe(vars(tr));
    }
  });
});
