"""基础设施：SSRF 闸门、配置白名单、打包、缓存

运行（不需要 pytest）::

    python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from esgtender import (  # noqa: E402
    cli,
    crawl,
    dedup,
    docx_export,
    env,
    extract,
    netguard,
    notify,
    package,
    pipeline,
    presets,
    render,
    search,
    sources,
    store,
    triage,
)


class TestNetGuard(unittest.TestCase):
    """SSRF 闸门：内网、环回、元数据地址、非 http(s) 一律拒绝。"""

    PUBLIC = "93.184.216.34"

    def _resolver(self, ips):
        return mock.patch.object(netguard, "_resolve", return_value=ips)

    def test_public_host_allowed(self):
        with self._resolver([self.PUBLIC]):
            self.assertEqual(
                netguard.assert_public_url("https://example.com/a?b=1"),
                "https://example.com/a?b=1",
            )

    def test_loopback_blocked(self):
        with self._resolver(["127.0.0.1"]):
            with self.assertRaises(netguard.BlockedAddress):
                netguard.assert_public_url("http://localhost:8080/admin/shutdown")

    def test_cloud_metadata_blocked(self):
        with self._resolver(["169.254.169.254"]):
            with self.assertRaises(netguard.BlockedAddress):
                netguard.assert_public_url("http://169.254.169.254/latest/meta-data/")

    def test_one_private_record_is_enough_to_block(self):
        """多 A 记录里只要有一个落内网就拒绝，否则攻击者可以让公网记录「陪跑」。"""
        with self._resolver([self.PUBLIC, "10.0.0.7"]):
            with self.assertRaises(netguard.BlockedAddress):
                netguard.assert_public_url("https://evil.example/x")

    def test_invalid_port_is_blocked_address_not_value_error(self):
        """端口非法时也要抛 BlockedAddress。

        ``urlparse(...).port`` 对 ``:99999`` / ``:abc`` 抛的是裸 ValueError，
        调用方（crawl / notify）只捕 BlockedAddress，漏出去就是未捕获异常。
        """
        for url in ("http://example.com:99999/x", "http://example.com:abc/x"):
            with self.subTest(url=url):
                with self.assertRaises(netguard.BlockedAddress):
                    netguard.assert_public_url(url)

    def test_non_http_scheme_blocked(self):
        for url in ("file:///C:/Windows/win.ini", "javascript:alert(1)", "ftp://example.com/x"):
            with self.assertRaises(netguard.BlockedAddress):
                netguard.assert_public_url(url)

    def test_ipv4_mapped_v6_blocked(self):
        with self._resolver(["::ffff:127.0.0.1"]):
            with self.assertRaises(netguard.BlockedAddress):
                netguard.assert_public_url("http://v6.example/")

    def test_redirect_into_private_is_stopped_before_request(self):
        """公网 URL 302 到 127.0.0.1：第二个请求根本不能发出去。"""
        calls: list[str] = []

        class _Resp:
            def __init__(self, url, location=""):
                self.url = netguard.httpx.URL(url)
                self.headers = {"location": location} if location else {}
                self.is_redirect = bool(location)

            def raise_for_status(self):
                return None

        def fake_get(url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                return _Resp(url, "http://127.0.0.1/secret")
            return _Resp(url)

        def fake_resolve(host, port):
            return ["127.0.0.1"] if host in ("127.0.0.1", "localhost") else [self.PUBLIC]

        with mock.patch.object(netguard.httpx, "get", side_effect=fake_get), mock.patch.object(
            netguard, "_resolve", side_effect=fake_resolve
        ):
            with self.assertRaises(netguard.BlockedAddress):
                netguard.safe_get("https://public.example/list")
        self.assertEqual(len(calls), 1, "第二跳应在发起请求前被拦下")


class TestEnvWhitelist(unittest.TestCase):
    """凭据读取只返回白名单里的键，进程环境里的其它变量一律不外泄。"""

    def test_unknown_keys_are_dropped(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "BOCHA_API_KEY=k1\nSECRET_TOKEN=s3cr3t\nSMTP_HOST=smtp.example.com\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SECRET_TOKEN": "from-env"}, clear=True):
                loaded = env.load_env(path)
        self.assertEqual(loaded["BOCHA_API_KEY"], "k1")
        self.assertEqual(loaded["SMTP_HOST"], "smtp.example.com")
        self.assertNotIn("SECRET_TOKEN", loaded)

    def test_process_env_wins_over_file(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("BOCHA_API_KEY=from-file\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"BOCHA_API_KEY": "from-env"}, clear=True):
                self.assertEqual(env.load_env(path)["BOCHA_API_KEY"], "from-env")

    def test_missing_file_yields_only_env(self):
        import os

        with mock.patch.dict(os.environ, {"SMTP_HOST": "smtp.example.com"}, clear=True):
            loaded = env.load_env(Path("does/not/exist/.env"))
        self.assertEqual(loaded, {"SMTP_HOST": "smtp.example.com"})

    def test_comment_and_quotes_are_stripped(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text('BOCHA_API_KEY="k123"  # 注释\n', encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(env.load_env(path)["BOCHA_API_KEY"], "k123")


class TestPackageAllowlist(unittest.TestCase):
    """打包默认不带任何东西：.env / cache / output / data 都不能进 zip。"""

    def test_zip_excludes_secrets_and_runtime_residue(self):
        import tempfile
        from zipfile import ZipFile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "pkg.zip"
            package.package(target)
            names = ZipFile(target).namelist()

        self.assertTrue(any(name.endswith("/SKILL.md") for name in names))
        self.assertTrue(all(name.startswith("esg-tender-intel/") for name in names))
        self.assertFalse(any(name.endswith("/.env") for name in names))
        for residue in ("/cache/", "/output/", "/data/", "__pycache__", ".pyc"):
            self.assertFalse(any(residue in name for name in names), f"{residue} 不该进包")

    def test_allowlist_has_no_duplicate_entries(self):
        self.assertEqual(len(package.ALLOW), len(set(package.ALLOW)))


class TestCacheHousekeeping(unittest.TestCase):
    def test_expired_cache_files_are_removed(self):
        import os
        import tempfile
        import time

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            old = cache_dir / "old.json"
            fresh = cache_dir / "fresh.json"
            old.write_text("[]", encoding="utf-8")
            fresh.write_text("[]", encoding="utf-8")
            stale = time.time() - 48 * 3600
            os.utime(old, (stale, stale))
            with mock.patch.object(search, "CACHE_DIR", cache_dir):
                removed = search.sweep_cache(24)
            self.assertEqual(removed, 1)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())

    def test_cache_write_is_atomic(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            hit = search.Hit(
                title="t", url="https://e.com/1", snippet="", site="",
                published="", query="q", provider="bocha",
            )
            with mock.patch.object(search, "CACHE_DIR", cache_dir):
                search._write_cache("abc", [hit])
                loaded = search._read_cache("abc", ttl_hours=24)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].url, "https://e.com/1")
            self.assertEqual(list(cache_dir.glob("*.tmp")), [], "临时文件必须被 replace 掉")


if __name__ == "__main__":
    unittest.main(verbosity=2)
