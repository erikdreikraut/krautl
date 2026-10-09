"""Direct Wawi connection. TLS verification is mandatory outside loopback tests."""
import os
import ssl
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from .jtl_client import JtlFehler


class OnPremClient:
    def __init__(self, url, key, *, ca_file=None, transport=None):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or parsed.path.rstrip("/") != "/api/eazybusiness"):
            raise JtlFehler("JTL_LOCAL_URL muss https://HOST:PORT/api/eazybusiness sein.")
        if not key:
            raise JtlFehler("JTL_LOCAL_API_KEY fehlt.")
        self.url = url.rstrip("/")
        verify = ssl.create_default_context(cafile=ca_file) if ca_file else True
        self.http = httpx.AsyncClient(verify=verify, transport=transport, timeout=30,
            follow_redirects=False, trust_env=False,
            headers={"Authorization": "Wawi " + key,
                     "x-appid": "krautl-lokal", "x-appversion": "0.1.0"})

    @classmethod
    def aus_umgebung(cls):
        return cls(os.getenv("JTL_LOCAL_URL", ""), os.getenv("JTL_LOCAL_API_KEY", ""),
                   ca_file=os.getenv("JTL_LOCAL_CA_FILE") or None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.http.aclose()

    async def _request(self, method, path, **kwargs):
        try:
            response = await self.http.request(method, self.url + path, **kwargs)
        except httpx.HTTPError:
            raise JtlFehler("Direkte JTL-Verbindung fehlgeschlagen (TLS/Netz/Zeitlimit).") from None
        if response.status_code != 200:
            raise JtlFehler(f"Direkte JTL-API: HTTP {response.status_code}.")
        try:
            result = response.json()
        except ValueError:
            raise JtlFehler("JTL antwortet nicht mit JSON.") from None
        if not isinstance(result, dict):
            raise JtlFehler("Unerwartete JTL-Antwort.")
        return result

    async def katalog(self):
        result, gesehen = [], set()
        for page in range(1, 10001):
            data = await self._request("GET", "/v2/items", params={"pageNumber": page, "pageSize": 100})
            items = data.get("items")
            if not isinstance(items, list) or data.get("pageNumber") != page:
                raise JtlFehler("Ungültige JTL-Katalogseite.")
            for item in items:
                ident = str(UUID(item["id"]))
                if ident in gesehen:
                    raise JtlFehler("Doppelte Artikel-ID im JTL-Katalog.")
                gesehen.add(ident)
                result.append({"id": ident, "sku": item.get("sKU", item.get("sku")),
                               "parent": item.get("parentItemId")})
            if data.get("hasNextPage") is False:
                if len(result) != data.get("totalItems"):
                    raise JtlFehler("JTL-Katalog während Abruf verändert; nächster Lauf versucht erneut.")
                return result
            if not items or data.get("hasNextPage") is not True:
                raise JtlFehler("Unvollständige JTL-Paginierung.")
        raise JtlFehler("JTL-Katalog überschreitet Seitenlimit.")

    async def lesen(self, ident, sku):
        data = await self._request("GET", "/v2/items/" + str(UUID(ident)))
        if data.get("id") != ident or data.get("identifiers", {}).get("sku") != sku:
            raise JtlFehler("JTL-Artikel-ID oder SKU weicht von Zuordnung ab.")
        return data.get("attributes") or {"values": []}

    async def schreiben(self, ident, attributes):
        data = await self._request("PATCH", "/v2/items/" + str(UUID(ident)),
                                   json={"attributes": attributes})
        if data.get("item", {}).get("id") != ident:
            raise JtlFehler("JTL-Schreibantwort bestätigt nicht die erwartete Artikel-ID.")
