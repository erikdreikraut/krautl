"""Read-only setup client for Krautl's own JTL Cloud service account.

No attribute writes are enabled until the tenant-specific mapping and PATCH
semantics have been verified. Credentials never leave this backend.
"""
import asyncio
import os
import time
from uuid import UUID

import httpx

ERP_URL = "https://api.jtl-cloud.com/erp"
TOKEN_URL = "https://id.jtl-cloud.com/oauth/v2/token"
SKU_QUERY = """query($sku: String!) {
  QueryItems(first: 2, where: {sku: {eq: $sku}}) {
    nodes { id sku }
    pageInfo { hasNextPage }
  }
}"""


class JtlFehler(RuntimeError):
    """A sanitized error that may be shown to an operator."""


class JtlClient:
    def __init__(self, client_id, client_secret, tenant_id, transport=None):
        if not client_id or not client_secret:
            raise JtlFehler("JTL_CLIENT_ID und JTL_CLIENT_SECRET fehlen.")
        try:
            self.tenant_id = str(UUID(tenant_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise JtlFehler("JTL_TENANT_ID muss die bestätigte ERP-Tenant-UUID sein.") from exc
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = httpx.AsyncClient(timeout=30, transport=transport, follow_redirects=False)
        self.token = None
        self.token_bis = 0
        self.token_lock = asyncio.Lock()

    @classmethod
    def aus_umgebung(cls):
        return cls(os.environ.get("JTL_CLIENT_ID", ""), os.environ.get("JTL_CLIENT_SECRET", ""),
                   os.environ.get("JTL_TENANT_ID", ""))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.http.aclose()

    @staticmethod
    def _json(response):
        try:
            data = response.json()
        except ValueError as exc:
            raise JtlFehler("JTL hat keine gültige JSON-Antwort geliefert.") from exc
        if not isinstance(data, dict):
            raise JtlFehler("Unerwartete JTL-Antwortstruktur.")
        return data

    async def _token(self):
        async with self.token_lock:
            if self.token and time.monotonic() < self.token_bis:
                return self.token
            try:
                response = await self.http.post(TOKEN_URL,
                    auth=httpx.BasicAuth(self.client_id, self.client_secret),
                    data={"grant_type": "client_credentials", "scope": "openid"})
            except httpx.HTTPError as exc:
                raise JtlFehler("JTL-Token konnte nicht abgerufen werden (Verbindung/Zeitlimit).") from exc
            if response.status_code != 200:
                raise JtlFehler(f"JTL-Authentifizierung fehlgeschlagen (HTTP {response.status_code}).")
            data = self._json(response)
            token = data.get("access_token")
            try:
                dauer = float(data["expires_in"])
            except (KeyError, TypeError, ValueError) as exc:
                raise JtlFehler("JTL-Tokenlaufzeit fehlt oder ist ungültig.") from exc
            if not isinstance(token, str) or not token or not 0 < dauer < 86400 * 30:
                raise JtlFehler("JTL-Tokenantwort ist unvollständig.")
            self.token, self.token_bis = token, time.monotonic() + max(0, dauer - 60)
            return token

    async def _lesen(self, path, query=None):
        # Only these two fixed read operations are allowed, including POST GraphQL.
        for versuch in range(2):
            token = await self._token()
            headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": self.tenant_id}
            try:
                if query is None:
                    response = await self.http.get(ERP_URL + path, headers=headers)
                else:
                    response = await self.http.post(ERP_URL + path, headers=headers, json=query)
            except httpx.HTTPError as exc:
                raise JtlFehler("JTL-Lesezugriff fehlgeschlagen (Verbindung/Zeitlimit).") from exc
            if response.status_code == 401 and versuch == 0:
                self.token = None
                continue
            if response.status_code != 200:
                raise JtlFehler(f"JTL-Lesezugriff fehlgeschlagen (HTTP {response.status_code}). Installation, Tenant und items.read prüfen.")
            return self._json(response)
        raise JtlFehler("JTL-Anmeldung fehlgeschlagen.")

    async def artikel_lesen(self, artikelnummer):
        sku = artikelnummer.strip()
        if not sku:
            raise JtlFehler("Eine genaue Artikelnummer ist erforderlich.")
        data = await self._lesen("/v2/graphql", {"query": SKU_QUERY, "variables": {"sku": sku}})
        if data.get("errors"):
            raise JtlFehler("JTL-GraphQL meldet einen Fehler; keine Artikelzuordnung möglich.")
        ergebnis = (data.get("data") or {}).get("QueryItems")
        if not isinstance(ergebnis, dict):
            raise JtlFehler("JTL hat keine Artikelabfrage geliefert.")
        nodes = ergebnis.get("nodes")
        mehr = (ergebnis.get("pageInfo") or {}).get("hasNextPage")
        if not isinstance(nodes, list) or len(nodes) != 1 or mehr not in (False, 0) or mehr is None:
            raise JtlFehler("Artikelnummer nicht eindeutig gefunden; kein Zugriff auf einen geratenen Artikel.")
        artikel = nodes[0]
        if not isinstance(artikel, dict) or artikel.get("sku") != sku:
            raise JtlFehler("JTL-Artikelnummer stimmt nicht exakt überein.")
        try:
            ident = str(UUID(artikel["id"]))
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise JtlFehler("JTL lieferte keine gültige V2-Artikel-UUID.") from exc
        details = await self._lesen(f"/v2/items/{ident}")
        if details.get("id", "").lower() != ident or (details.get("identifiers") or {}).get("sku") != sku:
            raise JtlFehler("Die gelesenen Artikeldetails passen nicht zur Artikelnummer.")
        return details
