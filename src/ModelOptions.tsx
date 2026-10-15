import { modelContract } from "./modelCatalog";
import type { NodeData } from "./workflow";
import "./modelOptions.css";

// Temperature only reaches chat requests; seed reaches image requests and video
// models whose live contract accepts it (see backend providers).
export default function ModelOptions({
  data,
  onChange,
  onPatch,
}: {
  data: NodeData;
  onChange: (value: Record<string, unknown>) => void;
  onPatch: (patch: Partial<NodeData>) => void;
}) {
  const contract = modelContract(data.provider, data.model);
  const values = data.providerInput || {};
  const parameters = contract?.parameters ?? [];
  const temperature = ["analysis", "prompt"].includes(data.kind);
  const seed =
    data.kind === "image" ||
    (["motion", "edit"].includes(data.kind) && contract?.seed === true);
  if (!parameters.length && !temperature && !seed) return null;
  function update(key: string, value: unknown) {
    const next = { ...values };
    if (value === "") delete next[key];
    else next[key] = value;
    onChange(next);
  }
  return (
    <section className="model-options" aria-label="모델 옵션">
      <h3>모델 옵션</h3>
      {temperature && (
        <label className="range-field">
          <span>
            Temperature <strong>{data.temperature.toFixed(2)}</strong>
          </span>
          <input
            type="range"
            min="0"
            max="2"
            step="0.05"
            aria-label="Temperature"
            value={data.temperature}
            onChange={(e) => onPatch({ temperature: Number(e.target.value) })}
          />
          <small>
            <span>정밀하게</span>
            <span>자유롭게</span>
          </small>
        </label>
      )}
      {seed && (
        <label className="field">
          <span>Seed</span>
          <input
            aria-label="Seed"
            value={data.seed}
            maxLength={20}
            placeholder="Random"
            onChange={(e) => onPatch({ seed: e.target.value })}
          />
        </label>
      )}
      {parameters
        .filter(
          (field) =>
            !field.when ||
            Object.entries(field.when).every(
              ([key, expected]) =>
                (values[key] ??
                  parameters.find((p) => p.key === key)?.default) === expected,
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
                  onChange={(e) =>
                    update(
                      field.key,
                      // Keep numeric options (e.g. duration) as numbers.
                      field.options!.find((o) => String(o) === e.target.value),
                    )
                  }
                >
                  {field.options!.map((option) => (
                    <option key={option} value={option}>
                      {field.optionLabels?.[String(option)] ?? option}
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
    </section>
  );
}
