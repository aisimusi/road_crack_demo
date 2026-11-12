from __future__ import annotations

from pathlib import Path
import sys
import unittest

PROJECT_BACKEND = Path(__file__).resolve().parents[1]
if str(PROJECT_BACKEND) not in sys.path:
    sys.path.insert(0, str(PROJECT_BACKEND))

from app.agent.tool_registry import build_default_registry  # noqa: E402


class AgentRegistryTestCase(unittest.TestCase):
    def test_openai_tools_schema_contains_new_tools(self) -> None:
        registry = build_default_registry()
        tools_schema = registry.openai_tools()
        names = [item["function"]["name"] for item in tools_schema]

        self.assertIn("resolve_query_context", names)
        self.assertIn("rank_roads_by_risk", names)
        self.assertIn("find_high_risk_cracks", names)
        self.assertIn("analyze_surrounding_pois", names)

        for item in tools_schema:
            self.assertEqual(item["type"], "function")
            self.assertTrue(item["function"]["name"])
            self.assertIn("parameters", item["function"])


if __name__ == "__main__":
    unittest.main()
