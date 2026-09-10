"use client";

import { useState } from "react";

import { downloadReport, type Analysis, type Report } from "@/lib/api";
import { Button, ErrorBanner, InfoBanner } from "./ui";

const STATUS_LABEL: Record<string, string> = {
  met: "Karşılandı",
  violated: "Karşılanmadı",
  not_applicable: "Uygulanamaz",
  not_run: "Uygulanamadı",
};

/** Mirrors _ASSUMPTION_LABELS in backend/app/apa/tables.py. */
const ASSUMPTION_LABEL: Record<string, string> = {
  normality: "Normallik",
  homogeneity_of_variance: "Varyansların homojenliği",
  multicollinearity: "Çoklu bağlantı",
  homoscedasticity: "Hata varyanslarının sabitliği",
  linearity: "Doğrusallık",
  expected_cell_count: "Beklenen göz frekansı",
  not_applicable: "Uygulanabilir varsayım yok",
};

/** Mirrors _METRIC_LABELS in backend/app/apa/tables.py. */
const METRIC_SYMBOL: Record<string, string> = {
  cohens_d: "Cohen's d",
  eta_squared: "η²",
  partial_eta_squared: "kısmi η²",
  epsilon_squared: "ε²",
  r: "r",
  rho: "ρ",
  rank_biserial_r: "r",
  cramers_v: "Cramér's V",
  r_squared: "R²",
  alpha: "α",
};

/** Statistics bounded by 1 drop their leading zero (APA 7th ed. §6.36). */
const BOUNDED = new Set(Object.keys(METRIC_SYMBOL)).add("p");

function formatNumber(value: number | null, digits = 3): string {
  if (value === null || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

function formatStatistic(metric: string, value: number): string {
  const text = value.toFixed(BOUNDED.has(metric) ? 3 : 2);
  return BOUNDED.has(metric) ? text.replace(/^(-?)0\./, "$1.") : text;
}

export function ResultView({
  analysis,
  report,
}: {
  analysis: Analysis;
  report: Report | null;
}) {
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function download(format: "docx" | "pdf") {
    setDownloadError(null);
    setBusy(format);
    try {
      await downloadReport(analysis.id, format);
    } catch (error) {
      setDownloadError(
        error instanceof Error ? error.message : "Rapor indirilemedi.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-base font-semibold">
          {analysis.analysis_label_tr ?? analysis.analysis_type}
        </h3>
        {analysis.effect_size ? (
          <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-700">
            Etki büyüklüğü: {analysis.effect_size.label_tr} (
            {METRIC_SYMBOL[analysis.effect_size.metric] ??
              analysis.effect_size.metric}{" "}
            ={" "}
            {formatStatistic(
              analysis.effect_size.metric,
              analysis.effect_size.value,
            )}
            )
          </span>
        ) : null}
      </div>

      {/* §3.4: when the assumption checks changed the test, say so plainly. */}
      {analysis.substituted && analysis.substitution_reason_tr ? (
        <InfoBanner title="Analiz seçimi değiştirildi">
          {analysis.substitution_reason_tr}
        </InfoBanner>
      ) : null}

      {/* §3.4: the assumption checks are always reported, never skipped.
          Once the report exists its APA "Varsayım Kontrolleri" table carries
          them, so this live panel only fills the gap before that. */}
      {report ? null : (
      <div>
        <h4 className="mb-2 text-sm font-semibold text-slate-700">
          Varsayım kontrolleri
        </h4>
        <div className="overflow-x-auto rounded-md border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">Varsayım</th>
                <th className="px-3 py-2">Grup / Değişken</th>
                <th className="px-3 py-2">Test</th>
                <th className="px-3 py-2 text-right">İstatistik</th>
                <th className="px-3 py-2 text-right">p</th>
                <th className="px-3 py-2">Sonuç</th>
              </tr>
            </thead>
            <tbody>
              {(analysis.assumption_results ?? []).map((check, index) => (
                <tr key={index} className="border-t border-slate-100">
                  <td className="px-3 py-2">
                    {ASSUMPTION_LABEL[check.assumption] ?? check.assumption}
                  </td>
                  <td className="px-3 py-2 text-slate-600">
                    {check.group ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-slate-600">
                    {check.test_name}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatNumber(check.statistic)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatNumber(check.p_value)}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        check.status === "violated"
                          ? "text-amber-700"
                          : "text-slate-700"
                      }
                    >
                      {STATUS_LABEL[check.status] ?? check.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      )}

      {report ? (
        <>
          <div>
            <h4 className="mb-2 text-sm font-semibold text-slate-700">
              Bulgular
            </h4>
            <p className="rounded-md bg-slate-50 p-4 text-sm leading-7 text-slate-800">
              {report.interpretation_text_tr}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              {report.interpretation_source === "llm"
                ? "Yorum metni dil modeli tarafından yazılmış, içindeki her sayısal değer hesaplama çıktısıyla doğrulanmıştır."
                : "Yorum metni doğrulanmış şablondan üretilmiştir."}
            </p>
          </div>

          <div>
            <h4 className="mb-2 text-sm font-semibold text-slate-700">
              APA tabloları
            </h4>
            {/* Server-rendered APA markup (§3.7). It is generated by our own
                deterministic table code and escaped there, never user input. */}
            <div
              className="apa-preview"
              dangerouslySetInnerHTML={{ __html: report.apa_table_html }}
            />
          </div>

          <div className="space-y-3">
            <div className="flex gap-3">
              {report.docx_url ? (
                <Button onClick={() => download("docx")} disabled={busy !== null}>
                  {busy === "docx" ? "İndiriliyor…" : "Word (.docx) indir"}
                </Button>
              ) : null}
              {report.pdf_url ? (
                <Button
                  variant="secondary"
                  onClick={() => download("pdf")}
                  disabled={busy !== null}
                >
                  {busy === "pdf" ? "İndiriliyor…" : "PDF indir"}
                </Button>
              ) : null}
            </div>
            {downloadError ? <ErrorBanner message={downloadError} /> : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
