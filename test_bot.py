import unittest

import bot


class BotUtilityTests(unittest.TestCase):
    def test_overs_to_balls(self):
        self.assertEqual(bot.overs_to_balls("10"), 60)
        self.assertEqual(bot.overs_to_balls("10.3"), 63)
        self.assertEqual(bot.overs_to_balls("0.5"), 5)
        self.assertEqual(bot.overs_to_balls("bad"), 0)

    def test_stable_event_suffix_is_deterministic(self):
        text = "Player reaches fifty in 24 balls"
        self.assertEqual(bot.stable_event_suffix(text), bot.stable_event_suffix(text))
        self.assertNotEqual(bot.stable_event_suffix(text), bot.stable_event_suffix("other"))

    def test_international_text_filter(self):
        self.assertTrue(bot.is_international_text_check("India vs Australia, 2nd ODI"))
        self.assertFalse(bot.is_international_text_check("India A vs Pakistan A"))
        self.assertFalse(bot.is_international_text_check("Some League Final"))

    def test_command_matches(self):
        self.assertTrue(bot._command_matches("/track 1", "/track"))
        self.assertFalse(bot._command_matches("hello /track 1", "/track"))


if __name__ == "__main__":
    unittest.main()
