"""Oracle: fan a prompt out to several Ollama models, judge aggregates.

Concurrent `ainvoke` to each model (asyncio.gather), then one judge model
synthesizes all answers into a single detailed response (e.g. a plan).
"""

from __future__ import annotations

import asyncio

from langchain.tools import tool

DEFAULT_MODELS = [
    "glm-5.2:cloud",
    "deepseek-v4-pro:cloud",
    "minimax-m3:cloud",
    "kimi-k2.6:cloud",
    "minimax-m2.7:cloud",
]


async def _ask(model_name: str, prompt: str) -> str:
    """Invoke one Ollama model; degrade to an error string so one bad model
    never sinks the whole fan-out."""
    from novacode_cli.config.model_create import create_model_from_config

    model = create_model_from_config("ollama", model_name)
    if model is None:
        return f"[{model_name}] unavailable"
    try:
        resp = await model.ainvoke(prompt)
        return str(getattr(resp, "content", resp)).strip()
    except Exception as e:  # noqa: BLE001
        return f"[{model_name}] error: {type(e).__name__}: {e}"


def _build_judge_prompt(prompt: str, models: list[str], answers: list[str]) -> str:
    panel = "\n\n".join(f"### Model: {m}\n{a}" for m, a in zip(models, answers))
    return (
        "You are the judge. Several models answered the same request below. "
        "Synthesize their answers into ONE detailed, correct response (a step-by-step "
        "plan if the request calls for one). Resolve conflicts, keep the strongest "
        "points, drop the weak or wrong ones. Do not mention the models.\n\n"
        f"## Original request\n{prompt}\n\n"
        f"## Model answers\n{panel}\n\n"
        "## Your synthesized response"
    )


@tool
async def oracle(prompt: str, models: list[str] | None = None, judge: str | None = None) -> str:
    """Consult multiple Ollama models concurrently and aggregate their answers.

    Fans `prompt` out to every model at once, then a judge model merges the
    responses into one detailed answer (e.g. a plan). Use when a request
    benefits from multiple perspectives before committing to an answer.

    Args:
        prompt: The question or task sent to every model.
        models: Ollama model names to consult concurrently. Defaults to the
            standard oracle panel (glm/deepseek/minimax/kimi).
        judge: Ollama model that aggregates the answers. Defaults to models[0].

    Returns:
        The judge's synthesized response (falls back to the raw per-model
        answers if the judge itself fails).
    """
    models = models or DEFAULT_MODELS
    answers = await asyncio.gather(*(_ask(m, prompt) for m in models))
    verdict = await _ask(judge or models[0], _build_judge_prompt(prompt, models, answers))

    if verdict.startswith("["):  # judge unavailable/errored — return raw answers
        panel = "\n\n".join(f"### Model: {m}\n{a}" for m, a in zip(models, answers))
        return f"[judge failed: {verdict}]\n\n{panel}"
    return verdict


if __name__ == "__main__":
    # ponytail: self-check for the pure aggregation logic (no ollama needed).
    p = _build_judge_prompt("plan X", ["a", "b"], ["ans-A", "ans-B"])
    assert "ans-A" in p and "ans-B" in p and "plan X" in p
    assert "### Model: a" in p and "### Model: b" in p
    print("oracle self-check ok")
