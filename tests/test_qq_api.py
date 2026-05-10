import unittest

from qq_valhalla.qq_api import QQClient


class QQClientTests(unittest.TestCase):
    def test_headers_include_configured_language(self):
        client = QQClient(
            "skey=abc; p_skey=def; p_uin=o1",
            user_agent="TestAgent/1.0",
            accept_language="zh-CN,zh;q=0.8",
        )
        headers = client._headers("application/json")
        self.assertEqual(headers["User-Agent"], "TestAgent/1.0")
        self.assertEqual(headers["Accept-Language"], "zh-CN,zh;q=0.8")
        self.assertEqual(headers["Origin"], "https://qun.qq.com")

    def test_headers_emulate_browser_fingerprint(self):
        client = QQClient("skey=abc; p_skey=def; p_uin=o1")
        headers = client._headers("application/json")
        self.assertEqual(headers["X-Requested-With"], "XMLHttpRequest")
        self.assertEqual(headers["Sec-Fetch-Site"], "same-origin")
        self.assertEqual(headers["Sec-Fetch-Mode"], "cors")
        self.assertEqual(headers["Sec-Fetch-Dest"], "empty")
        self.assertEqual(headers["sec-ch-ua-mobile"], "?0")
        self.assertIn("Chromium", headers["sec-ch-ua"])
        self.assertEqual(headers["sec-ch-ua-platform"], '"Windows"')
        self.assertEqual(headers["Connection"], "keep-alive")
        self.assertEqual(headers["Accept-Encoding"], "gzip, deflate, br")
        self.assertEqual(headers["Referer"], "https://qun.qq.com/member.html")
        self.assertNotIn("python", headers["User-Agent"].lower())
