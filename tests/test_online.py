import threading
import unittest
from backend.service import Service

class OnlineCountTests(unittest.TestCase):
    def setUp(self):
        self.now=1000
        self.service=Service.__new__(Service)
        self.service.clock=lambda:self.now
        self.service.presence={}
        self.service.presence_lock=threading.Lock()

    def test_unique_users_not_sessions(self):
        self.assertEqual(self.service.online_count(1),1)
        self.assertEqual(self.service.online_count(1),1)
        self.assertEqual(self.service.online_count(2),2)

    def test_sixty_second_expiration(self):
        self.service.online_count(1)
        self.now+=59
        self.assertEqual(self.service.online_count(2),2)
        self.now+=1
        self.assertEqual(self.service.online_count(2),1)
        self.now+=60
        self.assertEqual(self.service.online_count(3),1)

    def test_heartbeat_keeps_user_present(self):
        self.service.online_count(1)
        self.now+=50
        self.service.online_count(1)
        self.now+=20
        self.assertEqual(self.service.online_count(2),2)

if __name__=='__main__':unittest.main()
