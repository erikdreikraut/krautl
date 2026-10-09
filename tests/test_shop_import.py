import unittest
from unittest.mock import patch

from app.shop_import import produktseite_auslesen, seitenzahl_ermitteln, artikelnummer_aus_detail, shop_katalog_laden


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
    def test_katalog_ergaenzt_nur_fehlende_nummern_aus_detail(self):
        katalog = HTML.replace('/_s3', '/_s1').replace('30014_weihrauch.png', 'weihrauch.png')
        with patch('app.shop_import._seite_laden', side_effect=[katalog, '<span itemprop="sku">00300-014</span>']) as laden:
            produkte = shop_katalog_laden()
        self.assertEqual(['00300-014', '20810'], [p.artikelnummer for p in produkte])
        self.assertEqual(2, laden.call_count)
        self.assertEqual('https://dreikraut.de/Weihrauch-Kapseln', laden.call_args.args[0])

    def test_explizite_sku_erhaelt_bindestriche_und_fuehrende_nullen(self):
        self.assertEqual("00447-000", artikelnummer_aus_detail('<span itemprop="sku">00447-000</span>'))
        self.assertEqual("40047-000", artikelnummer_aus_detail('<meta itemprop="sku" content="40047-000">'))
        self.assertIsNone(artikelnummer_aus_detail('<span itemprop="sku">A</span><span itemprop="sku">B</span>'))
        self.assertIsNone(artikelnummer_aus_detail('<img src="40047_spirulina.jpg">'))

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
