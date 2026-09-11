"use client";

import { useState } from "react";

import { isSupabaseConfigured, signInWithEmail } from "@/lib/supabase";
import { setUserEmail } from "@/lib/api";
import { Button, Card, ErrorBanner } from "./ui";

/**
 * Sign-in step.
 *
 * With Supabase configured this sends a magic link — which doubles as the
 * email verification §3.10 wants for the free tier. Without it, the form just
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
          ? "E-posta adresinize tek kullanımlık bir giriş bağlantısı göndereceğiz."
          : "Geliştirme modu: kimlik doğrulama yapılandırılmamış."
      }
    >
      {error ? (
        <div className="mb-4">
          <ErrorBanner message={error} />
        </div>
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
