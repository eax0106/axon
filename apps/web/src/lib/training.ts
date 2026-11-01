import type { components } from "@axon/contracts";
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";

type S = components["schemas"];
export type Training = S["Training"];
export type Item = S["ItemOut"];
export type NewItem = S["NewItem"];
export type Suggestion = S["SuggestionOut"];
export type Proposal = S["Proposal"];
export const LIMITS = { fact: 60, rule: 20 } as const; // app/training/knowledge.py
export const MAX_ITEM = 300;

const path = (id: string) => ({ params: { path: { employee_id: id } } });

export const useTraining = (id: string) =>
  useQuery({ queryKey: ["training", id], queryFn: () => unwrap(api.GET("/employees/{employee_id}/training", path(id))) });
export const useSuggestions = (id: string) =>
  useQuery({ queryKey: ["training", id, "suggestions"], queryFn: () => unwrap(api.GET("/employees/{employee_id}/training/suggestions", path(id))) });

/** Bodies that are a file rather than JSON (voice, photo, documents) go as they are, with their type. */
export const raw = (file: Blob, type: string) => ({
  body: file as never,
  bodySerializer: (b: unknown) => b as Blob,
  headers: { "Content-Type": type },
});
