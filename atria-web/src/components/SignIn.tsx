"use client";

/**
 * The sign-in screen.
 *
 * Deliberately plain: a nurse starting a shift wants two fields and a button.
 *
 * The demo credentials are pre-filled rather than listed. A wall of accounts
 * was there so nobody had to hunt for a password, but it turned the first
 * screen of a clinical product into a table of test logins. Filling the fields
 * does the same job and takes a keystroke fewer.
 */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export function SignIn() {
  const { signIn } = useAuth();
  /*
   * Start empty and fill in only if the server says the seeded accounts are
   * actually live.
   *
   * These fields used to be pre-filled with nurse.demo unconditionally. On any
   * deployment that sets ATRIA_USERS that account does not exist, so pressing
   * Sign in without editing produced "incorrect username or password" — an
   * accurate message about credentials the page had put there itself. Offering
   * a login that cannot work is worse than offering none.
   */
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [demo, setDemo] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.mode()
      .then((m) => {
        if (cancelled || !m.demo_accounts) return;
        setDemo(true);
        setUsername("nurse.demo");
        setPassword("nurse.demo");
      })
      .catch(() => { /* the fields simply stay empty */ });
    return () => { cancelled = true; };
  }, []);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await signIn(username.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "could not sign in");
      setBusy(false);
    }
  };

  return (
    /*
     * Centred in whatever height is left below the banner. No calc(): the body
     * is a flex column, so this just takes the remaining space and centres in
     * it. A hardcoded subtraction was off by exactly the banner height, and
     * would go wrong again the moment the banner changed.
     */
    <div className="relative flex-1 flex items-center justify-center px-4 py-8">
      {/*
        * The board itself, behind the sign-in.
        *
        * Fixed rather than absolute so it covers the viewport instead of just
        * this box, and decorative rather than informative — aria-hidden, no alt
        * text, nothing here a person needs in order to sign in.
        *
        * Blurred and washed out on purpose. It is a screenshot of a working
        * screen; left sharp it reads as the real board with a dialog stuck on
        * top, and someone will try to click it.
        */}
      <div aria-hidden
           className="fixed inset-0 bg-[url('/bg.png')] bg-cover bg-center" />
      <div aria-hidden
           className="fixed inset-0 bg-page/75 backdrop-blur-[6px]" />

      <div className="relative w-full max-w-[440px] bg-card border border-line
                      rounded-xl p-7 shadow-[0_16px_48px_-12px_rgba(33,52,58,.35)]">
        <h1 className="text-[22px] font-bold">Sign in to ATRIA</h1>
        <p className="text-[15px] text-ink2 mt-1.5">
          Every assessment and sign-off is recorded against the person who made
          it, so the board asks who you are first.
        </p>
        {demo && (
          <p className="text-[14px] text-ink3 mt-2">
            Demo accounts are live on this deployment and the fields are filled
            in for you.
          </p>
        )}

        <form onSubmit={submit} className="mt-5 flex flex-col gap-3">
          <label className="text-[14px] font-semibold text-ink2">
            Username
            <input
              className="mt-1 w-full h-11 px-3 rounded-xl border border-line
                         bg-page text-[16px]"
              value={username} autoComplete="username" autoFocus
              onChange={(e) => setUsername(e.target.value)} />
          </label>
          <label className="text-[14px] font-semibold text-ink2">
            Password
            <input
              type="password"
              className="mt-1 w-full h-11 px-3 rounded-xl border border-line
                         bg-page text-[16px]"
              value={password} autoComplete="current-password"
              onChange={(e) => setPassword(e.target.value)} />
          </label>

          {error && (
            <p role="alert" className="text-[15px] text-danger font-semibold">
              {error}
            </p>
          )}

          <button type="submit" disabled={busy || !username || !password}
                  className="h-12 rounded-xl bg-brand text-white text-[16px]
                             font-semibold disabled:opacity-40">
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>

    </div>
  );
}
