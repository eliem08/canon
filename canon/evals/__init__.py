"""Before/after eval: agent accuracy on raw files vs. on Canon's MCP tools."""

from canon.evals.harness import render_report, run_eval
from canon.evals.models import ClaudeModel, OpenAICompatibleModel, StubModel

__all__ = ["ClaudeModel", "OpenAICompatibleModel", "StubModel", "render_report", "run_eval"]
