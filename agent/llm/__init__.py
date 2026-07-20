"""LLM provider abstraction layer.

This package will host the extracted provider adapters, streaming helpers,
extractors, and cost functions from agent/runtime.py. Phase B1 extracts cost
functions only; subsequent phases add the rest.

Public API (incomplete — grows with each phase):
    cost_for_model(model, prompt_tokens, completion_tokens) -> float
    model_id(model) -> str
"""
