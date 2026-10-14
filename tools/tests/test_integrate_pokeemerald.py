import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import integrate_pokeemerald as installer  # noqa: E402


MAIN_SOURCE = """void InitIntrHandlers(void);

void AgbMain(void)
{
    for (;;)
    {
        ReadKeys();
    }
}
"""


class IntegratePokeemeraldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "Makefile").write_text("all:\\n", encoding="utf-8")
        (self.root / "src").mkdir()
        self.main_path = self.root / "src" / "main.c"
        self.main_path.write_text(MAIN_SOURCE, encoding="utf-8")
        self.backup_path = Path(str(self.main_path) + installer.BACKUP_SUFFIX)
        self.loader_path = self.root / "src" / "cubhma_multiplayer_payload.c"

    def tearDown(self):
        self.temp.cleanup()

    def test_installs_and_keeps_backup(self):
        self.assertTrue(installer.integrate(self.root))
        updated = self.main_path.read_text(encoding="utf-8")
        self.assertEqual(1, updated.count(installer.NEW_PROTOTYPE))
        self.assertEqual(1, updated.count(installer.CALL.strip()))
        self.assertTrue(self.backup_path.is_file())
        self.assertEqual(MAIN_SOURCE, self.backup_path.read_text(encoding="utf-8"))
        self.assertEqual(installer.LOADER_TEMPLATE.read_text(encoding="utf-8"), self.loader_path.read_text(encoding="utf-8"))

    def test_integration_is_idempotent(self):
        installer.integrate(self.root)
        first = self.main_path.read_text(encoding="utf-8")
        self.assertFalse(installer.integrate(self.root))
        self.assertEqual(first, self.main_path.read_text(encoding="utf-8"))

    def test_revert_removes_only_added_lines(self):
        installer.integrate(self.root)
        with self.main_path.open("a", encoding="utf-8") as file:
            file.write("\\n/* unrelated local edit */\\n")
        installer.revert(self.root)
        text = self.main_path.read_text(encoding="utf-8")
        self.assertIn("/* unrelated local edit */", text)
        self.assertNotIn(installer.NEW_PROTOTYPE, text)
        self.assertNotIn(installer.CALL.strip(), text)
        self.assertFalse(self.backup_path.exists())
        self.assertFalse(self.loader_path.exists())

    def test_partial_integration_is_refused_without_changes(self):
        self.main_path.write_text(MAIN_SOURCE + installer.NEW_PROTOTYPE + "\\n", encoding="utf-8")
        before = self.main_path.read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Partial/custom"):
            installer.integrate(self.root)
        self.assertEqual(before, self.main_path.read_text(encoding="utf-8"))
        self.assertFalse(self.backup_path.exists())


if __name__ == "__main__":
    unittest.main()
