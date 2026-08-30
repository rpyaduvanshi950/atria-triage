"use client";

/**
 * Who is at the board.
 *
 * One field and a button. A triage nurse starting a shift should not be typing
 * a password into a prototype, so this asks for a name or an employee ID and
 * takes them at their word.
 *
 * What that gives up is real, and the page says so rather than implying a
 * check it does not perform: the name is recorded against every decision, and
 * the record marks it as self-declared. The token carries the nurse role only,
 * so nobody can name their way into an administrator's permissions.
 */
import { useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export function SignIn() {
  const { signIn } = useAuth();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      await signIn(name.trim());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in.");
      setBusy(false);
    }
  };

  return (
    <div className="relative flex-1 flex items-center justify-center px-4 py-8">
      {/* The board itself, behind the sign-in. Decorative, and deliberately
          blurred: left sharp it reads as the real board with a dialog stuck on
          top and someone will try to click it. */}
      <div aria-hidden
           className="fixed inset-0 bg-[url('/bg.png')] bg-cover bg-center" />
      <div aria-hidden
           className="fixed inset-0 bg-page/75 backdrop-blur-[6px]" />

      <div className="relative w-full max-w-[440px] bg-card border border-line
                      rounded-xl p-7 shadow-[0_16px_48px_-12px_rgba(33,52,58,.35)]">
        <h1 className="text-[22px] font-bold">Start your shift</h1>
        <p className="text-[15px] text-ink2 mt-1.5 leading-relaxed">
          Every assessment and sign-off is recorded against the name you give,
          so the board asks who you are first.
        </p>

        <form onSubmit={submit} className="mt-5 flex flex-col gap-3">
          <label className="text-[14px] font-semibold text-ink2">
            Your name or employee ID
            <input
              className="mt-1 w-full h-12 px-3 rounded-xl border border-line
                         bg-page text-[16px]"
              value={name} autoFocus autoComplete="name"
              placeholder="A. Rahman, or 40817"
              onChange={(e) => setName(e.target.value)} />
          </label>

          {error && (
            <p role="alert" className="text-[15px] text-danger font-semibold">
              {error}
            </p>
          )}

          <button type="submit" disabled={busy || !name.trim()}
                  className="h-12 rounded-xl bg-brand text-white text-[16px]
                             font-semibold disabled:opacity-40">
            {busy ? "Starting…" : "Sign in"}
          </button>
        </form>

        <p className="text-[13px] text-ink3 mt-4 leading-relaxed">
          Prototype: the name is not checked against anything, and the record
          marks it as self-declared. Everyone signing in this way works as a
          triage nurse.
        </p>
      </div>
    </div>
  );
}
