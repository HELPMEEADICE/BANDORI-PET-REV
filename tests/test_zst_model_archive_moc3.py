import unittest

import zst_model_archive


class ZstModelArchiveMoc3Test(unittest.TestCase):
    def test_model_resource_members_include_model3_file_references(self):
        model_json = {
            "FileReferences": {
                "Moc": "model.moc3",
                "Textures": ["textures/texture_00.png"],
                "Physics": "model.physics3.json",
                "Pose": "model.pose3.json",
                "DisplayInfo": "model.cdi3.json",
                "Expressions": [{"Name": "exp_smile01", "File": "expressions/exp_smile01.exp3.json"}],
            }
        }

        self.assertEqual(
            {
                "live_01/model.moc3",
                "live_01/textures/texture_00.png",
                "live_01/model.physics3.json",
                "live_01/model.pose3.json",
                "live_01/model.cdi3.json",
                "live_01/expressions/exp_smile01.exp3.json",
            },
            zst_model_archive._model_resource_members(
                "live_01/test.model3.json",
                model_json,
                include_expressions=True,
            ),
        )

    def test_action_resource_members_include_model3_motion_and_expression_files(self):
        model_json = {
            "FileReferences": {
                "Motions": {"mtn_smile01_C": [{"File": "motions/mtn_smile01_C.motion3.json"}]},
                "Expressions": [{"Name": "exp_smile01", "File": "expressions/exp_smile01.exp3.json"}],
            }
        }

        self.assertEqual(
            {
                "live_01/motions/mtn_smile01_C.motion3.json",
                "live_01/expressions/exp_smile01.exp3.json",
            },
            zst_model_archive._action_resource_members(
                "live_01/test.model3.json",
                model_json,
                ["mtn_smile01_C"],
                ["exp_smile01"],
            ),
        )


if __name__ == "__main__":
    unittest.main()
