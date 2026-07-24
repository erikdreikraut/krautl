"""Einmalige interaktive Dropbox-Anmeldung für den Krautl-Server.

Voraussetzung: DROPBOX_APP_KEY und DROPBOX_APP_SECRET sind im Container gesetzt.
Das Skript zeigt einen Link, nimmt den einmaligen Dropbox-Code entgegen und
gibt den dauerhaft nutzbaren Refresh Token aus. Es speichert keine Geheimnisse.
"""
import os

from dropbox import DropboxOAuth2FlowNoRedirect


def anmelden() -> None:
    app_key = os.getenv("DROPBOX_APP_KEY")
    app_secret = os.getenv("DROPBOX_APP_SECRET")
    if not app_key or not app_secret:
        raise RuntimeError(
            "DROPBOX_APP_KEY und DROPBOX_APP_SECRET müssen zuerst in Elestio "
            "hinterlegt und der App-Container neu gestartet werden."
        )

    flow = DropboxOAuth2FlowNoRedirect(
        app_key,
        app_secret,
        token_access_type="offline",
    )
    print("\n1. Öffne diesen Link im Browser:\n")
    print(flow.start())
    print(
        "\n2. Melde dich bei Dropbox an und erlaube Krautl den Zugriff.\n"
        "3. Kopiere den einmaligen Code von Dropbox hierher.\n"
    )
    code = input("Dropbox-Code: ").strip()
    if not code:
        raise RuntimeError("Kein Dropbox-Code eingegeben.")

    ergebnis = flow.finish(code)
    if not ergebnis.refresh_token:
        raise RuntimeError(
            "Dropbox hat keinen Refresh Token geliefert. Bitte prüfen, ob "
            "die Anmeldung mit dauerhaftem Hintergrundzugriff erlaubt wurde."
        )

    print("\nAnmeldung erfolgreich.")
    print(
        "Kopiere den folgenden Wert als DROPBOX_REFRESH_TOKEN in Elestio. "
        "Nicht in den Chat oder ins Git-Repository einfügen:\n"
    )
    print(ergebnis.refresh_token)


if __name__ == "__main__":
    anmelden()
