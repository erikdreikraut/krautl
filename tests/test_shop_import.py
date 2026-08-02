import unittest

from app.shop_import import produktseite_auslesen, seitenzahl_ermitteln


HTML = """
<a href="https://dreikraut.de/_s1">1</a>
<a href="https://dreikraut.de/_s3">3</a>
<div class="col product-wrapper" itemtype="https://schema.org/Product">
  <img src="https://dreikraut.de/media/image/product/4/sm/30014_weihrauch.png">
  <div class="productbox-title" itemprop="name">
    <a href="https://dreikraut.de/Weihrauch-Kapseln">Weihrauch Kapseln BIO</a>
  </div>
</div>
<div class="col product-wrapper" itemtype="https://schema.org/Product">
  <img src="https://dreikraut.de/media/image/product/5/sm/20810_hagebutte.png">
  <div class="productbox-title" itemprop="name">
    <a href="https://dreikraut.de/Hagebuttenpulver">Bio-Hagebuttenpulver</a>
  </div>
</div>
"""


class ShopImportTest(unittest.TestCase):
    def test_produkte_mit_artikelnummer_werden_ausgelesen(self):
        produkte = produktseite_auslesen(HTML)
        self.assertEqual(2, len(produkte))
        self.assertEqual("Weihrauch Kapseln BIO", produkte[0].name)
        self.assertEqual("30014", produkte[0].artikelnummer)
        self.assertEqual("https://dreikraut.de/Hagebuttenpulver", produkte[1].website_url)

    def test_letzte_seite_wird_erkannt(self):
        self.assertEqual(3, seitenzahl_ermitteln(HTML))


if __name__ == "__main__":
    unittest.main()
