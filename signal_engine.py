import json

from ollama import chat
from pydantic import BaseModel, Field
from typing import Literal


class TradeSignal(BaseModel):

    symbol: Literal[
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT"
    ]

    action: Literal[
        "LONG",
        "SHORT",
        "IGNORE"
    ]

    confidence: int = Field(
        ge=0,
        le=100
    )

    duration: Literal[
        "hours",
        "1-3 days",
        "3-7 days"
    ]

    reason: str


def analyze_news(headline, market):

    market_text = json.dumps(
        market,
        indent=2
    )

    prompt = f"""
You are a conservative crypto news trading classifier.

NEWS HEADLINE:
{headline}

LIVE MARKET DATA:
{market_text}

Analyze whether this news creates a NEW trading opportunity.

You may choose:
BTCUSDT
ETHUSDT
SOLUSDT

Actions:
LONG
SHORT
IGNORE

Important rules:

1. IGNORE is the default.
2. Do not force a trade.
3. Never invent facts beyond the provided headline.
4. Consider whether the headline is specific enough to act on.
5. Consider the current market reaction.
6. If the market has already made a very large move in the
   predicted direction, prefer IGNORE rather than chasing.
7. Small price movement after major news may mean the market
   has not fully reacted yet.
8. Confidence above 80 should be rare.
9. Choose the SINGLE clearest opportunity.
10. This is paper trading only.

Return the result using the required JSON structure.
"""

    response = chat(
        model="qwen3:4b",

        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],

        format=TradeSignal.model_json_schema(),

        options={
            "temperature": 0
        }
    )

    signal = TradeSignal.model_validate_json(
        response.message.content
    )

    return signal.model_dump()