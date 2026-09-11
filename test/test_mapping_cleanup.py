import os
import tempfile
import unittest
from unittest.mock import patch

from service import bp_mapping


class MappingCleanupTest(unittest.TestCase):
    def test_cleanup_removes_task_records_and_task_folders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            notes_root = os.path.join(temp_dir, "note")
            mapping_root = os.path.join(temp_dir, "mapping")
            os.makedirs(os.path.join(notes_root, "note123"))
            os.makedirs(os.path.join(mapping_root, "map123"))
            open(os.path.join(notes_root, "note123", "result.pdf"), "wb").close()
            open(os.path.join(mapping_root, "map123", "map123.json"), "wb").close()

            with (
                patch.object(bp_mapping, "Note_Folder", notes_root),
                patch.object(bp_mapping, "Mapping_Folder", mapping_root),
                patch.object(
                    bp_mapping,
                    "execute_query",
                    side_effect=[
                        [{"TransferID": "note123"}],
                        True,
                        True,
                        True,
                    ],
                ) as execute_query,
            ):
                bp_mapping.delete_mapping_artifacts("map123")

            self.assertFalse(os.path.exists(os.path.join(notes_root, "note123")))
            self.assertFalse(os.path.exists(os.path.join(mapping_root, "map123")))
            statements = [call.args[0] for call in execute_query.call_args_list]
            self.assertTrue(any("BackgroundTasks" in statement for statement in statements))
            self.assertTrue(any("NoteTransferHistory" in statement for statement in statements))


if __name__ == "__main__":
    unittest.main()
