import { Download, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { useJob } from "../hooks";
import { t } from "../i18n";
import Icon from "./Icon";
import JobPanel from "./JobPanel";
import Modal from "./Modal";

type Installable = "libreoffice" | "miktex";

const INFO: Record<Installable, { name: string; body: string }> = {
  libreoffice: {
    name: "LibreOffice",
    body: "LibreOffice (ücretsiz, yaklaşık 350 MB) internetten indirilip kurulacak. Windows kurulum izni isteyebilir ve işlem birkaç dakika sürebilir.",
  },
  miktex: {
    name: "MiKTeX",
    body: "MiKTeX (ücretsiz LaTeX dağıtımı, temel kurulum yaklaşık 1 GB) internetten indirilip kurulacak. Belgelerin istediği paketler ilk derlemede ayrıca indirilir. Windows kurulum izni isteyebilir ve işlem birkaç dakika sürebilir.",
  },
};

/** LibreOffice ve MiKTeX uygulamaya gömülmez (yüzlerce MB). Kullanıcı onaylarsa winget ile
 * kurulur; Windows izin (UAC) penceresi açabilir. Bitince motorlar yeniden taranır (`onInstalled`). */
export function InstallEngine({ engine, onInstalled }: { engine: Installable; onInstalled: () => void }) {
  const job = useJob();
  const [confirming, setConfirming] = useState(false);
  const { name, body } = INFO[engine];

  useEffect(() => {
    if (job.job?.status === "bitti") onInstalled();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.job?.status]);

  const start = () => {
    setConfirming(false);
    void job.start({ type: "install_engine", engine });
  };

  return (
    <div className="install-engine">
      <button type="button" onClick={() => setConfirming(true)} disabled={job.running}>
        <Icon icon={job.running ? LoaderCircle : Download} className={job.running ? "spin" : undefined} />
        {job.running ? t("{ad} kuruluyor…", { ad: name }) : t("{ad}'i kur", { ad: name })}
      </button>
      <JobPanel job={job.job} error={job.error} />
      {confirming && (
        <Modal title={t("{ad} kurulsun mu?", { ad: name })} onClose={() => setConfirming(false)}>
          <p>{t(body)}</p>
          <div className="modal-actions">
            <button type="button" data-autofocus onClick={() => setConfirming(false)}>
              {t("Vazgeç")}
            </button>
            <button type="button" className="primary" onClick={start}>
              <Icon icon={Download} size={17} />
              {t("Kurulumu başlat")}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

export default function InstallLibreOffice({ onInstalled }: { onInstalled: () => void }) {
  return <InstallEngine engine="libreoffice" onInstalled={onInstalled} />;
}
