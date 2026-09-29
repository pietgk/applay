import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from tools import validate_skills  # noqa: E402


class SkillValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.source_root = self.root / ".claude" / "skills"
        self.codex_root = self.root / ".agents" / "skills"
        self.source_root.mkdir(parents=True)
        self.codex_root.mkdir(parents=True)

    def _skill(self, name: str, description: str = "Use when testing a skill.") -> pathlib.Path:
        skill = self.source_root / name
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n\n# Test\n",
            encoding="utf-8",
        )
        return skill

    def test_valid_skill_and_codex_symlink_pass(self):
        skill = self._skill("apply-example")
        (self.codex_root / skill.name).symlink_to(skill, target_is_directory=True)

        self.assertEqual(
            validate_skills.validate_apply_skills(self.source_root, self.codex_root), []
        )

    def test_missing_codex_symlink_fails(self):
        self._skill("apply-example")

        self.assertEqual(
            validate_skills.validate_apply_skills(self.source_root, self.codex_root),
            [f"apply-example: missing Codex symlink {self.codex_root / 'apply-example'}"],
        )

    def test_invalid_description_fails_before_discovery_check(self):
        self._skill("apply-example", "Use for <example> applications.")

        self.assertEqual(
            validate_skills.validate_apply_skills(self.source_root, self.codex_root),
            ["apply-example: description cannot contain angle brackets"],
        )

    def test_wrong_symlink_target_fails(self):
        self._skill("apply-example")
        other = self.root / "other"
        other.mkdir()
        (self.codex_root / "apply-example").symlink_to(other, target_is_directory=True)

        errors = validate_skills.validate_apply_skills(self.source_root, self.codex_root)

        self.assertEqual(len(errors), 1)
        self.assertIn("Codex symlink points to", errors[0])


if __name__ == "__main__":
    unittest.main()
