import base64
import unittest

from meshdebug.pki_crypto import generate_keypair, public_key_from_private


class PkiCryptoTests(unittest.TestCase):
    def test_public_key_from_private_matches_firmware_curve25519_eval(self):
        private_key = base64.b64decode("MRhF97IwardKLzu2QjnjWrsx1cSeSQuH7nmvPU8tHsw=")
        expected_public_key = base64.b64decode("L99OPVltadQQe+Vzw6ZbZQIvZdrmaguj0AwZzNfwZkE=")

        self.assertEqual(public_key_from_private(private_key), expected_public_key)

    def test_generate_keypair_returns_a_firmware_consistent_pair(self):
        private_key, public_key = generate_keypair()

        self.assertEqual(len(private_key), 32)
        self.assertEqual(len(public_key), 32)
        self.assertEqual(private_key[0] & 0x07, 0)
        self.assertEqual(private_key[31] & 0x80, 0)
        self.assertNotEqual(private_key[31] & 0x40, 0)
        self.assertEqual(public_key_from_private(private_key), public_key)


if __name__ == "__main__":
    unittest.main()
