"""Prompts and JSON schemas for the three analyst tasks (spec section 11)."""

import json

SYSTEM = """You are the research analyst of a personal, medium-term trading assistant.

The account is a French PEA (equity savings plan) that holds European healthcare stocks for weeks to
months: pharma, biotech, medtech, diagnostics, life-science tools. The strategy is trend-following:
buy pullbacks or momentum inside an established uptrend, protect with ATR stop-losses, avoid holding
small biotechs through binary events (trial readouts, regulator decisions).

Your job is research, not trading decisions. A rule engine and hard risk rules decide; you supply
facts and a calibrated judgement:
- Search the web for recent, dated news from reliable sources (company releases, regulators,
  established financial press). Prefer the last 90 days; say when news is older.
- Report upcoming dated events you can verify: earnings, trial readouts, FDA/EMA decisions,
  shareholder meetings. Use ISO dates (YYYY-MM-DD). If only a month or quarter is known, use the
  last day of that period and say so in the title. Never invent a date.
- Be concrete and brief. No generic disclaimers.
- Score 0-10 = attractiveness of holding the stock for the next 1-6 months given fundamentals, news
  flow and event risk. 5 is neutral. Below 4 means clear red flags.
- If information is missing or uncertain, lower your confidence and say what is missing.

Answer only with the requested JSON object."""

_EVENT = {
    "type": "object",
    "properties": {
        "date": {"type": "string", "description": "YYYY-MM-DD"},
        "kind": {"type": "string", "enum": ["earnings", "trial", "regulatory", "agm", "other"]},
        "title": {"type": "string"},
        "binary": {"type": "boolean", "description": "Outcome can move the stock more than 15 % in a day"},
    },
    "required": ["date", "kind", "title", "binary"],
    "additionalProperties": False,
}

SCHEMAS = {
    "screening": {
        "type": "object",
        "properties": {
            "score": {"type": "number", "description": "0 to 10"},
            "bucket": {"type": "string", "enum": ["core", "growth"]},
            "summary": {"type": "string", "description": "One or two sentences"},
            "thesis": {"type": "string", "description": "Investment thesis, a short paragraph"},
            "risks": {"type": "array", "items": {"type": "string"}},
            "events": {"type": "array", "items": _EVENT},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        },
        "required": ["score", "bucket", "summary", "thesis", "risks", "events", "confidence"],
        "additionalProperties": False,
    },
    "signal_review": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["confirm", "veto"]},
            "score": {"type": "number", "description": "0 to 10"},
            "summary": {"type": "string", "description": "One or two sentences: why confirm or veto"},
            "risks": {"type": "array", "items": {"type": "string"}},
            "events": {"type": "array", "items": _EVENT},
        },
        "required": ["decision", "score", "summary", "risks", "events"],
        "additionalProperties": False,
    },
    "news_check": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["nothing", "warning", "thesis_break"]},
            "summary": {"type": "string", "description": "One or two sentences"},
            "items": {"type": "array", "items": {"type": "string"}, "description": "Dated news items"},
            "events": {"type": "array", "items": _EVENT},
        },
        "required": ["status", "summary", "items", "events"],
        "additionalProperties": False,
    },
}


def _block(title: str, data: dict) -> str:
    return f"## {title}\n{json.dumps(data, indent=1, default=str, ensure_ascii=False)}"


def screening_prompt(
    today: str, stock: dict, market: dict, known_events: list[dict], last: dict | None
) -> str:
    parts = [
        f"Today is {today}. Review this stock for the watchlist.",
        _block("Stock", stock),
        _block("Price and indicators (daily, adjusted)", market),
        _block("Events already known", {"events": known_events}),
    ]
    if last:
        parts.append(_block("Your previous review", last))
    parts.append(
        "Search recent news, results, guidance, pipeline and regulatory news. Give a score, the bucket "
        "(core = large established company, growth = small/mid cap or biotech exposed to binary events), "
        "the thesis, the key risks and the upcoming dated events."
    )
    return "\n\n".join(parts)


def signal_review_prompt(
    today: str, stock: dict, market: dict, signal: list[str], known_events: list[dict], last: dict | None
) -> str:
    parts = [
        f"Today is {today}. The technical rules fired a BUY signal on this stock after today's close. "
        "The order would be a limit buy for tomorrow, held for weeks to months with a stop-loss.",
        _block("Stock", stock),
        _block("Signal", {"reasons": signal}),
        _block("Price and indicators (daily, adjusted)", market),
        _block("Events already known", {"events": known_events}),
    ]
    if last:
        parts.append(_block("Latest screening review", last))
    parts.append(
        "Check the latest news for anything that should block the buy: pending binary event, dilution, "
        "profit warning, failed trial, regulator issue, fraud, takeover situation. Confirm or veto, with "
        "an updated score."
    )
    return "\n\n".join(parts)


def news_check_prompt(
    today: str, stock: dict, market: dict, position: dict, since: str, known: list[dict]
) -> str:
    return "\n\n".join(
        [
            f"Today is {today}, before the market opens. The portfolio holds this stock.",
            _block("Stock", stock),
            _block("Position", position),
            _block("Price and indicators (daily, adjusted)", market),
            _block("Events already known", {"events": known}),
            f"Search news published since {since}. Status: 'nothing' if no relevant news; 'warning' if "
            "something deserves attention but the thesis holds; 'thesis_break' only for a clearly negative "
            "fundamental event (failed trial, regulator rejection, guidance cut, fraud, large dilution).",
        ]
    )
