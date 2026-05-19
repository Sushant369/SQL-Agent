import os
from openai import OpenAI
from dotenv import load_dotenv
from ambisql.utils.usage_monitor import build_usage_report

load_dotenv()

def _prompt_metrics(messages):
    normalized_messages = messages or []
    message_lengths = [
        len(str(message.get("content", "")))
        for message in normalized_messages
        if isinstance(message, dict)
    ]
    return {
        "message_count": len(normalized_messages),
        "total_characters": sum(message_lengths),
        "max_message_characters": max(message_lengths) if message_lengths else 0,
    }

class LLMCaller:
    def __init__(self, model, debug_logger=None, component="llm"):
        self.model = model
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens_used = 0
        self.request_count = 0
        self.debug_logger = debug_logger
        self.component = component
        api_key = os.getenv("OPENAI_API_KEY")
        if model == 'qwen':
            self.model = "qwen3-235b-a22b-instruct-2507"
            api_key = os.getenv("DASHSCOPE_API_KEY")
        elif model == 'claude':
            self.model = "claude-sonnet-4-5-20250929"
        elif model in ('gpt', 'gpt4o-mini'):
            self.model = "gpt-4o-mini"
        elif model == 'gemini':
            self.model = "gemini-2.5-pro"
        else:
            raise ValueError(
                f"Model {model} not recognized. Available models: 'qwen', 'claude', 'gpt', 'gpt4o-mini', 'gemini'"
            )

        # initialize a openai-like client via dashscope
        self.client = OpenAI(
            api_key=api_key,
            #base_url=os.getenv("OPENAI_API_BASE")
        )

    def call(self, query, temperature=0, operation="llm_call", metadata=None):
        print(f"Calling {self.model} with query: {query}")
        if self.model.startswith("claude"):
            max_tokens = 50000
        else:
            max_tokens = None
        request_kwargs = {
            "model": self.model,
            "messages": query,
        }
        if not self.model.startswith("gpt-5") and temperature is not None:
            request_kwargs["temperature"] = temperature
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens
        if self.debug_logger:
            self.debug_logger.log_event(
                component=self.component,
                event=f"{operation}_request",
                payload={
                    "model": self.model,
                    "temperature": temperature,
                    "metadata": metadata,
                    "prompt_metrics": _prompt_metrics(query),
                    "messages": query,
                },
            )

        try:
            response = self.client.chat.completions.create(**request_kwargs)
            print(f"Response: {response}")
            self.request_count += 1
            usage_payload = None
            if response.usage:
                prompt_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(response.usage, "completion_tokens", 0) or 0
                total_tokens = getattr(response.usage, "total_tokens", 0) or (
                    prompt_tokens + completion_tokens
                )
                self.total_tokens_used += total_tokens
                self.input_tokens += prompt_tokens
                self.output_tokens += completion_tokens
                usage_payload = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }

            content = response.choices[0].message.content
            if self.debug_logger:
                self.debug_logger.log_event(
                    component=self.component,
                    event=f"{operation}_response",
                    payload={
                        "model": self.model,
                        "metadata": metadata,
                        "prompt_metrics": _prompt_metrics(query),
                        "usage": usage_payload,
                        "content": content,
                    },
                )
            return content
        except Exception as exc:
            if self.debug_logger:
                self.debug_logger.log_exception(
                    component=self.component,
                    event=f"{operation}_failure",
                    exception=exc,
                    payload={
                        "model": self.model,
                        "temperature": temperature,
                        "metadata": metadata,
                        "prompt_metrics": _prompt_metrics(query),
                        "messages": query,
                    },
                )
            raise

    def get_total_tokens_used(self):
        return self.total_tokens_used, self.input_tokens, self.output_tokens

    def get_usage_report(self, label="Ambiguity workflow"):
        return build_usage_report(
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            requests=self.request_count,
            label=label,
        )

