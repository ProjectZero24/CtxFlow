// API types mirroring the FastAPI schemas

export interface ProjectMeta {
  project_id: string;
  name: string;
  description: string;
  created_at: number;
  updated_at: number;
  nodes: number;
  edges: number;
}

export interface RunRecord {
  run_id: string;
  project_id: string;
  query: string;
  status: string;
  stage?: string;
  intent?: string;
  answer: string;
  verdict: string;
  cited_nodes: string[];
  alerts: Alert[];
  validations: Record<string, unknown>[];
  context_usage: ContextUsage;
  external_search?: ExternalSearch;
  errors: string[];
  degraded: boolean;
  started_at: number;
  ended_at?: number;
  events?: WorkflowEvent[];
}

export interface Alert {
  type: string;
  message: string;
  node_id?: string;
  superseded_by?: string;
}

export interface ContextUsage {
  nodes_retrieved?: number;
  nodes_used?: number;
  nodes_dropped?: number;
  tokens_used?: number;
  token_budget?: number;
  selected_node_ids?: string[];
}

export interface ExternalSearch {
  status: string;
  provider?: string;
  errors?: Record<string, string>;
}

export interface WorkflowEvent {
  run_id: string;
  stage: string;
  status: string;
  message: string;
  ts: number;
  data?: Record<string, unknown>;
}

export interface HealthResponse {
  status: string;
  version: string;
  graph_nodes: number;
  graph_edges: number;
  persistence: string;
  model_enabled: boolean;
  model_provider?: string;
  model_id?: string;
}

export interface TraceResponse {
  answer_node_id: string;
  provenance_chain: TraceStep[];
  superseded_claims: GraphNode[];
  contradictions: Contradiction[];
  source_papers: GraphNode[];
}

export interface TraceStep {
  node_id: string;
  content: string;
  summary?: string;
  node_type: string;
  status: string;
  edge_relation?: string;
  edge_weight?: number;
}

export interface GraphNode {
  id: string;
  content: string;
  summary?: string;
  node_type: string;
  status: string;
  tags?: string[];
  superseded_by?: string;
  metadata?: Record<string, unknown>;
  timestamp?: number;
}

export interface Contradiction {
  node_id: string;
  content: string;
  relation: string;
  confidence?: number;
  evidence?: string;
}

// ─── Message types for UI chat ───────────────────────────────────────────────

export type MessageRole = "user" | "assistant" | "thinking";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  cited_nodes?: string[];
  alerts?: Alert[];
  verdict?: string;
  external_search?: ExternalSearch;
  context_usage?: ContextUsage;
  timestamp: number;
}

export type StageStatus = "pending" | "active" | "done" | "failed" | "degraded" | "skipped" | "blocked";

export interface StageState {
  [stage: string]: StageStatus;
}

export const WORKFLOW_STAGES = [
  "plan", "retrieve", "read", "memory", "pack", "synthesize", "verify", "persist",
] as const;

export type WorkflowStage = typeof WORKFLOW_STAGES[number];
