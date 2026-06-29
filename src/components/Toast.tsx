import { useEffect } from "react";
import { useToastStore } from "../store/toast";
import "./Toast.css";

const AUTO_DISMISS_MS = 5000;

export function ToastContainer() {
  const { toasts, removeToast } = useToastStore();

  return (
    <div className="toast-container" aria-live="polite" aria-atomic="false">
      {toasts.map((t) => (
        <ToastItem key={t.id} id={t.id} message={t.message} onDismiss={removeToast} />
      ))}
    </div>
  );
}

interface ToastItemProps {
  id: number;
  message: string;
  onDismiss: (id: number) => void;
}

function ToastItem({ id, message, onDismiss }: ToastItemProps) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(id), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [id, onDismiss]);

  return (
    <div className="toast" role="status">
      <span className="toast__message">{message}</span>
      <button
        className="toast__close"
        aria-label="Dismiss"
        onClick={() => onDismiss(id)}
      >
        ×
      </button>
    </div>
  );
}
