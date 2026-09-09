import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_worker_status.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from app.main import health
from app.worker_service import _status_fuer_ergebnis


class _Session:
    def __init__(self, worker):
        self.worker = worker

    async def get(self, _model, _key):
        return self.worker


class MailWorkerStatusTest(unittest.IsolatedAsyncioTestCase):
    async def test_frischer_fehler_wird_nicht_als_aktiv_gemeldet(self):
        jetzt = datetime.now(timezone.utc)
        worker = SimpleNamespace(
            status="teilweise_fehlerhaft",
            letzter_lauf=jetzt,
            letzter_erfolg=jetzt - timedelta(minutes=20),
            letzter_fehler=jetzt,
            detail="service: Anmeldung fehlgeschlagen",
        )

        ergebnis = await health(_Session(worker))

        self.assertTrue(ergebnis["mail_worker"]["laeuft"])
        self.assertFalse(ergebnis["mail_worker"]["aktiv"])

    async def test_nur_frischer_erfolgreicher_abruf_ist_aktiv(self):
        jetzt = datetime.now(timezone.utc)
        worker = SimpleNamespace(
            status="ok",
            letzter_lauf=jetzt,
            letzter_erfolg=jetzt,
            letzter_fehler=None,
            detail="0 neue Mail(s)",
        )

        ergebnis = await health(_Session(worker))

        self.assertTrue(ergebnis["mail_worker"]["laeuft"])
        self.assertTrue(ergebnis["mail_worker"]["aktiv"])

    def test_teilfehler_aktualisiert_den_letzten_erfolg_nicht(self):
        status = _status_fuer_ergebnis({
            "mails": 0,
            "fehler": ["service: Anmeldung fehlgeschlagen"],
            "erfolgreiche_postfaecher": 1,
        })

        self.assertEqual("teilweise_fehlerhaft", status["status"])
        self.assertFalse(status["erfolgreich"])
        self.assertTrue(status["fehler"])

    def test_vollstaendiger_abrufausfall_ist_worker_fehler(self):
        status = _status_fuer_ergebnis({
            "mails": 0,
            "fehler": ["service: Anmeldung fehlgeschlagen"],
            "erfolgreiche_postfaecher": 0,
        })

        self.assertEqual("fehler", status["status"])


if __name__ == "__main__":
    unittest.main()
