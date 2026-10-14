import unittest
from backend.service import nickname_matches

class NicknameTests(unittest.TestCase):
    def test_valid_display_names(self):
        for name in ['Игрок @BrainrotFreebie','Игрок@BrainrotFreebie','@brainrotfreebie','@BrainrotFreebie✨','@BrainrotFreebieИгрок','@Brainrot\u200bFreebie','＠ＢｒａｉｎｒｏｔＦｒｅｅｂｉｅ']:
            with self.subTest(name=name):self.assertTrue(nickname_matches(dict(first_name=name)))
        self.assertTrue(nickname_matches(dict(first_name='Игрок',last_name='@BrainrotFreebie')))

    def test_unrelated_handles_and_username_do_not_qualify(self):
        for name in ['', '@BrainrotFreebie_fake','@BrainrotFreebies','BrainrotFreebie','@Another']:
            with self.subTest(name=name):self.assertFalse(nickname_matches(dict(first_name=name)))
        self.assertFalse(nickname_matches(dict(first_name='Игрок',username='BrainrotFreebie')))
        self.assertFalse(nickname_matches(dict(first_name=None,last_name=None)))

if __name__=='__main__':unittest.main()
