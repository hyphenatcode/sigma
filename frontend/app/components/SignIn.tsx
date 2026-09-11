"use client";

import { useState } from "react";

import {
  isSupabaseConfigured,
  signInWithEmail,
  signInWithGoogle,
} from "@/lib/supabase";
import { setUserEmail } from "@/lib/api";
import { Button, Card, ErrorBanner } from "./ui";

/**
 * Sign-in step.
 *
 * With Supabase configured this offers two routes in: Google, and a magic
 * link — which doubles as the email verification §3.10 wants for the free
 * tier. Two routes because email deliverability would otherwise be a single
 * point of failure for all authentication. Without Supabase, the form just
 * records an email address for the development header, and says so plainly
 * rather than looking like real authentication.
 */
export function SignIn({
  onDevSignIn,
}: {
  onDevSignIn: (email: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!email.includes("@")) {
      setError("Lütfen geçerli bir e-posta adresi girin.");
      return;
    }
    setError(null);

    if (!isSupabaseConfigured) {
      const normalised = email.trim().toLowerCase();
      setUserEmail(normalised);
      onDevSignIn(normalised);
      return;
    }

    setBusy(true);
    try {
      await signInWithEmail(email.trim().toLowerCase());
      setSent(true);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Giriş bağlantısı gönderilemedi.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function google() {
    setError(null);
    setBusy(true);
    try {
      // Redirects away on success; control only returns here on failure.
      await signInWithGoogle();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Google ile giriş başlatılamadı.",
      );
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <Card title="E-postanızı kontrol edin">
        <p className="text-sm text-slate-700">
          <span className="font-medium">{email}</span> adresine bir giriş
          bağlantısı gönderdik. Bağlantıya tıkladığınızda buraya
          yönlendirileceksiniz.
        </p>
        <div className="mt-4">
          <Button variant="secondary" onClick={() => setSent(false)}>
            Farklı bir adres kullan
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <Card
      title="Giriş"
      description={
        isSupabaseConfigured
          ? "Google hesabınızla ya da e-posta adresinize gönderilecek tek kullanımlık bağlantıyla giriş yapın."
          : "Geliştirme modu: kimlik doğrulama yapılandırılmamış."
      }
    >
      {error ? (
        <div className="mb-4">
          <ErrorBanner message={error} />
        </div>
      ) : null}

      {isSupabaseConfigured ? (
        <>
          <button
            type="button"
            onClick={() => void google()}
            disabled={busy}
            className="inline-flex w-full items-center justify-center gap-3 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <GoogleMark />
            Google ile devam et
          </button>

          <div className="my-5 flex items-center gap-3">
            <span className="h-px flex-1 bg-slate-200" />
            <span className="text-xs text-slate-500">veya</span>
            <span className="h-px flex-1 bg-slate-200" />
          </div>
        </>
      ) : null}

      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-64 flex-1">
          <label htmlFor="email" className="block text-xs font-medium text-slate-600">
            E-posta adresi
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void submit();
            }}
            placeholder="ad.soyad@universite.edu.tr"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>
        <Button onClick={() => void submit()} disabled={busy}>
          {busy
            ? "Gönderiliyor…"
            : isSupabaseConfigured
              ? "Giriş bağlantısı gönder"
              : "Devam et"}
        </Button>
      </div>

      <p className="mt-4 text-xs text-slate-500">
        Üniversite (.edu.tr) adresiyle giriş yapan kullanıcılar ücretsiz deneme
        hakkından yararlanır.
      </p>

      {!isSupabaseConfigured ? (
        <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          Bu ortamda kimlik doğrulama devre dışı. Girdiğiniz adres yalnızca
          geliştirme amacıyla kullanılır ve doğrulanmaz.
        </p>
      ) : null}
    </Card>
  );
}

/** Google's four-colour "G", inline so the button needs no network request. */
function GoogleMark() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z"
      />
      <path
        fill="#34A853"
        d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z"
      />
      <path
        fill="#FBBC05"
        d="M11.69 28.18C11.25 26.86 11 25.45 11 24s.25-2.86.69-4.18v-5.7H4.34A21.99 21.99 0 0 0 2 24c0 3.55.85 6.91 2.34 9.88l7.35-5.7z"
      />
      <path
        fill="#EA4335"
        d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.93 4.34 14.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z"
      />
    </svg>
  );
}
