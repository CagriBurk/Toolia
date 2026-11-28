import { useEffect, useState } from "react";
import type { EnginesResponse, FileMeta } from "../api";
import FilePicker, { FileRow, FilesCard, filesSummary } from "../components/FilePicker";
import { InstallEngine } from "../components/InstallLibreOffice";
import JobPanel, { ActionCard } from "../components/JobPanel";
import PageHeader from "../components/PageHeader";
import { useFiles, useJob } from "../hooks";
import { t } from "../i18n";
import { idsFrom, type Route } from "../router";
import { ACCEPT } from "../tools";

// Proje zip'i ya da ana .tex ile yanındakiler: resimler, PDF şekiller, .bib, veri dosyaları.
const KINDS: FileMeta["kind"][] = ["tex", "zip", "image", "pdf", "text", "office", "other"];

type TexEngine = "auto" | "pdflatex" | "xelatex" | "lualatex";
const ENGINES: [TexEngine, string][] = [
  ["auto", "Otomatik"],
  ["pdflatex", "pdfLaTeX"],
  ["xelatex", "XeLaTeX"],
  ["lualatex", "LuaLaTeX"],
];

interface Props {
  route: Route;
  engines: EnginesResponse | null;
  onEnginesChanged: () => void;
}

/** Ana dosya alanının ipucu: zip'te otomatik, tek .tex'te gereksiz. */
function mainHint(files: FileMeta[]): string {
  const texs = files.filter((f) => f.name.toLowerCase().endsWith(".tex"));
  if (files.some((f) => f.kind === "zip")) return t("Boş bırakılırsa \\documentclass içeren dosya (öncelik main.tex) seçilir.");
  if (texs.length > 1) return t("Birden çok .tex var; boş bırakılırsa \\documentclass içeren dosya seçilir.");
  return "";
}

export default function Latex({ route, engines, onEnginesChanged }: Props) {
  const initial = useFiles(idsFrom(route));
  const [files, setFiles] = useState<FileMeta[]>([]);
  const [engine, setEngine] = useState<TexEngine>("auto");
  const [main, setMain] = useState("");
  const [name, setName] = useState("");
  const job = useJob();
  const tex = engines?.engines.find((e) => e.key === "latex");
  const hasSource = files.some((f) => f.kind === "zip" || f.name.toLowerCase().endsWith(".tex"));
  const hint = mainHint(files);

  useEffect(() => {
    if (initial.files.length) setFiles(initial.files.filter((f) => KINDS.includes(f.kind)));
  }, [initial.files]);

  return (
    <>
      <PageHeader title="LaTeX → PDF" />
      <div className="tool-layout">
        <div className="tool-main">
          {tex && !tex.ok && (
            <div className="banner error">
              {tex.available ? tex.problems[0] : t("LaTeX (MiKTeX ya da TeX Live) bulunamadı; .tex dosyaları derlenemez.")}
              {engines?.windows && !tex.available ? (
                <InstallEngine engine="miktex" onInstalled={onEnginesChanged} />
              ) : (
                tex.install_hint && <code className="small">{tex.install_hint}</code>
              )}
            </div>
          )}
          <FilesCard
            count={files.length}
            hint={
              files.length > 0 &&
              !hasSource &&
              t("Derlenecek bir .tex dosyası ya da proje .zip'i ekle.")
            }
          >
            {files.length > 0 &&
              files.map((f) => <FileRow key={f.id} file={f} onRemove={() => setFiles((all) => all.filter((x) => x.id !== f.id))} />)}
            <FilePicker
              accept={ACCEPT.latex}
              kind={KINDS}
              compact={files.length > 0}
              title={
                files.length
                  ? t("Dosya ekle")
                  : t("Overleaf'ten indirdiğin proje .zip'ini ya da .tex dosyasını (yanındaki resim ve .bib dosyalarıyla) bırak")
              }
              onAdd={(added) => setFiles((f) => [...f, ...added])}
            />
          </FilesCard>
          <section className="card">
            <h2>{t("Seçenekler")}</h2>
            <label className="field">
              {t("Derleyici")}
              <select className="input" value={engine} onChange={(e) => setEngine(e.target.value as TexEngine)}>
                {ENGINES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {t(label)}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted small">
              {t("Otomatik: belgedeki % !TEX program satırına, yoksa paketlere bakar (fontspec → XeLaTeX). Overleaf'te Menü → Derleyici'de ne seçiliyse onu seçebilirsin.")}
            </p>
            {hint && (
              <label className="field">
                {t("Ana dosya")}
                <input className="input" placeholder={t("otomatik (ör. main.tex)")} value={main} onChange={(e) => setMain(e.target.value)} />
                <span className="muted small">{hint}</span>
              </label>
            )}
            <label className="field">
              {t("Çıktı adı")}
              <input className="input" placeholder={t("otomatik")} value={name} onChange={(e) => setName(e.target.value)} />
            </label>
          </section>
        </div>
        <aside className="tool-side">
          <ActionCard
            rows={[
              [t("Dosya"), filesSummary(files)],
              [t("Çıktı"), hasSource ? "1 PDF" : "—"],
            ]}
            note={t("Hata olsa da PDF üretilebiliyorsa üretilir ve hatalar uyarı olarak gösterilir. İlk derlemede eksik paketler indirileceği için biraz uzun sürebilir.")}
            label={job.running ? t("Derleniyor…") : t("PDF'e derle")}
            disabled={!hasSource || job.running || (tex !== undefined && !tex.ok)}
            busy={job.running}
            done={job.job?.status === "bitti"}
            onRun={() =>
              job.start({
                type: "tex_to_pdf",
                files: files.map((f) => f.id),
                engine,
                main: main.trim() || undefined,
                name: name.trim() || undefined,
              })
            }
          />
          <JobPanel job={job.job} error={job.error ?? initial.error} />
        </aside>
      </div>
    </>
  );
}
