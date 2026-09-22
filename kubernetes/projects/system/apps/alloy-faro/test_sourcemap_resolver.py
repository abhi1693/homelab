import importlib.util
import pathlib
import unittest
import urllib.error

spec = importlib.util.spec_from_file_location("resolver", pathlib.Path(__file__).with_name("sourcemap-resolver.py"))
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)
MAP = b'{"version":3,"sources":["original.ts"],"mappings":"AAAA"}'
PATH = "/shipyardhq/_next/static/chunks/bundle.js.map"


class ResolverTest(unittest.TestCase):
    def test_existing_alias(self):
        self.assertEqual(resolver.resolve(PATH, lambda url: MAP), MAP)

    def test_turbopack_distinct_hash(self):
        urls = []

        def fetch(url):
            urls.append(url)
            if url.endswith("bundle.js.map"):
                raise urllib.error.HTTPError(url, 404, "missing", {}, None)
            if url.endswith("bundle.js"):
                return b"const a=1;\n//# sourceMappingURL=another-hash.js.map\n"
            self.assertTrue(url.endswith("/faro-sourcemaps/_next/static/chunks/another-hash.js.map"))
            return MAP

        self.assertEqual(resolver.resolve(PATH, fetch), MAP)
        self.assertEqual(len(urls), 3)

    def test_path_restrictions(self):
        for path in ("/evil/_next/static/chunks/a.js.map", PATH + "?url=http://evil", PATH.replace("chunks", "%2e%2e"), PATH.replace("bundle", "a%2Fb%3Ac")):
            with self.subTest(path=path), self.assertRaises(ValueError):
                resolver.asset_path(path)

    def test_no_remote_or_traversing_map_reference(self):
        for ref in ("http://evil/a.js.map", "//evil/a.js.map", "../a.js.map", "data:abc"):
            def fetch(url):
                if url.endswith(".map"):
                    raise urllib.error.HTTPError(url, 404, "missing", {}, None)
                return ("//# sourceMappingURL=" + ref).encode()
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                resolver.resolve(PATH, fetch)

    def test_rejects_html_and_non_map_json(self):
        for body in (b"<html>login</html>", b"{}", b"[]"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                resolver.resolve(PATH, lambda url: body)


if __name__ == "__main__":
    unittest.main()
