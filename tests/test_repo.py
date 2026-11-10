import json
import os
import re
import unittest

from _load import ROOT

SKILLS = ["meme-scanner", "meme-radar", "meme-news", "meme-entry", "meme-exit", "meme-timemachine", "meme-risk",
          "meme-budget", "meme-broker", "meme-alerts", "meme-analyst", "meme-whales", "meme-journal"]
ABOUT = ("13 Claude skills for meme coin trading: scan the coins in play, catch new launches the second they go live, "
         "rug-check every one, time every entry and exit, replay every outcome after fees before you risk a dollar, "
         "and keep an honest journal of the real trades.")
# skills on the way to a trade carry the full safety block
ORDER_PATH = ["meme-scanner", "meme-radar", "meme-entry", "meme-exit", "meme-timemachine", "meme-budget", "meme-risk",
              "meme-broker", "meme-alerts", "meme-whales", "meme-journal"]


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


def every_text_file():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".txt", ".xml")) or f == "LICENSE":
                yield os.path.join(base, f)


class Repo(unittest.TestCase):
    def test_thirteen_skill_folders_at_the_root(self):
        found = sorted(d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_root(self):
        root = sorted(d for d in os.listdir(ROOT) if not d.startswith(".git"))
        self.assertEqual(root, sorted([".claude-plugin", "LICENSE", "README.md", "tests", "platform"] + SKILLS))

    def test_frontmatter_name_and_description(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 300, "%s description is too thin" % s)
            self.assertLess(len(fm), 1400, "%s description is too long" % s)
            self.assertGreater(len(text.splitlines()), 80, s)
            self.assertIn("${CLAUDE_SKILL_DIR}", text, s)

    def test_every_skill_says_not_financial_advice(self):
        for s in SKILLS:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            self.assertIn("not financial advice", low, s)
            self.assertIn("seed phrase", low, s)
            self.assertIn("yes", low, s)

    def test_order_path_skills_carry_the_full_safety_block(self):
        for s in ORDER_PATH:
            _, text = frontmatter(os.path.join(ROOT, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            for line in ("paper trading by default", "never connects to a wallet",
                         "the user typed an explicit yes for that one order in the chat",
                         "no leverage, perps or short selling"):
                self.assertIn(line, low, "%s: %s" % (s, line))

    def test_every_skill_has_a_tool_and_a_test(self):
        for s in SKILLS:
            tools = [f for f in os.listdir(os.path.join(ROOT, s)) if f.endswith(".py")]
            self.assertEqual(len(tools), 1, s)
            self.assertTrue(os.path.exists(os.path.join(ROOT, "tests", "test_%s.py" % s.split("-", 1)[1])), s)

    def test_plugin_manifest_points_at_the_root_skills(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["name"], "meme-trader-skill")
        self.assertEqual(plugin["skills"], "./")
        self.assertEqual(plugin["description"], ABOUT)
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as fh:
            market = json.load(fh)
        self.assertEqual(market["name"], "meme-trader-skill")
        self.assertEqual(market["plugins"][0]["name"], "meme-trader-skill")
        self.assertEqual(market["plugins"][0]["source"], "./")

    def test_readme(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertTrue(readme.startswith("# Der Meme Trader Skill"))
        for line in (ABOUT, "/plugin marketplace add bn194/meme-trader-skill",
                     "/plugin install meme-trader-skill@meme-trader-skill", "## Kleingedrucktes",
                     "Keine Finanzberatung", "python3 -m unittest discover -s tests -v"):
            self.assertTrue(line in readme, "README misses: %s" % line)
        for s in SKILLS:
            self.assertTrue("/" + s in readme, s)

    def test_no_em_dashes_and_no_keys(self):
        for path in every_text_file():
            rel = os.path.relpath(path, ROOT)
            if rel.startswith(os.path.join("tests", "fixtures")):
                continue  # fixtures are real data, kept as published
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            self.assertNotIn(chr(0x2014), text, rel)  # no em dashes
            self.assertNotRegex(text, r"(?i)(private[_ ]?key|secret[_ ]?key|seed[_ ]?phrase)\s*[:=]\s*['\"][^'\"]{8,}", rel)

    def test_every_tool_runs_on_python_3_8(self):
        for s in SKILLS:
            folder = os.path.join(ROOT, s)
            for f in os.listdir(folder):
                if not f.endswith(".py"):
                    continue
                with open(os.path.join(folder, f), encoding="utf-8") as fh:
                    src = fh.read()
                for bad in ("import zoneinfo", "from zoneinfo", ".removeprefix(", ".removesuffix(", "list[", "dict[",
                            "tuple[", "set[", ":=", "| None"):
                    if bad.endswith("["):
                        self.assertNotRegex(src, r"(?<![\w.\"'])%s" % re.escape(bad), "%s/%s" % (s, f))
                    else:
                        self.assertNotIn(bad, src, "%s/%s" % (s, f))
                self.assertNotRegex(src, r"(?m)^\s+match \w+.*:$", "%s/%s" % (s, f))
                self.assertNotRegex(src, r"(?m)^import (requests|httpx|aiohttp|solana|solders|web3)", "%s/%s" % (s, f))

    def test_the_example_config_is_safe_by_default(self):
        with open(os.path.join(ROOT, "meme-budget", "config.example.json")) as fh:
            cfg = json.load(fh)
        for k in ("max_loss_per_trade_usd", "max_daily_loss_usd", "max_trades_per_day", "min_reward_risk",
                  "require_stop", "require_edge", "require_safety", "max_hold_minutes", "losing_streak_pause",
                  "fee_pct", "fee_min_usd", "slippage_pct", "pool_fee_pct", "min_liquidity_usd", "timezone"):
            self.assertIn(k, cfg, k)
        self.assertIs(cfg["paper"], True)
        self.assertIs(cfg["require_stop"], True)
        self.assertIs(cfg["require_safety"], True)
        self.assertIs(cfg["require_edge"], True)
        self.assertIs(cfg["allow_leverage"], False)
        self.assertIs(cfg["allow_perps"], False)
        self.assertIs(cfg["allow_short"], False)
        self.assertLessEqual(cfg["max_loss_per_trade_usd"], cfg["budget_usd"] * 0.05)
        self.assertLessEqual(cfg["testphase_max_order_usd"], cfg["max_order_usd"])
        self.assertEqual(cfg["testphase_trades"], 20)
        self.assertEqual(cfg["currency"], "EUR")
        self.assertIn(cfg["venue"], cfg["venues"])
        for v in cfg["venues"].values():
            self.assertTrue(v["note"])

    def test_no_tool_handles_keys_or_signs(self):
        for s in SKILLS:
            folder = os.path.join(ROOT, s)
            for f in os.listdir(folder):
                if f.endswith(".py"):
                    with open(os.path.join(folder, f), encoding="utf-8") as fh:
                        src = fh.read().lower()
                    for bad in ("sendtransaction", "signtransaction", "keypair", "secretkey", "mnemonic", "/swap/v1/swap\""):
                        self.assertNotIn(bad, src, "%s/%s: %s" % (s, f, bad))


if __name__ == "__main__":
    unittest.main()
