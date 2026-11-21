import { useEffect, useState } from "react";
import type { FileMeta } from "../api";
import FilePicker, { FileRow, FilesCard, fileSummary } from "../components/FilePicker";
import JobPanel, { ActionCard } from "../components/JobPanel";
import PageHeader from "../components/PageHeader";
import PasswordDialog from "../components/PasswordDialog";
import { useFiles, useJob, useUnlockQueue } from "../hooks";
import { t } from "../i18n";
import { passwords } from "../passwords";
import { idsFrom, type Route } from "../router";
import { ACCEPT } from "../tools";

type Mode = "her" | "n" | "aralik" | "yer-imi";

const MODES: { value: Mode; label: string; hint: string }[] = [
  { value: "her", label: "Her sayfa ayrı", hint: "Her sayfa ayrı bir PDF olur." },
  { value: "n", label: "Her N sayfada bir", hint: "Eşit büyüklükte parçalar." },
  { value: "aralik", label: "Aralıklara göre", hint: "Virgülle ayrılmış her aralık bir dosya: 1-3, 4-10, 11-" },
  { value: "yer-imi", label: "Yer imlerine göre", hint: "Üst seviye her bölüm ayrı dosya (bölüm adıyla)." },
];

export default function Split({ route }: { route: Route }) {
  const initial = useFiles(idsFrom(route));
  const [file, setFile] = useState<FileMeta | null>(null);
  const [mode, setMode] = useState<Mode>("her");
  const [every, setEvery] = useState(2);
  const [spec, setSpec] = useState("");
  const job = useJob();

  const unlock = useUnlockQueue({
    onUnlock: ([accepted]) => {
      if (accepted) setFile(accepted);
    },
    onCancel: (cancelled) => {
      setFile((curr) => (curr?.id === cancelled.id ? null : curr));
    },
  });
  const queueUnlock = unlock.queue;

  useEffect(() => {
    const pdf = initial.files.find((f) => f.kind === "pdf");
    if (pdf) queueUnlock([pdf]);
  }, [initial.files, queueUnlock]);

  const pages = file?.page_count ?? 0;
  const modeLabel = MODES.find((m) => m.value === mode)?.label;
  const parts = mode === "her" ? pages : mode === "n" && every > 0 ? Math.ceil(pages / every) : null;

  return (
    <>
      <PageHeader title="Böl" />
      <div className="tool-layout">
        <div className="tool-main">
          <FilesCard title={t("Dosya")}>
            {file ? (
              <FileRow file={file} onRemove={() => (setFile(null), job.reset())} />
            ) : (
              <FilePicker accept={ACCEPT.pdf} kind="pdf" multiple={false} title={t("Bölünecek PDF'i bırak")} onAdd={([f]) => setFile(f)} />
            )}
          </FilesCard>
          <section className="card">
            <fieldset className="radio-cards">
              <legend>{t("Nasıl bölünsün?")}</legend>
              {MODES.map((m) => (
                <label key={m.value} className={`radio-card${mode === m.value ? " on" : ""}`}>
                  <input type="radio" name="mode" value={m.value} checked={mode === m.value} onChange={() => setMode(m.value)} />
                  <span className="radio-card-head">
                    <strong>{t(m.label)}</strong>
                    <span className="radio-dot" aria-hidden="true" />
                  </span>
                  <span className="muted small">{t(m.hint)}</span>
                </label>
              ))}
            </fieldset>
            {mode === "n" && (
              <label className="field inline">
                {t("Kaç sayfada bir")}
                <input className="input narrow" type="number" min={1} value={every} onChange={(e) => setEvery(Number(e.target.value))} />
              </label>
            )}
            {mode === "aralik" && (
              <label className="field">
                {t("Aralıklar")}
                <input className="input" placeholder="1-3, 4-10, 11-" value={spec} onChange={(e) => setSpec(e.target.value)} />
              </label>
            )}
          </section>
        </div>
        <aside className="tool-side">
          <ActionCard
            rows={[
              [t("Dosya"), fileSummary(file)],
              [t("Yöntem"), modeLabel && t(modeLabel)],
              ...(parts ? ([[t("Çıktı"), t("{n} dosya", { n: parts })]] as [string, string][]) : []),
            ]}
            label={parts ? t("Böl ({n} dosya)", { n: parts }) : t("Böl")}
            disabled={!file || job.running || (mode === "aralik" && !spec.trim())}
            busy={job.running}
            done={job.job?.status === "bitti"}
            onRun={() =>
              file &&
              job.start({
                type: "split",
                file: file.id,
                mode,
                every,
                spec,
                passwords: passwords.forFiles([file.id]),
              })
            }
          />
          <JobPanel job={job.job} error={job.error ?? initial.error} zipName={file ? `${file.name.replace(/\.pdf$/i, "")}_parcalar` : undefined} />
        </aside>
      </div>
      {unlock.locked && <PasswordDialog file={unlock.locked} onDone={unlock.onDone} />}
    </>
  );
}
