"""Tests de non-regression pour memoire_supabase.py -- migration du 04/09/2026
(etat des bots persiste dans Supabase plutot que commite en Git a chaque
cycle). Stdlib uniquement (unittest.mock), aucune nouvelle dependance de
test -- ce depot n'avait jusqu'ici aucune suite de tests (CI = pyflakes
seul), premiere introduite ici vu la criticite du changement (bot en prod,
cron 5 min pour trading-ct-alert.yml)."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import memoire_supabase  # noqa: E402


def _reponse(status_code=200, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else []
    if status_code >= 400:
        import requests
        r.raise_for_status.side_effect = requests.HTTPError(f"{status_code}")
    else:
        r.raise_for_status.return_value = None
    return r


class TestChargerEtatSupabase(unittest.TestCase):
    def test_sans_secrets_retourne_none(self):
        self.assertIsNone(memoire_supabase.charger_etat_supabase("cle", "", ""))
        self.assertIsNone(memoire_supabase.charger_etat_supabase("cle", "https://x.supabase.co", ""))

    @patch("memoire_supabase.requests.get")
    def test_premiere_execution_retourne_dict_vide(self, mock_get):
        mock_get.return_value = _reponse(json_data=[])
        etat = memoire_supabase.charger_etat_supabase("cle", "https://x.supabase.co", "service_role")
        self.assertEqual(etat, {})

    @patch("memoire_supabase.requests.get")
    def test_etat_existant_est_retourne(self, mock_get):
        mock_get.return_value = _reponse(json_data=[{"donnees": {"combined_state": "buy"}}])
        etat = memoire_supabase.charger_etat_supabase("cle", "https://x.supabase.co", "service_role")
        self.assertEqual(etat, {"combined_state": "buy"})

    @patch("memoire_supabase.time.sleep", lambda *_: None)
    @patch("memoire_supabase.requests.get")
    def test_erreur_reseau_persistante_retourne_none(self, mock_get):
        import requests
        mock_get.side_effect = requests.ConnectionError("boom")
        etat = memoire_supabase.charger_etat_supabase("cle", "https://x.supabase.co", "service_role")
        self.assertIsNone(etat)
        self.assertEqual(mock_get.call_count, memoire_supabase.TENTATIVES)

    @patch("memoire_supabase.time.sleep", lambda *_: None)
    @patch("memoire_supabase.requests.get")
    def test_erreur_transitoire_puis_succes_ne_perd_pas_letat(self, mock_get):
        # Le retry (meme principe que memoire_supabase.py cote pokedeals,
        # ajoute suite a un vrai timeout observe en prod) ne doit pas faire
        # abandonner le cycle pour un simple hoquet reseau.
        import requests
        mock_get.side_effect = [requests.ConnectionError("boom"), _reponse(json_data=[{"donnees": {"a": 1}}])]
        etat = memoire_supabase.charger_etat_supabase("cle", "https://x.supabase.co", "service_role")
        self.assertEqual(etat, {"a": 1})


class TestSauvegarderEtatSupabase(unittest.TestCase):
    def test_sans_secrets_retourne_false(self):
        self.assertFalse(memoire_supabase.sauvegarder_etat_supabase({"a": 1}, "cle", "", ""))

    @patch("memoire_supabase.requests.post")
    def test_succes_retourne_true(self, mock_post):
        mock_post.return_value = _reponse()
        ok = memoire_supabase.sauvegarder_etat_supabase({"a": 1}, "cle", "https://x.supabase.co", "service_role")
        self.assertTrue(ok)
        # Verifie l'upsert (on_conflict=cle) et la cle envoyee -- une carte
        # active resterait exclue si la cle etait mal transmise a l'API.
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["params"], {"on_conflict": "cle"})
        self.assertEqual(kwargs["json"]["cle"], "cle")
        self.assertEqual(kwargs["json"]["donnees"], {"a": 1})

    @patch("memoire_supabase.time.sleep", lambda *_: None)
    @patch("memoire_supabase.requests.post")
    def test_echec_reseau_retourne_false(self, mock_post):
        import requests
        mock_post.side_effect = requests.ConnectionError("boom")
        ok = memoire_supabase.sauvegarder_etat_supabase({"a": 1}, "cle", "https://x.supabase.co", "service_role")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
