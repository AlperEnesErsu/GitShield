import os
from typing import Optional
import httpx
from gitshield.ai.prompts import SYSTEM_REMEDIATION_PROMPT, USER_REMEDIATION_TEMPLATE
from gitshield.core.models import Finding, RuleType


class AIRemediator:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = (
            api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )

    def generate_fix(self, finding: Finding) -> str:
        """Generate an AI-driven safe remediation patch for a finding."""
        # 1. Sanitize/redact context if it contains secret
        safe_context = finding.context or finding.matched_text
        if finding.rule_type in (RuleType.SECRET, RuleType.ENTROPY):
            safe_context = safe_context.replace(finding.matched_text, "<REDACTED_SECRET>")

        prompt = USER_REMEDIATION_TEMPLATE.format(
            file_path=finding.file_path,
            line_number=finding.line_number,
            rule_id=finding.rule_id,
            title=finding.title,
            severity=finding.severity.value,
            cwe=finding.cwe or "N/A",
            context=safe_context,
        )

        if not self.api_key:
            # Fallback heuristic advice if no LLM key is configured
            return finding.suggested_fix or "Use environment variables or parameterized inputs."

        # Support Gemini API via direct HTTP
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"text": f"{SYSTEM_REMEDIATION_PROMPT}\n\n{prompt}"}
                            ]
                        }
                    ]
                }
                with httpx.Client(timeout=15.0) as client:
                    resp = client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as e:
                return f"LLM error: {e}. Default advice: {finding.suggested_fix}"

        return finding.suggested_fix or "Review code security according to best practices."
