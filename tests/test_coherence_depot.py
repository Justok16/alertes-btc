"""Garde-fous de coherence du depot (aucun reseau)."""

import unittest
from pathlib import Path

RACINE = Path(__file__).parent.parent


class TestMemoireSupabaseDupliquee(unittest.TestCase):
    def test_les_deux_copies_sont_identiques(self):
        # memoire_supabase.py existe en deux exemplaires (bot BTC a la racine,
        # bots trading-ct dans trading-ct/) : une correction appliquee a l'un
        # sans l'autre passerait inapercue. La CI refuse toute divergence.
        racine = (RACINE / "memoire_supabase.py").read_text(encoding="utf-8")
        trading_ct = (RACINE / "trading-ct" / "memoire_supabase.py").read_text(encoding="utf-8")
        self.assertEqual(racine, trading_ct,
                         "memoire_supabase.py et trading-ct/memoire_supabase.py divergent : "
                         "reporter la modification dans les deux fichiers")


if __name__ == "__main__":
    unittest.main()
