import unittest
from scripts.pruefe_bilder_vollstaendigkeit import vergleich


class VollstaendigkeitTest(unittest.TestCase):
    def test_missing_hidden_and_stale_are_distinguished(self):
        def uid(n):return f"00000000-0000-0000-0000-{n:012d}"
        stand={"artikel":[{"id":uid(1),"sku":"A","ausgeblendet":True,"bilder":[]},
                          {"id":uid(3),"sku":"C","ausgeblendet":False,"bilder":[{"thumb":"x","quelle":"ameise"},{"thumb":None}]}]}
        rows=[{"id":uid(n),"sKU":str(n),"isActive":True,"isShopActive":True} for n in (1,2)]
        result=vergleich(stand,rows)
        self.assertEqual([r["sku"] for r in result["fehlende_artikel"]],["2"])
        self.assertEqual([r["sku"] for r in result["lokal_nicht_mehr_shopaktiv"]],["C"])
        self.assertEqual(result["fehlende_vorschauen"],1)
        self.assertEqual(result["exportvorschauen"],1)
        self.assertEqual(result["davon_ausgeblendet"],1)
