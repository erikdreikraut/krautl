import copy
import json
import unittest
import httpx

from app.jtl_onprem import OnPremClient
from scripts.pruefe_bilder_schreibformat import pruefen, pruefziel, faelle

SOURCE = "770f139d-18dd-405c-9f84-3221e3000000"
BLOB = "43a705d0-621f-4955-b02f-d6d2887c89d5"
URL = "https://wawi.test/api/eazybusiness"


class SchreibformatTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        image = {"blobIdentifier": BLOB, "sortNumber": 1, "isMainImage": True}
        self.block = {"defaultImages": [image], "platformImages": [], "ebayImages": [],
                      "saleschannelImages": [{"saleschannelId": "2-2-1", "images": [image]},
                                             {"saleschannelId": "1-1-0", "images": [image]}]}
        self.job = {"artikel": SOURCE, "sku": "30501-002", "api_ziel": URL, "ziel": self.block}
        self.calls = []
        self.target_get = 404
        self.target_body = {}
        self.baseline = 404
        self.probe_status = 400
        self.target_reads = 0
        self.appear_after = None

    def transport(self, req):
        self.calls.append((req.method, req.url.path))
        if req.url.path.endswith(SOURCE):
            self.assertEqual(req.method, "GET", "Live source must never be written")
            return httpx.Response(200, json={"id": SOURCE, "identifiers": {"sku": self.job["sku"]}})
        self.assertTrue(req.url.path.endswith(pruefziel(SOURCE)))
        if req.method == "GET":
            self.target_reads += 1
            status = 200 if self.appear_after and self.target_reads >= self.appear_after else self.target_get
            return httpx.Response(status, text="null") if self.target_body is None else httpx.Response(status, json=self.target_body)
        self.assertEqual(req.method, "PATCH")
        self.assertEqual(self.calls[-2], ("GET", req.url.path))
        body = json.loads(req.content)
        status = self.baseline if not body else self.probe_status
        return httpx.Response(status, json={"Title": "Unknown", "Status": 500, "Detail": "Unknown Internal Error"}
                              if status == 500 else {"Title": "validation details"})

    async def run_probe(self):
        async with OnPremClient(URL, "secret", transport=httpx.MockTransport(self.transport)) as c:
            return await pruefen(c, self.job, lambda *a: None)

    async def test_isolates_blocks_and_channels_without_touching_source_or_snapshot(self):
        original = copy.deepcopy(self.job)
        results = await self.run_probe()
        self.assertEqual(len(results), 7)
        self.assertTrue(all(status == 400 for label, status in results))
        self.assertEqual(self.job, original)
        self.assertEqual(sum(method == "PATCH" for method, path in self.calls), 8)

    async def test_abort_on_any_non_404_target_before_patch(self):
        for status in (200, 400, 401, 403, 500):
            self.calls = []
            self.target_get = status
            with self.assertRaisesRegex(ValueError, "Abbruch vor PATCH"):
                await self.run_probe()
            self.assertFalse(any(m == "PATCH" for m, p in self.calls))

    async def test_abort_when_target_appears_between_probes(self):
        self.appear_after = 2
        with self.assertRaisesRegex(ValueError, "Abbruch vor PATCH"):
            await self.run_probe()
        self.assertEqual(sum(m == "PATCH" for m, p in self.calls), 1)

    async def test_baseline_must_reach_not_found(self):
        self.baseline = 400
        with self.assertRaisesRegex(ValueError, "Kontrollrequest"):
            await self.run_probe()
        self.assertEqual(sum(m == "PATCH" for m, p in self.calls), 1)

    async def test_stop_on_unexpected_success_or_server_error(self):
        for status in (200, 201, 401, 403, 500):
            self.calls = []
            self.probe_status = status
            with self.assertRaisesRegex(ValueError, "Unerwartete Antwort"):
                await self.run_probe()
            self.assertEqual(sum(m == "PATCH" for m, p in self.calls), 2)

    async def test_wrong_api_target_stops_without_network(self):
        self.job["api_ziel"] = "https://other.test/api/eazybusiness"
        with self.assertRaisesRegex(ValueError, "Wawi-Ziel"):
            await self.run_probe()
        self.assertEqual(self.calls, [])

    def test_no_probe_can_use_source_as_target(self):
        with self.assertRaises(ValueError):
            pruefziel(pruefziel(SOURCE))

    def test_individual_case_copies_do_not_modify_snapshot(self):
        original = copy.deepcopy(self.block)
        cases = list(faelle(self.block))
        cases[0][1]["images"]["defaultImages"][0]["sortNumber"] = 99
        self.assertEqual(self.block, original)
        self.assertEqual(cases[1][1]["images"]["defaultImages"][0]["sortNumber"], 1)


    async def test_identity_diagnosis_only_gets_even_when_every_target_exists(self):
        from scripts.pruefe_bilder_schreibformat import identitaeten_lesen
        requests, output = [], []
        def transport(req):
            requests.append(req)
            return httpx.Response(200, json={"id": SOURCE, "identifiers": {"sku": "30501"},
                                             "images": {"url": "do-not-print"}})
        async with OnPremClient(URL, "secret", transport=httpx.MockTransport(transport)) as c:
            await identitaeten_lesen(c, self.job, output.append)
        self.assertEqual(len(requests), 4)
        self.assertTrue(all(r.method == "GET" for r in requests))
        self.assertTrue(any('"sku": "30501"' in s for s in output))
        self.assertFalse(any("do-not-print" in s for s in output))

    async def test_identity_diagnosis_handles_null_and_non_json_without_mutation(self):
        from scripts.pruefe_bilder_schreibformat import identitaeten_lesen
        requests = []
        def transport(req):
            requests.append(req)
            return httpx.Response(200, text="null" if len(requests) % 2 else "<html>private</html>")
        async with OnPremClient(URL, "secret", transport=httpx.MockTransport(transport)) as c:
            await identitaeten_lesen(c, self.job, lambda *a: None)
        self.assertTrue(all(r.method == "GET" for r in requests))


    async def test_installed_wawi_200_null_allows_guarded_probes(self):
        self.target_get = 200
        self.target_body = None
        results = await self.run_probe()
        self.assertEqual(len(results), 7)
        self.assertEqual(sum(m == "PATCH" for m, p in self.calls), 8)

    def test_absence_detection_is_strict(self):
        from scripts.pruefe_bilder_schreibformat import artikel_fehlt
        for body in ('{}', '[]', '"null"', 'false', '0', '', '<html>error</html>',
                     '{"id": null}', '{"id": "existing"}'):
            self.assertFalse(artikel_fehlt(httpx.Response(200, text=body)), body)
        self.assertTrue(artikel_fehlt(httpx.Response(200, text='null')))
        self.assertTrue(artikel_fehlt(httpx.Response(404)))
        self.assertFalse(artikel_fehlt(httpx.Response(500, text='null')))

    async def test_200_null_still_requires_missing_patch_control(self):
        self.target_get = 200
        self.target_body = None
        self.baseline = 400
        with self.assertRaisesRegex(ValueError, "Kontrollrequest"):
            await self.run_probe()
        self.assertEqual(sum(m == "PATCH" for m, p in self.calls), 1)


    async def test_observed_missing_item_internal_error_can_be_compared_without_retries(self):
        self.target_get = 200
        self.target_body = None
        self.baseline = 500
        self.probe_status = 500
        results = await self.run_probe()
        self.assertEqual(len(results), 7)
        self.assertTrue(all(status == 500 for label, status in results))
        self.assertEqual(sum(m == "PATCH" for m, p in self.calls), 8)
        self.assertEqual(self.target_reads, 8)

    async def test_500_control_does_not_relax_existing_item_guard(self):
        self.baseline = 500
        self.appear_after = 2
        with self.assertRaisesRegex(ValueError, "Abbruch vor PATCH"):
            await self.run_probe()
        self.assertEqual(sum(m == "PATCH" for m, p in self.calls), 1)
