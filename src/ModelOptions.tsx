import { modelContract } from "./modelCatalog";
import type { NodeData } from "./workflow";
import "./modelOptions.css";

export default function ModelOptions({
  data,
  onChange,
}: {
  data: NodeData;
  onChange: (value: Record<string, unknown>) => void;
}) {
  const contract = modelContract(data.provider, data.model);
  const values = data.providerInput || {};
  if (!contract || !contract.parameters.length) return null;
  function update(key: string, value: unknown) {
    const next = { ...values };
    if (value === "") delete next[key];
    else next[key] = value;
    onChange(next);
  }
  return (
    <section className="model-options" aria-label="모델별 입력 설정">
      <h3>모델 입력</h3>
      {contract.parameters
        .filter(
          (field) =>
            !field.when ||
            Object.entries(field.when).every(
              ([key, expected]) =>
                (values[key] ??
                  contract.parameters.find((p) => p.key === key)?.default) ===
                expected,
            ),
        )
        .map((field) => {
          const value = values[field.key] ?? field.default ?? "";
          return (
            <label
              className={field.type === "boolean" ? "model-checkbox" : "field"}
              key={field.key}
            >
              <span>{field.label}</span>
              {field.type === "enum" ? (
                <select
                  aria-label={field.label}
                  value={String(value)}
                  onChange={(e) => update(field.key, e.target.value)}
                >
                  {field.options!.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              ) : field.type === "boolean" ? (
                <input
                  aria-label={field.label}
                  type="checkbox"
                  checked={value === true}
                  onChange={(e) => update(field.key, e.target.checked)}
                />
              ) : (
                <input
                  aria-label={field.label}
                  type={
                    ["integer", "number"].includes(field.type)
                      ? "number"
                      : "text"
                  }
                  min={field.minimum}
                  max={field.maximum}
                  step={field.type === "integer" ? 1 : "any"}
                  value={String(value)}
                  maxLength={field.type === "url" ? 2000 : undefined}
                  placeholder={
                    field.type === "url"
                      ? "https://… 또는 $image / $video"
                      : undefined
                  }
                  onChange={(e) =>
                    update(
                      field.key,
                      e.target.value === ""
                        ? ""
                        : ["integer", "number"].includes(field.type)
                          ? Number(e.target.value)
                          : e.target.value,
                    )
                  }
                />
              )}
            </label>
          );
        })}
      {values.task === "inpainting" && (
        <p className="field-help">
          마스크 영상 또는 이미지 URL 중 하나가 필요합니다.
        </p>
      )}
    </section>
  );
}
