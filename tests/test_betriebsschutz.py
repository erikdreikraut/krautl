import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class BetriebsschutzTest(unittest.TestCase):
    def test_frontend_hat_restart_policy_und_healthcheck(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        frontend = compose.split("  frontend:\n", 1)[1].split("\nvolumes:", 1)[0]
        self.assertIn("restart: unless-stopped", frontend)
        self.assertIn("healthcheck:", frontend)
        self.assertIn("http://127.0.0.1/", frontend)

    def test_waechter_prueft_den_vollstaendigen_verbund(self):
        waechter = (ROOT / "scripts" / "krautl_guardian.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("for dienst in db app worker frontend", waechter)
        self.assertIn('docker compose ps -q "$dienst"', waechter)
        self.assertIn("docker compose up -d --no-build", waechter)
        self.assertIn('gesundheit" = "unhealthy', waechter)

    def test_timer_startet_nach_boot_und_prueft_alle_zwei_minuten(self):
        timer = (ROOT / "ops" / "krautl-guardian.timer").read_text(
            encoding="utf-8"
        )
        service = (ROOT / "ops" / "krautl-guardian.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("OnBootSec=1min", timer)
        self.assertIn("OnUnitActiveSec=2min", timer)
        self.assertIn("WantedBy=timers.target", timer)
        self.assertIn("Requires=docker.service", service)
        self.assertIn("scripts/krautl_guardian.sh", service)


if __name__ == "__main__":
    unittest.main()
