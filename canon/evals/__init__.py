"""Before/after eval: agent accuracy on raw files vs. on Canon's MCP tools."""

from canon.evals.harness import render_report, run_eval
from canon.evals.models import ClaudeModel, StubModel

__all__ = ["ClaudeModel", "StubModel", "render_report", "run_eval"]
