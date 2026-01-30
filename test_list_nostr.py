import unittest
import importlib.util
import sys
import os

# Import list-nostr.py dynamically
file_path = os.path.join(os.path.dirname(__file__), 'list-nostr.py')
spec = importlib.util.spec_from_file_location("list_nostr", file_path)
list_nostr = importlib.util.module_from_spec(spec)
sys.modules["list_nostr"] = list_nostr
spec.loader.exec_module(list_nostr)

chunk_list = list_nostr.chunk_list

class TestListNostr(unittest.TestCase):
    def test_chunk_list(self):
        # Test basic chunking
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        chunks = list(chunk_list(data, 3))
        self.assertEqual(len(chunks), 4)
        self.assertEqual(chunks[0], [1, 2, 3])
        self.assertEqual(chunks[3], [10])

        # Test empty list
        data = []
        chunks = list(chunk_list(data, 3))
        self.assertEqual(len(chunks), 0)

        # Test chunk size larger than list
        data = [1, 2]
        chunks = list(chunk_list(data, 5))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], [1, 2])

if __name__ == '__main__':
    unittest.main()
