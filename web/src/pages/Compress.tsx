import { useEffect, useState } from "react";
import { formatSize, type FileMeta } from "../api";
import FilePicker, { FileRow, FilesCard, filesSummary } from "../components/FilePicker";
import JobPanel, { ActionCard } from "../components/JobPanel";
import PageHeader from "../components/PageHeader";
import PasswordDialog from "../components/PasswordDialog";
import { useFiles, useJob, useUnlockQueue } from "../hooks";
import { t } from "../i18n";
import { passwords } from "../passwords";
import { idsFrom, type Route } from "../router";
import { ACCEPT } from "../tools";

type Level = "kayipsiz" | "dengeli" | "guclu";

// quality / shrink: seviye kartındaki üç basamaklı gösterge (yalnızca sunum).
const LEVELS: { value: Level; label: string; hint: string; quality: number; shrink: number }[] = [
  {
    value: "kayipsiz",
    label: "Kayıpsız",
    hint: "Kalite hiç değişmez: gereksiz veri atılır, yazı tipleri küçültülür. Yazı ağırlıklı PDF'lerde en iyisi.",
    quality: 3,
    shrink: 1,
  },
  { value: "dengeli", label: "Dengeli", hint: "+ resimler 150 DPI. Taranmış belge ve paftalarda %50–80.", quality: 2, shrink: 2 },
  {
    value: "guclu",
    label: "Güçlü",
    hint: "+ resimler 100 DPI, düşük kalite. En küçük dosya; ekranda okumak ve e-postayla göndermek için.",
    quality: 1,
    shrink: 3,
  },
];

function Meter({ value }: { value: number }) {
  return (
    <span className="meter" aria-hidden="true">
      {[1, 2, 3].map((i) => (
        <span key={i} className={i <= value ? "on" : undefined} />
      ))}
    </span>
  );
}

export default function Compress({ route }: { route: Route }) {
  const initial = useFiles(idsFrom(route));
  const [files, setFiles] = useState<FileMeta[]>([]);
  const [level, setLevel] = useState<Level>("dengeli");
  const job = useJob();

  const unlock = useUnlockQueue({
    onUnlock: (accepted) => setFiles((curr) => [...curr, ...accepted]),
    onCancel: (cancelled) => setFiles((curr) => curr.filter((f) => f.id !== cancelled.id)),
  });
  const queueUnlock = unlock.queue;

  useEffect(() => {
    if (initial.files.length) queueUnlock(initial.files.filter((f) => f.kind === "pdf"));
  }, [initial.files, queueUnlock]);

  const total = files.reduce((n, f) => n + f.size, 0);
  const after = job.job?.status === "bitti" ? job.job.files.reduce((n, f) => n + f.size, 0) : null;
  const levelLabel = LEVELS.find((l) => l.value === level)?.label;

  return (
    <>
      <PageHeader title="Sıkıştır" />
      <div className="tool-layout">
        <div className="tool-main">
          <FilesCard count={files.length}>
            {files.length > 0 && (
              <ul className="file-list">
                {files.map((f) => (
                  <li key={f.id}>
                    <FileRow file={f} onRemove={() => setFiles((all) => all.filter((x) => x.id !== f.id))} />
                  </li>
                ))}
              </ul>
            )}
            <FilePicker
              accept={ACCEPT.pdf}
              kind="pdf"
              compact={files.length > 0}
              title={files.length ? t("PDF ekle") : t("Küçültülecek PDF'leri bırak")}
              onAdd={(added) => setFiles((f) => [...f, ...added])}
            />
          </FilesCard>
          <section className="card">
            <fieldset className="radio-cards">
              <legend>{t("Seviye")}</legend>
              {LEVELS.map((l) => (
                <label key={l.value} className={`radio-card${level === l.value ? " on" : ""}`}>
                  <input type="radio" name="level" checked={level === l.value} onChange={() => setLevel(l.value)} />
                  <span className="radio-card-head">
                    <strong>{t(l.label)}</strong>
                    <span className="radio-dot" aria-hidden="true" />
                  </span>
                  <span className="muted small">{t(l.hint)}</span>
                  <span className="level-meter">
                    <span aria-hidden="true">{t("Kalite")}</span>
                    <Meter value={l.quality} />
                    <span aria-hidden="true">{t("Küçültme")}</span>
                    <Meter value={l.shrink} />
                    <span className="sr-only">
                      {t("Kalite 3 üzerinden {q}, küçültme 3 üzerinden {s}.", { q: l.quality, s: l.shrink })}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>
          </section>
        </div>
        <aside className="tool-side">
          <ActionCard
            rows={[
              [t("Dosya"), filesSummary(files, "PDF")],
              [t("Seviye"), levelLabel && t(levelLabel)],
            ]}
            note={t("Sonuç orijinalden büyük çıkarsa orijinal korunur. Metin ve bağlantılar korunur; yalnızca resimler yeniden sıkıştırılır.")}
            label={files.length > 1 ? t("{n} dosyayı sıkıştır", { n: files.length }) : t("Sıkıştır")}
            disabled={!files.length || job.running}
            busy={job.running}
            done={job.job?.status === "bitti"}
            onRun={() =>
              void job.start({
                type: "compress",
                files: files.map((f) => f.id),
                level,
                passwords: passwords.forFiles(files.map((f) => f.id)),
              })
            }
          />
          <JobPanel
            job={job.job}
            error={job.error ?? initial.error}
            zipName="kucultulmus"
            summary={
              after !== null &&
              total > 0 && (
                <span className="savings-summary">
                  <span>
                    {formatSize(total)} → <strong>{formatSize(after)}</strong>
                    {after < total && (
                      <span className="chip ok small savings-pct">{t("-%{p}", { p: Math.round((1 - after / total) * 100) })}</span>
                    )}
                  </span>
                  <span className="savings-bar" aria-hidden="true">
                    <span style={{ width: `${Math.min(100, Math.max(6, Math.round((after / total) * 100)))}%` }} />
                  </span>
                </span>
              )
            }
          />
        </aside>
      </div>
      {unlock.locked && <PasswordDialog file={unlock.locked} onDone={unlock.onDone} />}
    </>
  );
}
