import { Lock } from "lucide-react";
import { useState } from "react";
import { api, errorMessage, type FileMeta } from "../api";
import { t } from "../i18n";
import { passwords } from "../passwords";
import Icon from "./Icon";
import Modal from "./Modal";

interface Props {
  file: FileMeta;
  onDone: (ok: boolean) => void;
}

export default function PasswordDialog({ file, onDone }: Props) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.checkPassword(file.id, value);
      passwords.set(file.id, value);
      onDone(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={t("Şifreli PDF")} onClose={() => onDone(false)}>
      <form
        className="password-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="password-intro">
          <span className="tile">
            <Icon icon={Lock} />
          </span>
          <p>
            <strong className="break">{file.name}</strong>{" "}
            {t("şifreli. Açmak için şifresini gir. Şifre yalnızca bu sekmede tutulur, kaydedilmez.")}
          </p>
        </div>
        <input
          type="password"
          data-autofocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-label={t("Şifre")}
          className="input"
        />
        {error && <p className="error-text">{error}</p>}
        <div className="modal-actions">
          <button type="button" onClick={() => onDone(false)}>
            {t("Vazgeç")}
          </button>
          <button type="submit" className="primary" disabled={busy || !value}>
            {t("Aç")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
