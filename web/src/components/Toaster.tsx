import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import { dismiss, useToasts, type ToastKind } from "../toast";
import { t } from "../i18n";
import Icon from "./Icon";

const KIND_ICON = { ok: CircleCheck, info: Info, error: CircleAlert } satisfies Record<ToastKind, unknown>;

/** Bildirimlerin gösterildiği köşe. Ekran okuyucu: hatalar `alert`, diğerleri `status`. */
export default function Toaster() {
  const toasts = useToasts();
  return (
    <div className="toaster" aria-live="polite">
      {toasts.map((item) => (
        <div key={item.id} className={`toast ${item.kind}`} role={item.kind === "error" ? "alert" : "status"}>
          <Icon icon={KIND_ICON[item.kind]} className="toast-icon" />
          <span className="toast-text">
            {item.text}
            {item.count > 1 && <span className="toast-count"> ×{item.count}</span>}
          </span>
          <button type="button" className="icon-button" aria-label={t("Bildirimi kapat")} onClick={() => dismiss(item.id)}>
            <Icon icon={X} size={17} />
          </button>
        </div>
      ))}
    </div>
  );
}
