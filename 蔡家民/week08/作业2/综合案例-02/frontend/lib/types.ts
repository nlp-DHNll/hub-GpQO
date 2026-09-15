export type Status = "queued" | "pending" | "running" | "cancelling" | "cancelled" | "completed" | "failed";
export type Source = { url: string; title: string; site_name: string; snippet: string; accessed_at: string; published_at: string; extraction_status: "full" | "summary" | "failed" };
export type Conclusion = { text: string; sources: { url: string; title: string }[]; is_model_inference: boolean };
export type ProcessStep = { type: string; round: number; detail: Record<string, unknown>; created_at: string };
export type Research = {
  research_id: string; topic: string; goal: string; date_range: string; region: string; audience: string;
  depth: "quick" | "standard" | "deep"; status: Status; created_at: string; updated_at: string;
  friendly_error?: string; progress: number; current_step: string; version: number; root_id?: string;
  limited: boolean; limit_reason: string; follow_up: string;
  usage: { searches: number; model_calls: number; elapsed_seconds: number };
  limits: { max_rounds: number; max_seconds: number; max_searches: number; max_model_calls: number };
  report?: { title: string; summary: string; sections: { heading: string; body: string; conclusions: Conclusion[] }[]; key_conclusions: Conclusion[]; open_questions: string[] };
  sources: Source[]; process?: { plan: string[]; search_queries: string[]; reviewed_urls: string[]; iterations: number; steps: ProcessStep[] };
  confidence?: { overall: "high" | "medium" | "low"; info_cutoff: string; notes: string[]; gaps: string[] };
};
