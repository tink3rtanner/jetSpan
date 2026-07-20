import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("build-preview-site.py")
SPEC = importlib.util.spec_from_file_location("build_preview_site", SCRIPT)
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class PreviewSlugTests(unittest.TestCase):
    def test_single_branch_keeps_historical_slug(self):
        self.assertEqual(
            BUILD.assign_preview_slugs(["feat/mobile"]),
            {"feat/mobile": "feat-mobile"},
        )

    def test_collisions_are_unique_and_order_independent(self):
        branches = ["feat/a-b", "feat-a/b"]
        forward = BUILD.assign_preview_slugs(branches)
        reverse = BUILD.assign_preview_slugs(list(reversed(branches)))
        self.assertEqual(forward, reverse)
        self.assertEqual(len(set(forward.values())), 2)
        self.assertTrue(all(slug.startswith("feat-a-b-") for slug in forward.values()))


class SafeExtractionTests(unittest.TestCase):
    @staticmethod
    def archive_with(name, payload=b"ok"):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as tf:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))
        stream.seek(0)
        return stream

    def test_regular_file_extracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with tarfile.open(fileobj=self.archive_with("nested/file.txt")) as tf:
                BUILD.safe_extractall(tf, tmp)
            self.assertEqual(Path(tmp, "nested/file.txt").read_bytes(), b"ok")

    def test_parent_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp).parent / "preview-extraction-escape.txt"
            if outside.exists():
                outside.unlink()
            with tarfile.open(fileobj=self.archive_with("../preview-extraction-escape.txt")) as tf:
                with self.assertRaises(Exception):
                    BUILD.safe_extractall(tf, tmp)
            self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
