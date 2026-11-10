import unittest
import index

class ApiContractTests(unittest.TestCase):
    def test_fastapi_app_imports(self):
        self.assertEqual(index.app.title, "VERUM Meme Intelligence API")

    def test_health_and_provider_routes_exist(self):
        paths = {route.path for route in index.app.routes}
        self.assertIn("/api/v1/health", paths)
        self.assertIn("/api/v1/providers", paths)
        self.assertIn("/api/v1/radar", paths)

    def test_paper_and_integration_routes_exist(self):
        methods = {(route.path, method) for route in index.app.routes
                   for method in getattr(route, "methods", set())}
        self.assertIn(("/api/v1/paper/trades", "POST"), methods)
        self.assertIn(("/api/v1/integration/signals", "GET"), methods)
        self.assertIn(("/api/v1/integration/paper/results", "GET"), methods)

    def test_no_live_trade_route(self):
        paths = {route.path for route in index.app.routes}
        self.assertFalse(any("live" in path.lower() or "execute" in path.lower()
                             for path in paths))

if __name__ == "__main__":
    unittest.main()
