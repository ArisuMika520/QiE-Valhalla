import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from qq_valhalla.config import Settings, parse_group_ids


class ConfigTests(unittest.TestCase):
    def test_parse_group_ids(self):
        self.assertEqual(parse_group_ids("123, 456;123 789"), ["123", "456", "789"])
        self.assertEqual(parse_group_ids(""), [])

    def test_accept_language_from_env_file(self):
        with TemporaryDirectory() as temp_dir:
            env = Path(temp_dir) / ".env"
            env.write_text(
                'QQ_VALHALLA_COOKIE="skey=abc; p_skey=def; p_uin=o1"\n'
                'QQ_VALHALLA_GROUP_IDS="100"\n'
                'QQ_VALHALLA_ACCEPT_LANGUAGE="zh-CN,zh;q=0.8,en;q=0.4"\n',
                encoding="utf-8",
            )
            settings = Settings.from_env(env)
            self.assertEqual(settings.accept_language, "zh-CN,zh;q=0.8,en;q=0.4")
