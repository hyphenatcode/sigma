/**
 * Supabase browser client (§7).
 *
 * Auth is optional at build time so the app still runs against a local backend
 * with no Supabase project — that mirrors the backend's
 * ALLOW_INSECURE_HEADER_AUTH escape hatch. When the environment variables are
 * absent, `supabase` is null and the UI falls back to asking for an email
 * address and sending it as the development header.
 *
 * The anon key is public by design: it identifies the project, and row-level
 * security (not secrecy) is what protects data on the Supabase side. Sigma's
 * own data is protected by the API verifying the session JWT.
 */

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const isSupabaseConfigured = Boolean(url && anonKey);

export const supabase: SupabaseClient | null = isSupabaseConfigured
  ? createClient(url!, anonKey!, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    })
  : null;

/** The current access token, or null when signed out or unconfigured. */
export async function getAccessToken(): Promise<string | null> {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

export async function signInWithEmail(email: string): Promise<void> {
  if (!supabase) throw new Error("Supabase yapılandırılmamış.");
  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: window.location.origin },
  });
  if (error) throw new Error(error.message);
}

export async function signOut(): Promise<void> {
  await supabase?.auth.signOut();
}
