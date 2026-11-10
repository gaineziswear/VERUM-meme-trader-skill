import unittest
from index import _security

def safe_rug(top10=10.0, mint_authority=None, creator_balance="0"):
    return {
        "token": {"mintAuthority": mint_authority, "freezeAuthority": None, "supply": "1000000"},
        "creatorBalance": creator_balance,
        "risks": [],
        "topHolders": [{"pct": top10 / 10} for _ in range(10)],
        "markets": [{"lp": {"lpLockedPct": 100}}],
    }

def safe_goplus():
    return {
        "mintable": {"status": "0"}, "freezable": {"status": "0"},
        "balance_mutable_authority": {"status": "0"}, "closable": {"status": "0"},
        "non_transferable": "0", "transfer_fee": {}, "transfer_hook": [],
        "transfer_fee_upgradable": {"status": "0"},
        "transfer_hook_upgradable": {"status": "0"},
        "default_account_state_upgradable": {"status": "0"},
        "metadata_mutable": {"status": "0"}, "default_account_state": "1",
        "creators": [{"malicious_address": "0"}],
    }

class SecurityEvidenceTests(unittest.TestCase):
    def test_complete_clean_evidence_can_pass(self):
        result = _security(safe_rug(), safe_goplus(), {"liquidity": {"usd": 100000}})
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["dev_hold_pct"], 0)
        self.assertEqual(result["lp_locked_pct"], 100)

    def test_holder_concentration_causes_caution(self):
        result = _security(safe_rug(top10=32.9), safe_goplus(), {"liquidity": {"usd": 100000}})
        self.assertEqual(result["status"], "CAUTION")
        self.assertGreater(result["top10_holder_pct"], 20)

    def test_present_mint_authority_causes_avoid(self):
        result = _security(safe_rug(mint_authority="CreatorWallet"), safe_goplus(),
                           {"liquidity": {"usd": 100000}})
        self.assertEqual(result["status"], "AVOID")

    def test_missing_provider_data_is_unknown(self):
        result = _security(None, safe_goplus(), {"liquidity": {"usd": 100000}})
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertTrue(result["missing_evidence"])

if __name__ == "__main__":
    unittest.main()
