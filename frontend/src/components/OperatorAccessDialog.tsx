import { useEffect, useRef, useState } from "react";

import { Icon } from "./Icon";

export function OperatorAccessDialog({
  open,
  onClose,
  onUnlock,
}: {
  open: boolean;
  onClose: () => void;
  onUnlock: (secret: string) => void;
}) {
  const [secret, setSecret] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open]);

  if (!open) return null;

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (secret.length < 32) return;
    onUnlock(secret);
    setSecret("");
  }

  return (
    <div
      aria-labelledby="operator-dialog-title"
      aria-modal="true"
      className="modal-backdrop"
      role="dialog"
    >
      <form className="operator-dialog" onSubmit={submit}>
        <button
          aria-label="Close operator access dialog"
          className="icon-button dialog-close"
          onClick={onClose}
          type="button"
        >
          <Icon name="x" />
        </button>
        <span className="dialog-lock"><Icon name="lock" size={28} /></span>
        <p className="eyebrow">Protected action</p>
        <h2 id="operator-dialog-title">Unlock operator controls</h2>
        <p>
          Enter the local backend operator secret to approve or reject a draft.
          It stays in memory only and is cleared when this page closes.
        </p>
        <label>
          Operator secret
          <input
            autoComplete="off"
            minLength={32}
            onChange={(event) => setSecret(event.target.value)}
            placeholder="At least 32 characters"
            ref={inputRef}
            type="password"
            value={secret}
          />
        </label>
        <button
          className="primary-button full-button"
          disabled={secret.length < 32}
          type="submit"
        >
          Unlock for this session <Icon name="arrow" size={17} />
        </button>
        <small>No credential is written to local storage or sent to Supabase.</small>
      </form>
    </div>
  );
}
