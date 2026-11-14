"""A scripted model: a real LLMClient wired to a fake OpenAI client, so llm.py's parsing is exercised too."""
import itertools
import json
from types import SimpleNamespace as NS

from app.agent.llm import LLMClient, LLMConfig

CFG = LLMConfig(base_url="http://localhost:11434/v1", api_key="", model="scripted", temperature=None)


def call(name: str, args: dict | str, id_: str | None = None) -> tuple:
    """One tool call; pass `args` as a str to send malformed JSON."""
    return name, args if isinstance(args, str) else json.dumps(args), id_


def reply(*calls: tuple, text: str | None = None, tokens_in: int | None = 100) -> NS:
    """`tokens_in` is the reported prompt size; None means the server sent no usage."""
    ids = itertools.count(1)
    tool_calls = [NS(id=c[2] or f"call_{next(ids)}", function=NS(name=c[0], arguments=c[1])) for c in calls]
    message = NS(content=text, tool_calls=tool_calls or None)
    return NS(model="scripted", usage=None if tokens_in is None else NS(prompt_tokens=tokens_in, completion_tokens=10),
              choices=[NS(finish_reason="tool_calls" if tool_calls else "stop", message=message)])


def scripted_llm(script) -> LLMClient:
    """`script` is any iterable of replies; an Exception in it is raised instead. `.sent` lists the messages of each call."""
    steps = iter(script)
    sent: list[list[dict]] = []

    def create(**kwargs):
        sent.append(list(kwargs["messages"]))
        step = next(steps)
        if isinstance(step, Exception):
            raise step
        return step

    llm = LLMClient(CFG, client=NS(chat=NS(completions=NS(create=create))))
    llm.sent = sent
    return llm


def submit(decision="ACCEPT", new_units=0, demand=40.0, **over) -> tuple:
    args = {"decision": decision, "new_units": new_units, "daily_demand_used": demand,
            "key_factors": ["a fact"], "actions_taken": ["did it"], "confidence": "high", "summary": "Done."}
    return call("submit_decision", {**args, **over})


FACT_TOOLS = ("get_product", "get_inventory", "get_purchase_orders", "get_forecast", "get_sales_history",
              "get_suppliers", "get_budget", "get_storage")


def investigate(sku: str) -> NS:
    """One turn that reads every fact about a SKU, as a model that batches its reads would."""
    return reply(*(call(name, {"sku": sku}) for name in FACT_TOOLS))
