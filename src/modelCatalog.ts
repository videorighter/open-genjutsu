import catalog from "../models/catalog.json";
import type { NodeKind, Provider } from "./workflow";

export type ModelParameter = {
  key: string;
  label: string;
  type: string;
  minimum?: number;
  maximum?: number;
  default?: string | number | boolean;
  options?: (string | number)[];
  optionLabels?: Record<string, string>;
  when?: Record<string, string>;
};
export type ModelContract = {
  provider: Provider;
  id: string;
  label: string;
  kinds: NodeKind[];
  prompt: boolean;
  vision: boolean;
  generationVerified: boolean;
  source?: string;
  parameters: ModelParameter[];
  inputs?: string[];
  outputs?: string[];
  pricing?: Record<string, string>;
};
export const modelCatalog = catalog.models as ModelContract[];
export const defaultModels = catalog.defaults;
// ponytail: module registry; the service studio re-renders after loading it.
let live: ModelContract[] = [];
export function setLiveModels(models: ModelContract[]) {
  live = models;
}
export function liveModels(kind: NodeKind) {
  return live.filter((m) => m.kinds.includes(kind));
}
export function modelContract(provider: Provider, model: string) {
  return (
    (provider === "openrouter" && live.find((m) => m.id === model)) ||
    modelCatalog.find((m) => m.provider === provider && m.id === model)
  );
}
// Switching models drops options the new model rejects (e.g. FLUX.3's 720p on
// 2K-only MiniMax H3); defaults fill them at submission. Only live contracts
// (with inputs) list every option, so curated or unknown models keep the input.
export function keepSupported(
  input: Record<string, unknown> = {},
  contract?: ModelContract,
) {
  if (!contract?.inputs) return input;
  return Object.fromEntries(
    Object.entries(input).filter(([key, value]) => {
      const field = contract.parameters.find((p) => p.key === key);
      if (!field) return false;
      if (field.type === "enum")
        return (field.options ?? []).includes(value as string | number);
      if (field.type === "boolean") return typeof value === "boolean";
      if (field.type === "integer" || field.type === "number")
        return (
          typeof value === "number" &&
          (field.type === "number" || Number.isInteger(value)) &&
          value >= (field.minimum ?? -Infinity) &&
          value <= (field.maximum ?? Infinity)
        );
      return true;
    }),
  );
}
export function priceLabel(m: ModelContract) {
  const p = m.pricing || {};
  const perSecond = Object.entries(p).find(([k]) =>
    k.startsWith("cents_per_video_output_second"),
  );
  if (perSecond) return `${perSecond[1]}¢/초~`;
  if (p.cents_per_second_output) return `${p.cents_per_second_output}¢/초`;
  const dollars = Object.entries(p).find(([k]) =>
    k.includes("duration_seconds"),
  );
  if (dollars) return `$${dollars[1]}/초~`;
  if (p.prompt !== undefined && Number(p.prompt) >= 0)
    return `$${(Number(p.prompt) * 1e6).toFixed(2)}/$${(Number(p.completion) * 1e6).toFixed(2)} per 1M`;
  return "가격 확인 필요";
}
