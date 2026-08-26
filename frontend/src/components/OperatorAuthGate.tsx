import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";
import { useEffect, useMemo, useState } from "react";

import { apiUrlFromDocument, ProofShieldApi } from "../api";
import type { OperatorIdentity, PublicAuthConfig } from "../types";
import { Icon } from "./Icon";

export function OperatorAuthGate({
  children,
}: {
  children: (values: {
    api: ProofShieldApi;
    operator: OperatorIdentity;
    signOut: () => Promise<void>;
  }) => React.ReactNode;
}) {
  const apiUrl = useMemo(() => apiUrlFromDocument(), []);
  const [authClient, setAuthClient] = useState<SupabaseClient | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [operator, setOperator] = useState<OperatorIdentity | null>(null);
  const [booting, setBooting] = useState(true);
  const [checkingOperator, setCheckingOperator] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let unsubscribe: (() => void) | undefined;
    async function boot() {
      try {
        const response = await fetch(`${apiUrl}/v1/auth/config`);
        if (!response.ok) throw new Error("The local API has no public Auth configuration.");
        const config = (await response.json()) as PublicAuthConfig;
        const client = createClient(
          config.supabase_url,
          config.supabase_publishable_key,
          {
            auth: {
              autoRefreshToken: true,
              detectSessionInUrl: false,
              persistSession: true,
            },
          },
        );
        const { data, error: sessionError } = await client.auth.getSession();
        if (sessionError) throw sessionError;
        if (!active) return;
        setAuthClient(client);
        setSession(data.session);
        const { data: listener } = client.auth.onAuthStateChange((_event, nextSession) => {
          if (active) setSession(nextSession);
        });
        unsubscribe = () => listener.subscription.unsubscribe();
      } catch (bootError) {
        if (active) {
          setError(bootError instanceof Error ? bootError.message : "Authentication could not start.");
        }
      } finally {
        if (active) setBooting(false);
      }
    }
    void boot();
    return () => {
      active = false;
      unsubscribe?.();
    };
  }, [apiUrl]);

  const api = useMemo(
    () => new ProofShieldApi(apiUrl, fetch, () => session?.access_token ?? null),
    [apiUrl, session?.access_token],
  );

  useEffect(() => {
    if (!session) {
      setOperator(null);
      return;
    }
    const controller = new AbortController();
    setCheckingOperator(true);
    api
      .getOperator(controller.signal)
      .then((identity) => {
        if (!controller.signal.aborted) {
          setOperator(identity);
          setError(null);
        }
      })
      .catch(async (identityError: unknown) => {
        if (controller.signal.aborted) return;
        setOperator(null);
        setError(
          identityError instanceof Error
            ? identityError.message
            : "This account is not an active ProofShield operator.",
        );
        await authClient?.auth.signOut();
      })
      .finally(() => {
        if (!controller.signal.aborted) setCheckingOperator(false);
      });
    return () => controller.abort();
  }, [api, authClient, session]);

  async function signOut() {
    setOperator(null);
    setError(null);
    const { error: signOutError } = await authClient?.auth.signOut() ?? {};
    if (signOutError) setError(signOutError.message);
  }

  if (booting || checkingOperator) {
    return <AuthStatus label="Verifying operator session…" />;
  }
  if (session && operator) return children({ api, operator, signOut });
  return <SignInForm client={authClient} error={error} onError={setError} />;
}

function SignInForm({
  client,
  error,
  onError,
}: {
  client: SupabaseClient | null;
  error: string | null;
  onError: (message: string | null) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!client) return;
    setSubmitting(true);
    onError(null);
    const { error: signInError } = await client.auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    if (signInError) onError(signInError.message);
    setPassword("");
    setSubmitting(false);
  }

  return (
    <main className="auth-shell">
      <form className="auth-card" onSubmit={(event) => void submit(event)}>
        <span className="auth-mark"><Icon name="shield" size={34} /></span>
        <p className="eyebrow">Named operator access</p>
        <h1>Sign in to ProofShield</h1>
        <p>
          Supabase verifies your account. The backend then checks the active
          operator registry before exposing any merchant case.
        </p>
        {error ? <div className="auth-error" role="alert"><Icon name="warning" size={17} /> {error}</div> : null}
        <label>
          Operator email
          <input
            autoComplete="email"
            onChange={(event) => setEmail(event.target.value)}
            placeholder="operator@merchant.com"
            required
            type="email"
            value={email}
          />
        </label>
        <label>
          Password
          <input
            autoComplete="current-password"
            minLength={8}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>
        <button
          className="primary-button full-button"
          disabled={!client || submitting}
          type="submit"
        >
          {submitting ? "Verifying…" : "Sign in securely"}
          <Icon name="arrow" size={17} />
        </button>
        <small>Accounts are provisioned by the merchant administrator; public signup is disabled.</small>
      </form>
    </main>
  );
}

function AuthStatus({ label }: { label: string }) {
  return (
    <main className="auth-shell">
      <div aria-busy="true" className="auth-card auth-status">
        <span className="auth-mark"><Icon name="shield" size={34} /></span>
        <strong>{label}</strong>
      </div>
    </main>
  );
}
