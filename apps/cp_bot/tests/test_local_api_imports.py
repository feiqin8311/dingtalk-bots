import unittest


class LocalApiImportTests(unittest.TestCase):
    def test_required_common_api_classes_are_available_locally(self):
        from api import DingTalkNotifier
        from api.aliyun_client import AliyunOCRClient
        from api.lingxing_client import LingXingClient

        self.assertEqual(DingTalkNotifier.__name__, "DingTalkNotifier")
        self.assertEqual(AliyunOCRClient.__name__, "AliyunOCRClient")
        self.assertEqual(LingXingClient.__name__, "LingXingClient")


if __name__ == "__main__":
    unittest.main()
