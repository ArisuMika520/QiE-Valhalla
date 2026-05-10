import unittest

from qq_valhalla.cookie import missing_required_cookies, parse_cookie_header, qq_gtk


class CookieAndHashTests(unittest.TestCase):
    def test_parse_cookie_header(self):
        parsed = parse_cookie_header("skey=abc; p_skey=def; p_uin=o123")
        self.assertEqual(parsed["skey"], "abc")
        self.assertEqual(parsed["p_skey"], "def")
        self.assertEqual(parsed["p_uin"], "o123")
        self.assertEqual(missing_required_cookies(parsed), [])

    def test_qq_gtk_known_values(self):
        self.assertEqual(qq_gtk("abc"), "193485963")
        self.assertEqual(qq_gtk(""), "5381")
        self.assertEqual(qq_gtk("@abcdef1234567890"), "1727043975")
