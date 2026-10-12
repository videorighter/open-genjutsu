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
export function priceLabel(m: ModelContract) {
  const p = m.pricing || {};
  const perSecond = Object.entries(p).find(([k]) =>
    k.startsWith("cents_per_video_output_second"),
  );
  if (perSecond) return `${perSecond[1]}¢/초~`;
  if (p.cents_per_second_output) return `${p.cents_per_second_output}¢/초`;
  if (p.prompt !== undefined && Number(p.prompt) >= 0)
    return `$${(Number(p.prompt) * 1e6).toFixed(2)}/$${(Number(p.completion) * 1e6).toFixed(2)} per 1M`;
  return "가격 확인 필요";
}
