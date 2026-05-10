import unittest

from qq_valhalla.archiver import (
    filter_group_list_response,
    normalize_member_page_size,
    validate_group_list_response,
    validate_member_response,
    validate_target_groups_found,
)
from qq_valhalla.storage import extract_groups, normalize_group


class ArchiverFilterTests(unittest.TestCase):
    def test_filter_group_list_response_keeps_only_targets(self):
        response = {
            "ec": 0,
            "create": [{"gc": 100, "gn": "A"}, {"gc": 200, "gn": "B"}],
            "manage": [{"groupId": "300", "groupName": "C"}],
        }
        filtered = filter_group_list_response(response, {"200", "300"})
        groups = [normalize_group(group) for group in extract_groups(filtered)]

        self.assertEqual([group["group_id"] for group in groups], ["200", "300"])
        self.assertEqual(filtered["ec"], 0)

    def test_normalize_member_page_size(self):
        self.assertEqual(normalize_member_page_size(100), 40)
        self.assertEqual(normalize_member_page_size(0), 1)
        self.assertEqual(normalize_member_page_size(20), 20)

    def test_validate_member_response_rejects_empty_shell(self):
        with self.assertRaises(ValueError):
            validate_member_response({"ec": 0, "errcode": 0, "em": ""}, group_id="100", start=0, end=99)

        validate_member_response({"ec": 0, "errcode": 0, "mems": []}, group_id="100", start=0, end=39)

    def test_validate_group_list_and_target_group(self):
        with self.assertRaises(ValueError):
            validate_group_list_response({"ec": 0, "errcode": 0, "em": ""})

        validate_group_list_response({"ec": 0, "errcode": 0, "create": []})

        with self.assertRaises(ValueError):
            validate_target_groups_found(["100"], [])
