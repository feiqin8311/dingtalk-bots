import unittest

from usage_state import InMemoryRuntimeState, normalize_shipment_sns


class UsageStateTests(unittest.TestCase):
    def test_normalize_shipment_sns_deduplicates_and_sorts(self):
        self.assertEqual(normalize_shipment_sns([" sp2 ", "SP1", "sp2", ""]), ["SP1", "SP2"])

    def test_register_message_rejects_duplicate_until_ttl_expires(self):
        state = InMemoryRuntimeState()

        self.assertTrue(state.register_message("msg-1", ttl_sec=60))
        self.assertFalse(state.register_message("msg-1", ttl_sec=60))

    def test_shipment_lock_blocks_other_holder_and_releases(self):
        state = InMemoryRuntimeState()

        self.assertEqual(state.acquire_shipment_locks(["SP1"], "req-a", ttl_sec=60), (True, None))
        self.assertEqual(state.acquire_shipment_locks(["SP1"], "req-b", ttl_sec=60), (False, "SP1"))

        state.release_shipment_locks(["SP1"], "req-a")

        self.assertEqual(state.acquire_shipment_locks(["SP1"], "req-b", ttl_sec=60), (True, None))


if __name__ == "__main__":
    unittest.main()
