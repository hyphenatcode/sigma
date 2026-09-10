"use client";

import type { Dataset, MeasurementLevel, VariableRole } from "@/lib/api";

const LEVEL_OPTIONS: { value: MeasurementLevel; label: string }[] = [
  { value: "nominal", label: "Sınıflama (nominal)" },
  { value: "ordinal", label: "Sıralama (ordinal)" },
  { value: "interval", label: "Eşit aralıklı (interval)" },
  { value: "ratio", label: "Oranlı (ratio)" },
];

const ROLE_OPTIONS: { value: VariableRole | ""; label: string }[] = [
  { value: "", label: "—" },
  { value: "dependent", label: "Bağımlı değişken" },
  { value: "independent", label: "Bağımsız değişken" },
  { value: "grouping", label: "Gruplama değişkeni" },
  { value: "scale_item", label: "Ölçek maddesi" },
];

export interface VariableChoice {
  measurement_level: MeasurementLevel;
  role: VariableRole | "";
}

export function VariableTable({
  dataset,
  choices,
  onChange,
}: {
  dataset: Dataset;
  choices: Record<string, VariableChoice>;
  onChange: (column: string, choice: VariableChoice) => void;
}) {
  const detection = new Map(
    (dataset.detection ?? []).map((item) => [item.column_name, item]),
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
            <th className="py-2 pr-4">Sütun</th>
            <th className="py-2 pr-4">Algılanan tür</th>
            <th className="py-2 pr-4">Farklı değer</th>
            <th className="py-2 pr-4">Örnek</th>
            <th className="py-2 pr-4">Ölçüm düzeyi</th>
            <th className="py-2">Rol</th>
          </tr>
        </thead>
        <tbody>
          {dataset.variables.map((variable) => {
            const detected = detection.get(variable.column_name);
            const choice = choices[variable.column_name];
            if (!choice) return null;
            return (
              <tr
                key={variable.id}
                className="border-b border-slate-100 align-top"
              >
                <td className="py-2 pr-4 font-medium">
                  {variable.column_name}
                </td>
                <td className="py-2 pr-4 text-slate-600">
                  {variable.detected_type}
                </td>
                <td className="py-2 pr-4 text-slate-600">
                  {variable.distinct_value_count ?? "—"}
                </td>
                <td className="py-2 pr-4 text-slate-500">
                  {(detected?.sample_values ?? [])
                    .slice(0, 3)
                    .map((value) => String(value))
                    .join(", ")}
                </td>
                <td className="py-2 pr-4">
                  <select
                    aria-label={`${variable.column_name} ölçüm düzeyi`}
                    value={choice.measurement_level}
                    onChange={(event) =>
                      onChange(variable.column_name, {
                        ...choice,
                        measurement_level: event.target
                          .value as MeasurementLevel,
                      })
                    }
                    className="w-44 rounded-md border border-slate-300 px-2 py-1 text-sm"
                  >
                    {LEVEL_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="py-2">
                  <select
                    aria-label={`${variable.column_name} rolü`}
                    value={choice.role}
                    onChange={(event) =>
                      onChange(variable.column_name, {
                        ...choice,
                        role: event.target.value as VariableRole | "",
                      })
                    }
                    className="w-44 rounded-md border border-slate-300 px-2 py-1 text-sm"
                  >
                    {ROLE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
