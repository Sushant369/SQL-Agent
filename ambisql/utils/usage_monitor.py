MODEL_PRICING = {
    "gpt-5-2025-08-07": {
        "pricing_model": "GPT-5",
        "input_per_million": 1.25,
        "output_per_million": 10.00,
    },
    "gpt-4o-mini": {
        "pricing_model": "GPT-4o mini",
        "input_per_million": 0.15,
        "output_per_million": 0.60,
    },
}


def build_usage_report(model, input_tokens=0, output_tokens=0, requests=0, label=None):
    total_tokens = input_tokens + output_tokens
    pricing = MODEL_PRICING.get(model)

    if pricing:
        input_cost = (input_tokens / 1_000_000) * pricing["input_per_million"]
        output_cost = (output_tokens / 1_000_000) * pricing["output_per_million"]
        estimated_cost = input_cost + output_cost
        pricing_available = True
        pricing_model = pricing["pricing_model"]
    else:
        input_cost = 0.0
        output_cost = 0.0
        estimated_cost = 0.0
        pricing_available = False
        pricing_model = "Not started" if model == "not-run" else model

    return {
        "label": label or model,
        "model": model,
        "pricing_model": pricing_model,
        "requests": requests,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "input_cost_usd": round(input_cost, 6),
        "output_cost_usd": round(output_cost, 6),
        "estimated_cost_usd": round(estimated_cost, 6),
        "pricing_available": pricing_available,
    }


def empty_usage_report(label):
    return build_usage_report(
        model="not-run",
        input_tokens=0,
        output_tokens=0,
        requests=0,
        label=label,
    )


def combine_usage_reports(reports, label="Session total"):
    valid_reports = [report for report in reports if report]

    return {
        "label": label,
        "model": "multiple",
        "pricing_model": "Multiple models",
        "requests": sum(report.get("requests", 0) for report in valid_reports),
        "input_tokens": sum(report.get("input_tokens", 0) for report in valid_reports),
        "output_tokens": sum(report.get("output_tokens", 0) for report in valid_reports),
        "total_tokens": sum(report.get("total_tokens", 0) for report in valid_reports),
        "input_cost_usd": round(
            sum(report.get("input_cost_usd", 0.0) for report in valid_reports), 6
        ),
        "output_cost_usd": round(
            sum(report.get("output_cost_usd", 0.0) for report in valid_reports), 6
        ),
        "estimated_cost_usd": round(
            sum(report.get("estimated_cost_usd", 0.0) for report in valid_reports), 6
        ),
        "pricing_available": all(
            report.get("pricing_available", False) for report in valid_reports
        ),
    }
