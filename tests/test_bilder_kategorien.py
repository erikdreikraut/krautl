import unittest
from unittest.mock import AsyncMock
from app.bilder_kategorien import ShopKategorien
from app.jtl_client import JtlFehler


class KategorienTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_shop_categories_with_ordered_paths_and_cached_reads(self):
        rows = [{"id":"root", "name":"Kräuter", "sortNumber":2},
                {"id":"leaf", "parentId":"root", "name":"Tee", "sortNumber":1},
                {"id":"other", "name":"Intern", "sortNumber":0}]
        async def request(method, path, **kwargs):
            self.assertEqual(method, "GET")
            if path == "/v2/categories":
                return {"items":rows,"pageNumber":1,"totalItems":3,"hasNextPage":False}
            key = path.rsplit("/",1)[1]
            return {"id":key,"activeSalesChannelIds":["2-2-1"] if key != "other" else ["9-7-8-0"]}
        client = AsyncMock()
        client._request.side_effect = request
        resolver = ShopKategorien(client)
        detail = {"categories":{"categories":[{"categoryId":"leaf"},{"categoryId":"other"}]}}
        result, error = await resolver.artikel(detail)
        self.assertIsNone(error)
        self.assertEqual(result, [{"id":"leaf","name":"Kräuter / Tee","sortierung":[2,1]}])
        await resolver.artikel(detail)
        self.assertEqual(client._request.await_count,4)

    async def test_access_failure_is_explicit_and_not_repeated_per_article(self):
        client = AsyncMock()
        client._request.side_effect = JtlFehler("Direkte JTL-API: HTTP 403.")
        resolver = ShopKategorien(client)
        detail = {"categories":{"categories":[{"categoryId":"x"}]}}
        for _ in range(2):
            result, error = await resolver.artikel(detail)
            self.assertEqual(result, [])
            self.assertIn("403", error)
        self.assertEqual(client._request.await_count,1)

    async def test_missing_mapping_is_not_claimed_empty(self):
        result, error = await ShopKategorien(AsyncMock()).artikel({})
        self.assertEqual(result, [])
        self.assertIsNotNone(error)


    async def test_v1_fallback_uses_uuid_lookup_and_parent_order(self):
        async def request(method,path,**kwargs):
            self.assertEqual(method,"GET")
            if path=="/v2/categories": raise JtlFehler("Direkte JTL-API: HTTP 400.")
            if path=="/v1/categories/uuid-leaf":return {"Id":14,"Name":"Naturpflege","ParentCategoryId":4,"SortNumber":70,"ActiveSalesChannels":["2-2-1"]}
            if path=="/v1/categories/4":return {"Id":4,"Name":"dreikraut","SortNumber":0,"ActiveSalesChannels":["8-140-9"]}
            raise AssertionError(path)
        client=AsyncMock();client._request.side_effect=request
        resolver=ShopKategorien(client)
        detail={"categories":{"categories":[{"categoryId":"uuid-leaf"}]}}
        value,error=await resolver.artikel(detail)
        self.assertIsNone(error)
        self.assertEqual(value,[{"id":"v1-14","name":"dreikraut / Naturpflege","sortierung":[0,70]}])
        await resolver.artikel(detail)
        self.assertEqual(client._request.await_count,3)

    async def test_v1_cycle_remains_visible_error(self):
        client=AsyncMock()
        client._request.side_effect=[JtlFehler("HTTP 400"),{"Id":1,"Name":"X","ParentCategoryId":1,"SortNumber":0,"ActiveSalesChannels":["2-2-1"]},{"Id":1,"Name":"X","ParentCategoryId":1,"SortNumber":0,"ActiveSalesChannels":["2-2-1"]}]
        value,error=await ShopKategorien(client).artikel({"categories":{"categories":[{"categoryId":"uuid"}]}})
        self.assertEqual(value,[])
        self.assertIn("Hierarchie",error)
