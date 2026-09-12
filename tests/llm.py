import os
from openai import OpenAI
from ctxflow import CtxFlow
# Helper to format retrieved nodes for LLM prompt injection
def format_context_for_llm(results):
    items = [f"- [{r.node.node_type.upper()}] {r.node.content}" for r in results]
    return "Relevant Retrieved Memory:\n" + "\n".join(items)

# Initialize OpenAI client to route to NVIDIA NIM endpoints
api_key = os.environ.get("NVIDIA_API_KEY")
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=api_key,
)

# Specify an available NVIDIA NIM hosted model
MODEL_NAME = "meta/llama-3.2-11b-vision-instruct"


def simulate_agent_memory():
    print("=== Setting up Agent Memory ===")
    
    # The full conversation history (Baseline)
    full_history = []
    
    # CtxFlow Graph (Our Context Manager)
    ctx = CtxFlow()

    # TURN 1: The Critical Fact (The "Needle")
    fact = "Database connection string: postgresql://svc_app:SecretPass99@db-primary.internal:5432/checkout_db"
    full_history.append(f"Turn 1: {fact}")
    ctx.ingest(fact, node_type="credential", tags={"database", "postgresql", "connection"})

    # TURNS 2-8: Distractor noise (pushes the fact out of recent memory)
    for i in range(2, 9):
        noise = f"Turn {i}: Checked system logs. CPU usage is normal. Ignored 15 generic warnings."
        full_history.append(noise)
        ctx.ingest(noise, node_type="telemetry", tags={"logs", "cpu", "system"})

    # TURN 9: The Task
    task = "Write the connection command for the checkout database."
    
    return full_history, ctx, task


def evaluate_baseline_sliding_window(full_history, task):
    """BASELINE: LLM only remembers the last 3 turns of conversation."""
    print("\n--- Testing BASELINE (Sliding Window: Last 3 Turns) ---")
    
    # LLM only gets the recent noise, missing Turn 1
    recent_memory = "\n".join(full_history[-3:]) 
    
    prompt = f"Recent Memory:\n{recent_memory}\n\nTask: {task}"
    
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}]
    )
    print(f"Prompt Tokens Used: ~{len(prompt.split())}")
    print(f"LLM Response:\n{response.choices[0].message.content}")


def evaluate_ctxflow(ctx, task):
    """CTXFLOW: LLM uses the graph to retrieve relevant context."""
    print("\n--- Testing CTXFLOW (Graph Context Manager) ---")
    
    # Retrieve relevant memory using CtxFlow
    results = ctx.query(task, k=2)
    context_block = format_context_for_llm(results)
    
    prompt = f"{context_block}\n\nTask: {task}"
    
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}]
    )
    print(f"Prompt Tokens Used: ~{len(prompt.split())}")
    print(f"LLM Response:\n{response.choices[0].message.content}")


if __name__ == "__main__":
    history, ctx_graph, task = simulate_agent_memory()
    
    # The Baseline will fail (missing the database connection string)
    evaluate_baseline_sliding_window(history, task)
    
    # CtxFlow will retrieve Turn 1 and succeed
    evaluate_ctxflow(ctx_graph, task)