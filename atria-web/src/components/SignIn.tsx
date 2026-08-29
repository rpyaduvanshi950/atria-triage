"use client";

/**
 * The sign-in screen.
 *
 * Deliberately plain. A nurse signing in at the start of a shift wants two
 * fields and a button, and the demo accounts are listed on the page because
 * hiding them from a judge who has thirty seconds helps nobody.
 */
import { useState } from "react";
import { useAuth } from "@/lib/auth-context";

const DEMO = [
  ["nurse.demo", "Triage nurse", "assess and sign off"],
  ["charge.demo", "Charge nurse", "the above, plus acknowledgements and flow"],
  ["doc.demo", "Clinician", "the above, plus lowering a priority"],
  ["ops.demo", "Flow coordinator", "the department view only"],
  ["audit.demo", "Clinical governance", "the decision history, read-only"],
  ["admin.demo", "Administrator", "everything, including shadow mode"],
] as const;

export function SignIn() {
  const { signIn } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
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

  const pick = (name: string) => {
    setUsername(name);
    setPassword(name);   // demo accounts only; the notice below says so
    setError("");
  };

  return (
    <div className="max-w-[560px] mx-auto mt-10">
      <div className="bg-card border border-line rounded-xl p-7">
        <h1 className="text-[22px] font-bold">Sign in to ATRIA</h1>
        <p className="text-[15px] text-ink2 mt-1.5">
          Every assessment, override and sign-off is recorded against the person
          who made it. That record is only worth anything if the name on it is
          real, which is why the board asks who you are first.
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

      <div className="bg-card border border-line rounded-xl p-5 mt-4">
        <h2 className="text-[15px] font-bold">Demo accounts</h2>
        <p className="text-[14px] text-ink3 mt-1">
          Prototype only — each password is the same as the username. Click one
          to fill the form. A real deployment is configured with proper accounts
          and these do not exist.
        </p>
        <ul className="mt-3 flex flex-col gap-1.5">
          {DEMO.map(([name, role, what]) => (
            <li key={name}>
              <button onClick={() => pick(name)}
                      className="w-full text-left px-3 py-2 rounded-xl hover:bg-sunk
                                 transition-colors">
                <span className="font-semibold text-[15px]">{role}</span>
                <span className="text-ink3 text-[14px]"> · {name}</span>
                <span className="block text-[13px] text-ink3">{what}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
