"use client";

/**
 * Sigma — the minimal flow that exercises the whole pipeline (Phase 5):
 * upload -> confirm variables -> pick analysis -> view result -> download.
 *
 * Deliberately plain. The point of this screen is that every step of the
 * backend contract is reachable and legible, not that it is polished.
 */

import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  confirmVariables,
  createAnalysis,
  generateReport,
  getCredits,
  getUserEmail,
  uploadDataset,
  type Analysis,
  type Dataset,
  type MeasurementLevel,
  type Report,
} from "@/lib/api";
import { isSupabaseConfigured, signOut, supabase } from "@/lib/supabase";
import { SignIn } from "./components/SignIn";
import { ResultView } from "./components/ResultView";
import { VariableTable, type VariableChoice } from "./components/VariableTable";
import { Button, Card, ErrorBanner, Select, Steps } from "./components/ui";

const STEP_LABELS = [
  "Giriş",
  "Veri yükle",
  "Değişkenleri onayla",
  "Analiz seç",
  "Sonuç",
];

const TASK_OPTIONS = [
  { value: "comparison", label: "Gruplar arası fark (karşılaştırma)" },
  { value: "relationship", label: "İlişki (korelasyon)" },
  { value: "prediction", label: "Yordama (regresyon)" },
  { value: "scale_reliability", label: "Ölçek güvenirliği (Cronbach alfa)" },
];

export default function Home() {
  const [step, setStep] = useState(0);
  const [email, setEmail] = useState("");
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [choices, setChoices] = useState<Record<string, VariableChoice>>({});
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [credits, setCredits] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Analysis configuration
  const [task, setTask] = useState("comparison");
  const [dependent, setDependent] = useState("");
  const [independent, setIndependent] = useState<string[]>([]);
  const [isPaired, setIsPaired] = useState(false);
  const [pairedMeasurements, setPairedMeasurements] = useState<string[]>([]);
  const [scaleItems, setScaleItems] = useState<string[]>([]);

  useEffect(() => {
    if (!isSupabaseConfigured) {
      // Development mode: the email in localStorage is the whole "session".
      const stored = getUserEmail();
      if (stored) {
        setEmail(stored);
        setStep(1);
        void refreshCredits();
      }
      return;
    }

    // Supabase restores the session from storage and, after a magic-link
    // click, from the URL — so subscribe rather than reading once.
    let active = true;
    void supabase!.auth.getSession().then(({ data }) => {
      if (active) applySession(data.session?.user?.email ?? null);
    });
    const { data: subscription } = supabase!.auth.onAuthStateChange(
      (_event, session) => applySession(session?.user?.email ?? null),
    );
    return () => {
      active = false;
      subscription.subscription.unsubscribe();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applySession(sessionEmail: string | null) {
    if (sessionEmail) {
      setEmail(sessionEmail);
      setStep((current) => (current === 0 ? 1 : current));
      void refreshCredits();
    } else {
      setEmail("");
      setStep(0);
      setCredits(null);
    }
  }

  async function handleSignOut() {
    await signOut();
    restart();
    setStep(0);
    setCredits(null);
  }

  const columns = useMemo(
    () => (dataset?.variables ?? []).map((v) => v.column_name),
    [dataset],
  );

  async function refreshCredits() {
    try {
      setCredits((await getCredits()).credits_remaining);
    } catch {
      setCredits(null);
    }
  }

  function fail(caught: unknown) {
    setError(
      caught instanceof ApiError
        ? caught.message
        : caught instanceof Error
          ? caught.message
          : "Beklenmeyen bir hata oluştu.",
    );
  }

  async function handleUpload(file: File) {
    setError(null);
    setBusy(true);
    try {
      const uploaded = await uploadDataset(file);
      setDataset(uploaded);
      setChoices(
        Object.fromEntries(
          uploaded.variables.map((variable) => [
            variable.column_name,
            {
              measurement_level: (variable.measurement_level ??
                "ratio") as MeasurementLevel,
              role: "" as const,
            },
          ]),
        ),
      );
      setStep(2);
      await refreshCredits();
    } catch (caught) {
      fail(caught);
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmVariables() {
    if (!dataset) return;
    setError(null);
    setBusy(true);
    try {
      const updated = await confirmVariables(
        dataset.id,
        Object.entries(choices).map(([column_name, choice]) => ({
          column_name,
          measurement_level: choice.measurement_level,
          ...(choice.role ? { role: choice.role } : {}),
        })),
      );
      setDataset({ ...updated, detection: dataset.detection });
      setStep(3);
    } catch (caught) {
      fail(caught);
    } finally {
      setBusy(false);
    }
  }

  async function handleRunAnalysis() {
    if (!dataset) return;
    setError(null);
    setBusy(true);
    setReport(null);
    try {
      const created = await createAnalysis({
        dataset_id: dataset.id,
        task,
        dependent_variable: task === "scale_reliability" ? null : dependent,
        independent_variables: independent,
        paired_measurements: pairedMeasurements,
        scale_items: scaleItems,
        is_paired: isPaired,
      });
      setAnalysis(created);
      setStep(4);
      // §3.8: the report is what the user actually came for, so generate it
      // immediately rather than making them click twice.
      setReport(await generateReport(created.id));
      await refreshCredits();
    } catch (caught) {
      fail(caught);
      await refreshCredits();
    } finally {
      setBusy(false);
    }
  }

  function toggle(list: string[], value: string): string[] {
    return list.includes(value)
      ? list.filter((item) => item !== value)
      : [...list, value];
  }

  function restart() {
    setDataset(null);
    setAnalysis(null);
    setReport(null);
    setChoices({});
    setDependent("");
    setIndependent([]);
    setPairedMeasurements([]);
    setScaleItems([]);
    setIsPaired(false);
    setError(null);
    setStep(1);
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <header className="mb-8">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Sigma</h1>
            <p className="mt-1 text-sm text-slate-600">
              Tezin için istatistiksel analiz — SPSS bilmene gerek yok.
            </p>
          </div>
          <div className="text-right text-sm text-slate-600">
            {credits !== null ? (
              <p>
                Kalan analiz kredisi:{" "}
                <span className="font-semibold text-slate-900">{credits}</span>
              </p>
            ) : null}
            {email && step > 0 ? (
              <p className="mt-0.5 text-xs text-slate-500">
                {email}
                {isSupabaseConfigured ? (
                  <>
                    {" · "}
                    <button
                      type="button"
                      onClick={() => void handleSignOut()}
                      className="underline hover:text-slate-800"
                    >
                      çıkış
                    </button>
                  </>
                ) : null}
              </p>
            ) : null}
          </div>
        </div>
        <div className="mt-4">
          <Steps current={step} labels={STEP_LABELS} />
        </div>
      </header>

      {error ? (
        <div className="mb-6">
          <ErrorBanner message={error} />
        </div>
      ) : null}

      <div className="space-y-6">
        {step === 0 ? (
          <SignIn
            onDevSignIn={(signedInEmail) => {
              setEmail(signedInEmail);
              void refreshCredits();
              setStep(1);
            }}
          />
        ) : null}

        {step === 1 ? (
          <Card
            title="Veri setini yükle"
            description="CSV veya Excel (.xlsx), en fazla 20 MB. Dosyanız şifrelenmiş olarak saklanır."
          >
            <input
              type="file"
              accept=".csv,.xlsx"
              disabled={busy}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void handleUpload(file);
              }}
              className="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-slate-900 file:px-4 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-slate-700"
            />
            {busy ? (
              <p className="mt-3 text-sm text-slate-500">Yükleniyor…</p>
            ) : null}
          </Card>
        ) : null}

        {step === 2 && dataset ? (
          <Card
            title="Değişkenleri onayla"
            description={`${dataset.filename} — ${dataset.row_count} satır, ${dataset.column_count} sütun. Algılanan türleri gerekirse düzeltin.`}
          >
            <VariableTable
              dataset={dataset}
              choices={choices}
              onChange={(column, choice) =>
                setChoices((previous) => ({ ...previous, [column]: choice }))
              }
            />
            <div className="mt-5 flex gap-3">
              <Button onClick={handleConfirmVariables} disabled={busy}>
                {busy ? "Kaydediliyor…" : "Onayla ve devam et"}
              </Button>
              <Button variant="secondary" onClick={restart}>
                Başka dosya yükle
              </Button>
            </div>
          </Card>
        ) : null}

        {step === 3 && dataset ? (
          <Card
            title="Analizi tanımla"
            description="Sigma, seçimlerinize göre uygun testi kural tabanlı olarak belirler ve varsayımları kontrol eder."
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <Select
                id="task"
                label="Araştırma amacı"
                value={task}
                onChange={setTask}
                options={TASK_OPTIONS}
              />
              {task !== "scale_reliability" ? (
                <Select
                  id="dependent"
                  label="Bağımlı değişken"
                  value={dependent}
                  onChange={setDependent}
                  options={[
                    { value: "", label: "Seçiniz…" },
                    ...columns.map((c) => ({ value: c, label: c })),
                  ]}
                />
              ) : null}
            </div>

            {task === "comparison" ? (
              <label className="mt-4 flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={isPaired}
                  onChange={(event) => setIsPaired(event.target.checked)}
                  className="h-4 w-4 rounded border-slate-300"
                />
                Ölçümler aynı kişilerden alındı (öntest–sontest gibi)
              </label>
            ) : null}

            <div className="mt-4">
              {task === "scale_reliability" ? (
                <CheckboxGroup
                  legend="Ölçek maddeleri"
                  columns={columns}
                  selected={scaleItems}
                  onToggle={(value) =>
                    setScaleItems((previous) => toggle(previous, value))
                  }
                />
              ) : isPaired ? (
                <CheckboxGroup
                  legend="Eşleştirilmiş ölçüm sütunları"
                  columns={columns}
                  selected={pairedMeasurements}
                  onToggle={(value) =>
                    setPairedMeasurements((previous) => toggle(previous, value))
                  }
                />
              ) : (
                <CheckboxGroup
                  legend="Bağımsız değişken(ler)"
                  columns={columns}
                  selected={independent}
                  onToggle={(value) =>
                    setIndependent((previous) => toggle(previous, value))
                  }
                />
              )}
            </div>

            <div className="mt-5 flex gap-3">
              <Button onClick={handleRunAnalysis} disabled={busy}>
                {busy ? "Analiz çalışıyor…" : "Analizi çalıştır"}
              </Button>
              <Button variant="secondary" onClick={() => setStep(2)}>
                Geri
              </Button>
            </div>
          </Card>
        ) : null}

        {step === 4 && analysis ? (
          <Card title="Sonuç" description={dataset?.filename}>
            <ResultView analysis={analysis} report={report} />
            <div className="mt-6">
              <Button variant="secondary" onClick={restart}>
                Yeni analiz
              </Button>
            </div>
          </Card>
        ) : null}
      </div>
    </main>
  );
}

function CheckboxGroup({
  legend,
  columns,
  selected,
  onToggle,
}: {
  legend: string;
  columns: string[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <fieldset>
      <legend className="text-xs font-medium text-slate-600">{legend}</legend>
      <div className="mt-2 flex flex-wrap gap-2">
        {columns.map((column) => {
          const active = selected.includes(column);
          return (
            <label
              key={column}
              className={`cursor-pointer rounded-md border px-3 py-1.5 text-sm ${
                active
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              <input
                type="checkbox"
                checked={active}
                onChange={() => onToggle(column)}
                className="sr-only"
              />
              {column}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
