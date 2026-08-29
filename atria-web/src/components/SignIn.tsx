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
import { useState } from "react";
import { useAuth } from "@/lib/auth-context";

export function SignIn() {
  const { signIn } = useAuth();
  /* Pre-filled for the prototype. A real deployment sets ATRIA_USERS, at which
     point these accounts do not exist and the fields start empty. */
  const [username, setUsername] = useState("nurse.demo");
  const [password, setPassword] = useState("nurse.demo");
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
    <div className="flex-1 flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-[440px] bg-card border border-line rounded-xl p-7">
        <h1 className="text-[22px] font-bold">Sign in to ATRIA</h1>
        <p className="text-[15px] text-ink2 mt-1.5">
          Every assessment and sign-off is recorded against the person who made
          it, so the board asks who you are first.
        </p>

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
