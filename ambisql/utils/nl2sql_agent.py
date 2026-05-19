import os
from openai import OpenAI
from dotenv import load_dotenv

from ambisql.prompts.xiyan_template_prompt import xiyan_template_en
from ambisql.utils.usage_monitor import build_usage_report

load_dotenv()

def _prompt_metrics(messages):
    message_lengths = [
        len(str(message.get("content", "")))
        for message in (messages or [])
        if isinstance(message, dict)
    ]
    return {
        "message_count": len(messages or []),
        "total_characters": sum(message_lengths),
        "max_message_characters": max(message_lengths) if message_lengths else 0,
    }

class XiYanAgent:
    def __init__(self, debug_logger=None):
        self.model = "gpt-4o-mini"
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens_used = 0
        self.request_count = 0
        self.debug_logger = debug_logger
        self.client = OpenAI(
        #base_url=os.environ.get("MODELSCOPE_API_BASE"),# ModelScope Inference API Base URL
        api_key=os.environ.get("OPENAI_API_KEY"), # ModelScope API Key
    )

    def generate_sql(self, question, evidence, schema):
        prompt_with_evidence = xiyan_template_en.format(
            dialect="SQLite",
            question=question,
            db_schema=schema,
            evidence= evidence
        )

        messages = [
            {
                'role': 'system',
                'content': 'You are a helpful assistant to generate SQL queries bases on the database schema and the user question.'
            },
            {
                'role': 'user',
                'content': prompt_with_evidence
            }
        ]

        if self.debug_logger:
            self.debug_logger.log_event(
                component="sql_generation",
                event="sql_generation_request",
                payload={
                    "model": self.model,
                    "question": question,
                    "evidence": evidence,
                    "prompt_metrics": _prompt_metrics(messages),
                    "messages": messages,
                },
            )

        try:
            response_clarified = self.client.chat.completions.create(
                model=self.model,
                messages=messages
            )
            self.request_count += 1
            usage_payload = None
            if response_clarified.usage:
                prompt_tokens = getattr(response_clarified.usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(response_clarified.usage, "completion_tokens", 0) or 0
                total_tokens = getattr(response_clarified.usage, "total_tokens", 0) or (
                    prompt_tokens + completion_tokens
                )
                self.input_tokens += prompt_tokens
                self.output_tokens += completion_tokens
                self.total_tokens_used += total_tokens
                usage_payload = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }

            content = response_clarified.choices[0].message.content
            if self.debug_logger:
                self.debug_logger.log_event(
                    component="sql_generation",
                    event="sql_generation_response",
                    payload={
                        "model": self.model,
                        "prompt_metrics": _prompt_metrics(messages),
                        "usage": usage_payload,
                        "content": content,
                    },
                )
            return content
        except Exception as exc:
            if self.debug_logger:
                self.debug_logger.log_exception(
                    component="sql_generation",
                    event="sql_generation_failure",
                    exception=exc,
                    payload={
                        "model": self.model,
                        "question": question,
                        "evidence": evidence,
                        "prompt_metrics": _prompt_metrics(messages),
                        "messages": messages,
                    },
                )
            raise

    def get_usage_report(self, label="SQL generation"):
        return build_usage_report(
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            requests=self.request_count,
            label=label,
        )
