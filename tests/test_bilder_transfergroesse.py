import random,unittest
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from app.bilder_upload import datei_pruefen,dateiendung

class TransferSizeTest(unittest.TestCase):
 def noise(self,alpha=False):
  mode='RGBA' if alpha else 'RGB'
  im=Image.frombytes(mode,(96,96),random.Random(7).randbytes(96*96*(4 if alpha else 3)))
  out=BytesIO();im.save(out,'PNG');return out.getvalue()
 def test_large_opaque_png_uses_matching_jpeg_without_resizing(self):
  raw=self.noise()
  with patch('app.bilder_upload.MAX_TRANSFER_BYTES',len(raw)-1):result=datei_pruefen(raw)
  self.assertEqual(dateiendung(result),'.jpg')
  self.assertLess(len(result),len(raw))
  with Image.open(BytesIO(result)) as im:self.assertEqual(im.size,(96,96));self.assertEqual(im.format,'JPEG')
 def test_large_transparent_image_is_rejected_not_flattened(self):
  with patch('app.bilder_upload.MAX_TRANSFER_BYTES',100):
   with self.assertRaises(ValueError):datei_pruefen(self.noise(alpha=True))
 def test_even_jpeg_must_fit_limit(self):
  with patch('app.bilder_upload.MAX_TRANSFER_BYTES',100):
   with self.assertRaises(ValueError):datei_pruefen(self.noise())
 def test_palette_transparency_survives(self):
  im=Image.new('P',(12,12));im.info['transparency']=0
  out=BytesIO();im.save(out,'PNG');result=datei_pruefen(out.getvalue())
  self.assertEqual(dateiendung(result),'.png')
  with Image.open(BytesIO(result)) as restored:self.assertEqual(restored.convert('RGBA').getchannel('A').getextrema(),(0,0))
