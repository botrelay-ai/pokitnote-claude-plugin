import importlib.util
import json
import re
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("skills/pokit-note/SKILL.md", "skills/pokit-note-connected-assistant/SKILL.md")
USER_FACING = (*SKILLS, "commands/sign-in.md", "README.md", "routine-prompt.md")


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


class PluginConfigTest(unittest.TestCase):
    def test_mcp_points_at_the_remote_server(self):
        raw = json.loads(read(".mcp.json"))
        self.assertEqual(list(raw), ["pokitnote"])
        server = raw["pokitnote"]
        self.assertEqual(server["type"], "http")
        self.assertNotIn("command", server)
        self.assertNotIn("args", server)
        self.assertNotIn("headers", server)
        self.assertEqual(server["url"], "${POKITNOTE_API_BASE:-https://pokitnote.com/mcp}")
        self.assertEqual(server["oauth"], {"scopes": "notes"})
        text = json.dumps(raw)
        self.assertNotIn("grok-bot", text)
        self.assertNotIn("python", text.lower())
        for prefix in ("pnt_", "pnoa_", "pnor_"):
            self.assertNotIn(prefix, text)

    def test_cursor_files_are_gone(self):
        self.assertFalse((ROOT / ".cursor-plugin").exists())
        self.assertFalse((ROOT / "mcp.json").exists())
        self.assertFalse((ROOT / "server").exists())

    def test_marketplace_and_manifest(self):
        market = json.loads(read(".claude-plugin/marketplace.json"))
        self.assertEqual(market["name"], "pokit-note")
        self.assertEqual(market["plugins"][0]["name"], "pokit-note")
        self.assertEqual(market["plugins"][0]["source"], "./")
        plugin = json.loads(read(".claude-plugin/plugin.json"))
        self.assertEqual(plugin["name"], "pokit-note")
        self.assertEqual(plugin["license"], "MIT")
        self.assertEqual(plugin["repository"], "https://github.com/botrelay-ai/pokitnote-claude-plugin")
        for cursor_field in ("logo", "variables"):
            self.assertNotIn(cursor_field, plugin)
        self.assertNotIn("pnt_", json.dumps(plugin))
        logo = (ROOT / "assets" / "logo.png").read_bytes()
        self.assertTrue(logo.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(struct.unpack(">II", logo[16:24]), (256, 256))

    def test_no_grok_bot_or_cursor_left(self):
        pattern = re.compile(r"grok|cursor", re.IGNORECASE)
        for relative in USER_FACING:
            for number, line in enumerate(read(relative).splitlines(), start=1):
                self.assertIsNone(pattern.search(line), f"{relative}:{number}: {line}")

    def test_coffee_and_tea_follows_beverages(self):
        for relative in ("skills/pokit-note/SKILL.md", "README.md", "routine-prompt.md"):
            text = read(relative)
            self.assertIn("Beverages, Coffee & Tea, Dairy & Eggs", text)
            self.assertIn(
                "Coffee beans, ground coffee, K-cups, and tea go in Coffee & Tea, not Beverages.",
                text,
            )

    def test_pet_food_follows_frozen_foods(self):
        for relative in ("skills/pokit-note/SKILL.md", "README.md", "routine-prompt.md"):
            text = read(relative)
            self.assertIn("Frozen Foods, Pet Food, and Other", text)
            self.assertIn("Dog and cat food, treats, and litter go in Pet Food.", text)

    def test_address_override_cannot_ship_a_non_production_default(self):
        validate = load_script("validate_plugin")
        check = validate.resolved_mcp_url_problem
        self.assertIsNone(check("${POKITNOTE_API_BASE:-https://pokitnote.com/mcp}"))
        self.assertIsNone(check("https://pokitnote.com/mcp"))
        self.assertIsNotNone(check("https://pokitnote.com/mcp/"))
        self.assertIsNotNone(check("${POKITNOTE_API_BASE:-https://pokitnote.com/mcp/}"))
        self.assertIsNotNone(check("${POKITNOTE_API_BASE}"), "a bare variable fails when unset")
        for url in ("https://stage.pokitnote.com/mcp", "https://api.pokitnote.com/mcp"):
            self.assertIsNotNone(check(url), url)
            self.assertIsNotNone(check("${POKITNOTE_API_BASE:-" + url + "}"), url)
        for relative in ("skills/pokit-note/SKILL.md", "README.md"):
            text = read(relative)
            self.assertIn("https://pokitnote.com/mcp", text)
            self.assertNotIn("https://pokitnote.com/mcp/", text)
            self.assertIn("no trailing slash", text)
            self.assertIn("Leave Pokit Note address unset", text)
            self.assertIn("POKITNOTE_API_BASE", text)

    def test_shared_link_goes_in_item_note(self):
        for relative in ("skills/pokit-note-connected-assistant/SKILL.md", "routine-prompt.md"):
            self.assertIn("always put the page link in that item's note", read(relative))

    def test_routine_never_deletes_without_a_person(self):
        for relative in ("skills/pokit-note-connected-assistant/SKILL.md", "routine-prompt.md"):
            text = read(relative)
            self.assertIn("Never clear completed items, remove a recently bought item, or delete", text)
            self.assertIn("Each run starts fresh and cannot see earlier runs.", text)
            self.assertNotIn("Authorization header", text)

    def test_routine_prompt_is_up_to_date(self):
        build = load_script("build_routine_prompt")
        self.assertEqual(read("routine-prompt.md"), build.build())

    def test_routine_prompt_stands_alone(self):
        text = read("routine-prompt.md")
        self.assertNotIn("Pokit Note skill", text)
        self.assertNotIn("## Setup", text)
        self.assertIn("font-size: 17px", text)


if __name__ == "__main__":
    unittest.main()
