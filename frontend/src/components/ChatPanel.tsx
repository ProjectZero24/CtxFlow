import React, { useEffect, useRef, useState } from "react";
import { useAppState, useDispatch } from "../store/AppContext";
import { WORKFLOW_STAGES } from "../types";
import type { ChatMessage, StageStatus } from "../types";
import { useWorkflow } from "../hooks/useWorkflow";

// ─── Workflow stage bar ───────────────────────────────────────────────────────

const STAGE_LABELS: Record<string, string> = {
  plan: "Plan", retrieve: "Retrieve", read: "Read",
  memory: "Memory", pack: "Pack", synthesize: "Synthesize",
  verify: "Verify", persist: "Persist",
};

function StageBar() {
  const state = useAppState();
  if (!state.busy && Object.keys(state.stageState).length === 0) return null;

  const elapsed = (state.elapsedMs / 1000).toFixed(1);

  return (
    <div className="stage-bar">
      <div className="stage-pills">
        {WORKFLOW_STAGES.map((stage) => {
          const st: StageStatus = (state.stageState[stage] as StageStatus) ?? "pending";
          return (
            <div
              key={stage}
              className={`stage-pill stage-${st}`}
              title={`${stage}: ${st}`}
            >
              <span className="stage-dot" />
              {STAGE_LABELS[stage]}
            </div>
          );
        })}
      </div>
      {state.busy && (
        <span className="stage-elapsed">{elapsed}s</span>
      )}
    </div>
  );
}

// ─── Individual message ───────────────────────────────────────────────────────

function CitationChip({ nodeId, onTrace }: { nodeId: string; onTrace: (id: string) => void }) {
  return (
    <button className="citation-chip" onClick={() => onTrace(nodeId)} title={nodeId}>
      <svg viewBox="0 0 16 16" fill="currentColor" style={{ width: 10, height: 10 }}>
        <path d="M4 4h4v1H5v6h6V8h1v4H4V4z" />
        <path d="M8 4h4v4h-1V5.7L7.4 9.3l-.7-.7L10.3 5H8V4z" />
      </svg>
      {nodeId.slice(0, 10)}…
    </button>
  );
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const labels: Record<string, string> = {
    VERIFIED: "✓ Verified",
    WARNINGS_FOUND: "⚠ Warnings",
    INSUFFICIENT_EVIDENCE: "? Insufficient evidence",
  };
  return (
    <span className={`verdict-badge verdict-${verdict}`}>
      {labels[verdict] ?? verdict.replace(/_/g, " ")}
    </span>
  );
}

function ThinkingBubble() {
  return (
    <div className="thinking-bubble">
      <span /><span /><span />
    </div>
  );
}

function renderText(text: string, onTrace: (id: string) => void): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const pattern = /\[Node:([^\]]+)\]|`([^`]+)`|\*\*(.+?)\*\*/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;

  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) parts.push(<React.Fragment key={key++}>{text.slice(last, m.index)}</React.Fragment>);
    if (m[1]) {
      parts.push(<CitationChip key={key++} nodeId={m[1]} onTrace={onTrace} />);
    } else if (m[2]) {
      parts.push(<code key={key++} className="inline-code">{m[2]}</code>);
    } else if (m[3]) {
      parts.push(<strong key={key++}>{m[3]}</strong>);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(<React.Fragment key={key++}>{text.slice(last)}</React.Fragment>);
  return parts;
}

function Message({ msg, onTrace }: { msg: ChatMessage; onTrace: (id: string) => void }) {
  if (msg.role === "thinking") {
    return (
      <div className="message message-assistant">
        <div className="message-avatar avatar-ai">R</div>
        <div className="message-body"><ThinkingBubble /></div>
      </div>
    );
  }

  const isUser = msg.role === "user";

  return (
    <div className={`message ${isUser ? "message-user" : "message-assistant"}`}>
      <div className={`message-avatar ${isUser ? "avatar-user" : "avatar-ai"}`}>
        {isUser ? "U" : "R"}
      </div>
      <div className="message-body">
        <div className="message-text">
          {msg.content.split("\n").map((line, i) => (
            <p key={i}>{renderText(line, onTrace)}</p>
          ))}
        </div>

        {/* Citation chips */}
        {msg.cited_nodes && msg.cited_nodes.length > 0 && (
          <div className="citation-row">
            {msg.cited_nodes.slice(0, 8).map((nid) => (
              <CitationChip key={nid} nodeId={nid} onTrace={onTrace} />
            ))}
          </div>
        )}

        {/* Alerts */}
        {msg.alerts && msg.alerts.length > 0 && (
          <div className="alert-row">
            {msg.alerts.slice(0, 3).map((a, i) => (
              <div key={i} className={`alert-chip alert-${a.type}`}>
                {a.message || a.type}
              </div>
            ))}
          </div>
        )}

        {/* Verdict */}
        {msg.verdict && <VerdictBadge verdict={msg.verdict} />}

        {/* Context usage */}
        {msg.context_usage?.tokens_used && msg.context_usage?.token_budget && (
          <div className="context-mini">
            <div className="context-mini-bar">
              <div
                className="context-mini-fill"
                style={{ width: `${Math.min(100, (msg.context_usage.tokens_used / msg.context_usage.token_budget) * 100)}%` }}
              />
            </div>
            <span>{msg.context_usage.tokens_used.toLocaleString()} / {msg.context_usage.token_budget.toLocaleString()} tokens</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Composer ────────────────────────────────────────────────────────────────

function Composer() {
  const { run, busy } = useWorkflow();
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    setText("");
    if (inputRef.current) { inputRef.current.style.height = ""; }
    run(q);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(e as unknown as React.FormEvent); }
  };

  const onInput = (e: React.FormEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    el.style.height = "";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        ref={inputRef}
        className="composer-input"
        placeholder="Ask a research question… (Shift+Enter for newline)"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        onInput={onInput}
        rows={2}
        disabled={busy}
        aria-label="Research question"
      />
      <button type="submit" className="btn btn-primary composer-send" disabled={busy || !text.trim()}>
        {busy ? (
          <span className="spinner" aria-label="Sending" />
        ) : (
          <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden>
            <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z" />
          </svg>
        )}
        <span>{busy ? "Running…" : "Send"}</span>
      </button>
    </form>
  );
}

// ─── Main chat panel ──────────────────────────────────────────────────────────

export function ChatPanel() {
  const state = useAppState();
  const dispatch = useDispatch();
  const endRef = useRef<HTMLDivElement>(null);

  // Auto-scroll
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state.messages]);

  const onTrace = (nodeId: string) => {
    dispatch({ type: "SET_TRACE_NODE", payload: nodeId });
  };

  return (
    <section className="chat-panel">
      <StageBar />

      <div className="messages" role="log" aria-live="polite" aria-label="Research conversation">
        {state.messages.length === 0 && (
          <div className="welcome">
            <div className="welcome-icon" aria-hidden>
              <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth={1.5}>
                <circle cx="24" cy="24" r="20" />
                <path d="M16 24h16M24 16l8 8-8 8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h1>ResearchOS</h1>
            <p>Groq-powered multi-agent research. Load the demo corpus, then ask a question below.</p>
            <div className="welcome-examples">
              {[
                "Is cache-aware context selection still supported?",
                "How does GraphRAG compare with flat vector retrieval?",
                "What are known limitations of LLM-based evidence synthesis?",
              ].map((q) => (
                <ExampleChip key={q} text={q} />
              ))}
            </div>
          </div>
        )}

        {state.messages.map((msg) => (
          <Message key={msg.id} msg={msg} onTrace={onTrace} />
        ))}
        <div ref={endRef} />
      </div>

      <div className="composer-wrap">
        <Composer />
      </div>
    </section>
  );
}

function ExampleChip({ text }: { text: string }) {
  const { run, busy } = useWorkflow();
  return (
    <button className="example-chip" onClick={() => !busy && run(text)} disabled={busy}>
      {text}
    </button>
  );
}
