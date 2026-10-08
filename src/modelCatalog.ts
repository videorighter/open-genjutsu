import catalog from "../models/catalog.json";
import type { NodeKind, Provider } from "./workflow";

export type ModelParameter = {
  key: string;
  label: string;
  type: string;
  minimum?: number;
  maximum?: number;
  default?: string | number | boolean;
  options?: string[];
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
};
export const modelCatalog = catalog.models as ModelContract[];
export function modelContract(provider: Provider, model: string) {
  return modelCatalog.find((m) => m.provider === provider && m.id === model);
}
