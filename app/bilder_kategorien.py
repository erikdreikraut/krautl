"""Read-only shop category resolution, cached for one image sync."""
from .jtl_client import JtlFehler

SHOP = "2-2-1"


class ShopKategorien:
    def __init__(self, client):
        self.client = client
        self.index = None
        self.fehler = None
        self.cache = {}
        self.v1 = False

    async def laden(self):
        if self.fehler:
            raise JtlFehler(self.fehler)
        if self.index is not None:
            return
        index = {}
        try:
            total = None
            for page in range(1, 10001):
                data = await self.client._request("GET", "/v2/categories", params={"pageNumber": page, "pageSize": 100})
                rows = data.get("items")
                if (not isinstance(rows, list) or data.get("pageNumber") != page
                        or type(data.get("totalItems")) is not int
                        or (total is not None and total != data["totalItems"])):
                    raise JtlFehler("Unvollständiger Kategorie-Katalog.")
                total = data["totalItems"]
                for row in rows:
                    key = row.get("id")
                    if not isinstance(key, str) or key in index or not isinstance(row.get("name"), str):
                        raise JtlFehler("Uneindeutige Kategorie im Katalog.")
                    index[key] = row
                if data.get("hasNextPage") is False and len(index) == total:
                    self.index = index
                    return
                if not rows or data.get("hasNextPage") is not True:
                    break
            raise JtlFehler("Unvollständiger Kategorie-Katalog.")
        except JtlFehler as exc:
            if "HTTP 400" in str(exc):
                self.v1 = True
                self.index = {}
                return
            self.fehler = str(exc)
            raise

    async def pfad(self, key, besucht=()):
        if key in besucht or len(besucht) >= 30:
            raise JtlFehler("Ungültige Kategorie-Hierarchie.")
        if key in self.cache:
            result = self.cache[key]
            if isinstance(result, Exception):
                raise result
            return result
        try:
            row = self.index.get(key)
            if not row:
                raise JtlFehler("Zugeordnete Kategorie fehlt im Katalog.")
            detail = await self.client._request("GET", "/v2/categories/" + key)
            channels = detail.get("activeSalesChannelIds")
            # Some schema versions declare a string; accept only an exact single channel.
            if isinstance(channels, str):
                channels = [channels] if channels else []
            if detail.get("id") != key or not isinstance(channels, list) or any(not isinstance(c, str) for c in channels):
                raise JtlFehler("Shop-Aktivierung der Kategorie nicht eindeutig.")
            if SHOP not in channels:
                result = None
            else:
                parent = row.get("parentId")
                prefix = await self.pfad(parent, (*besucht, key)) if parent and parent != "00000000-0000-0000-0000-000000000000" else None
                if parent and parent != "00000000-0000-0000-0000-000000000000" and prefix is None:
                    raise JtlFehler("Übergeordnete Kategorie ist nicht im Shop aktiv.")
                name = row["name"].strip()
                if not name or type(row.get("sortNumber")) is not int:
                    raise JtlFehler("Kategoriename oder Reihenfolge fehlt.")
                result = {"id": key, "name": (prefix["name"] + " / " if prefix else "") + name,
                          "sortierung": (prefix["sortierung"] if prefix else []) + [row["sortNumber"]]}
            self.cache[key] = result
            return result
        except JtlFehler as exc:
            self.cache[key] = exc
            raise

    async def pfad_v1(self, key, besucht=()):
        key = str(key)
        if key in besucht or len(besucht) >= 30:
            raise JtlFehler("Ungültige Kategorie-Hierarchie.")
        cache_key = (key, bool(besucht))
        if cache_key in self.cache:
            return self.cache[cache_key]
        row = await self.client._request("GET", "/v1/categories/" + key)
        ident = row.get("Id")
        channels = row.get("ActiveSalesChannels")
        if type(ident) is not int or ident <= 0 or (key.isdecimal() and int(key) != ident) or not isinstance(channels, list):
            raise JtlFehler("Uneindeutige v1-Kategorie.")
        if not besucht and SHOP not in channels:
            self.cache[cache_key] = None
            return None
        parent = row.get("ParentCategoryId")
        if parent is not None and (type(parent) is not int or parent < 0):
            raise JtlFehler("Ungültige übergeordnete Kategorie.")
        prefix = await self.pfad_v1(parent, (*besucht, key)) if parent else None
        if parent and prefix is None:
            raise JtlFehler("Übergeordnete Kategorie ist nicht im Shop aktiv.")
        name = row.get("Name")
        if not isinstance(name, str) or not name.strip() or type(row.get("SortNumber")) is not int:
            raise JtlFehler("Kategoriename oder Reihenfolge fehlt.")
        value = {"id": "v1-" + str(ident), "name": (prefix["name"] + " / " if prefix else "") + name.strip(),
                 "sortierung": (prefix["sortierung"] if prefix else []) + [row["SortNumber"]]}
        self.cache[cache_key] = value
        return value

    async def artikel(self, detail):
        try:
            block = detail.get("categories")
            rows = block.get("categories") if isinstance(block, dict) else None
            if not isinstance(rows, list):
                raise JtlFehler("Kategoriezuordnung noch nicht verfügbar.")
            if not rows:
                return [], None
            await self.laden()
            result = {}
            for row in rows:
                key = row.get("categoryId") if isinstance(row, dict) else None
                if not isinstance(key, str) or (not self.v1 and key not in self.index):
                    raise JtlFehler("Kategoriezuordnung nicht eindeutig.")
                value = await self.pfad_v1(key) if self.v1 else await self.pfad(key)
                if value:
                    result[key] = value
            return sorted(result.values(), key=lambda c: (c["sortierung"], c["name"], c["id"])), None
        except JtlFehler as exc:
            return [], str(exc)
