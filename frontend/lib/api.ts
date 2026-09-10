/**
 * Client for the Sigma API (§6).
 *
 * Every request carries the Supabase session JWT as `Authorization: Bearer`,
 * which the API verifies cryptographically. When Supabase is not configured
 * the client falls back to the `X-User-Email` development header — which the
 * backend only accepts with ALLOW_INSECURE_HEADER_AUTH on, and refuses
 * outright in production.
 */

import { getAccessToken, isSupabaseConfigured } from "./supabase";

const USER_EMAIL_KEY = "sigma:user-email";

export function getUserEmail(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(USER_EMAIL_KEY) ?? "";
}

export function setUserEmail(email: string): void {
  window.localStorage.setItem(USER_EMAIL_KEY, email);
}

export type MeasurementLevel = "nominal" | "ordinal" | "interval" | "ratio";
export type VariableRole =
  | "dependent"
  | "independent"
  | "grouping"
  | "covariate"
  | "scale_item";

export interface DetectedVariable {
  column_name: string;
  position: number;
  detected_type: string;
  suggested_measurement_level: MeasurementLevel;
  distinct_value_count: number;
  missing_count: number;
  sample_values: (string | number | null)[];
}

export interface Variable {
  id: string;
  column_name: string;
  position: number;
  detected_type: string;
  confirmed_type: string | null;
  measurement_level: MeasurementLevel | null;
  role: VariableRole | null;
  distinct_value_count: number | null;
}

export interface Dataset {
  id: string;
  filename: string;
  row_count: number;
  column_count: number;
  uploaded_at: string;
  variables: Variable[];
  detection?: DetectedVariable[];
}

export interface EffectSize {
  metric: string;
  value: number;
  band: string;
  label_tr: string;
  thresholds: number[] | null;
}

export interface AssumptionResult {
  assumption: string;
  test_name: string;
  status: "met" | "violated" | "not_applicable" | "not_run";
  blocking: boolean;
  statistic: number | null;
  p_value: number | null;
  group: string | null;
  message_tr: string;
}

export interface Analysis {
  id: string;
  dataset_id: string;
  analysis_type: string;
  analysis_label_tr: string | null;
  recommended_analysis_type: string | null;
  status: string;
  created_at: string;
  assumption_results: AssumptionResult[] | null;
  effect_size: EffectSize | null;
  raw_result: Record<string, any> | null;
  substituted: boolean;
  substitution_reason_tr: string | null;
}

export interface Report {
  id: string;
  analysis_id: string;
  interpretation_text_tr: string;
  apa_table_html: string;
  interpretation_source: string;
  docx_url: string | null;
  pdf_url: string | null;
}

export interface Credits {
  credits_remaining: number;
  entries: Record<string, any>[];
}

/** Carries the backend's Turkish message straight to the UI. */
export class ApiError extends Error {
  code?: string;
  status: number;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** Attach whichever credential this deployment actually uses. */
async function authHeaders(headers: Headers): Promise<Headers> {
  if (isSupabaseConfigured) {
    const token = await getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return headers;
  }
  headers.set("X-User-Email", getUserEmail());
  return headers;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = await authHeaders(new Headers(init.headers));
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, { ...init, headers });

  if (!response.ok) {
    let message =
      response.status === 401
        ? "Oturumunuz sona ermiş olabilir. Lütfen tekrar giriş yapın."
        : `İstek başarısız oldu (${response.status}).`;
    let code: string | undefined;
    try {
      const body = await response.json();
      // FastAPI puts our structured refusals under `detail`, which is either a
      // string or the {detail, code, recommendation} object the API returns for
      // an unsupported analysis (§3.3).
      const detail = body?.detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (detail && typeof detail === "object") {
        message = detail.detail ?? message;
        code = detail.code;
      }
    } catch {
      /* keep the default message */
    }
    throw new ApiError(message, response.status, code);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function uploadDataset(file: File): Promise<Dataset> {
  const form = new FormData();
  form.append("file", file);
  return request<Dataset>("/api/datasets", { method: "POST", body: form });
}

export async function confirmVariables(
  datasetId: string,
  variables: {
    column_name: string;
    measurement_level?: MeasurementLevel;
    role?: VariableRole;
  }[],
): Promise<Dataset> {
  return request<Dataset>(`/api/datasets/${datasetId}/variables`, {
    method: "PATCH",
    body: JSON.stringify({ variables }),
  });
}

export async function deleteDataset(datasetId: string): Promise<void> {
  return request<void>(`/api/datasets/${datasetId}`, { method: "DELETE" });
}

export async function createAnalysis(payload: {
  dataset_id: string;
  task: string;
  dependent_variable?: string | null;
  independent_variables?: string[];
  paired_measurements?: string[];
  scale_items?: string[];
  is_paired?: boolean;
}): Promise<Analysis> {
  return request<Analysis>("/api/analyses", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function generateReport(analysisId: string): Promise<Report> {
  return request<Report>(`/api/analyses/${analysisId}/report`, {
    method: "POST",
  });
}

export async function getCredits(): Promise<Credits> {
  return request<Credits>("/api/credits");
}

/**
 * Download a generated report.
 *
 * A plain <a href> cannot carry the Authorization header the API requires, so
 * the file is fetched and handed to the browser as a blob.
 */
export async function downloadReport(
  analysisId: string,
  format: "docx" | "pdf",
): Promise<void> {
  const response = await fetch(
    `/api/analyses/${analysisId}/report/download/${format}`,
    { headers: await authHeaders(new Headers()) },
  );
  if (!response.ok) {
    throw new ApiError(`Rapor indirilemedi (${response.status}).`, response.status);
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `sigma-rapor-${analysisId.slice(0, 8)}.${format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
