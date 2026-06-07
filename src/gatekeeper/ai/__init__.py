"""M2 AI layer — risk classification of tool calls via the ``LLMProvider`` port.

Runs ONLY on writes/risky calls (ADR-005). Reads never hit an LLM. The prompt is externalized and
versioned in ``../prompts/risk_classifier.yaml`` — never inline. Output is a typed RiskScore; on
classifier error the call fails closed to "requires approval".
"""
