// Eksik İngilizce çevirileri listeler: kaynakta t("…") ile sarılıp src/i18n/en/*.json'da olmayan metinler.
// Kullanım (web/ içinden): node scripts/i18n-eksik.mjs [dosya ...]   (dosya verilmezse tüm src/)
// Yalnız düz dizge anahtarları görür (t("…") / t('…')); t(degisken) çağrılarını denetleyemez.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const dir = "src/i18n/en";
const en = Object.assign({}, ...readdirSync(dir).filter((f) => f.endsWith(".json")).map((f) => JSON.parse(readFileSync(join(dir, f), "utf8"))));

function walk(d) {
  return readdirSync(d, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(join(d, e.name)) : /\.tsx?$/.test(e.name) && !/\.test\./.test(e.name) && e.name !== "i18n.ts" ? [join(d, e.name)] : [],
  );
}

const files = process.argv.length > 2 ? process.argv.slice(2) : walk("src");
const re = /\bt\(\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g;
let missing = 0;
for (const file of files) {
  const src = readFileSync(file, "utf8");
  for (const m of src.matchAll(re)) {
    const key = JSON.parse(m[1].startsWith("'") ? `"${m[1].slice(1, -1).replace(/"/g, '\\"').replace(/\\'/g, "'")}"` : m[1]);
    if (!(key in en)) {
      missing++;
      console.log(`${file}: ${key}`);
    }
  }
}
console.log(missing ? `${missing} eksik çeviri` : "Eksik çeviri yok");
process.exitCode = missing ? 1 : 0;
