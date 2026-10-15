import unittest
import tempfile
import os
import sys

# Add the project root to the path so we can import greeting
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from greeting import greet

class TestGreeting(unittest.TestCase):
    def test_regular_name(self):
        self.assertEqual(greet("Ada"), "Hello, Ada!")
    
    def test_uppercase(self):
        self.assertEqual(greet("Ada", uppercase=True), "HELLO, ADA!")
    
    def test_unicode(self):
        self.assertEqual(greet("Zoë"), "Hello, Zoë!")
    
    def test_unicode_uppercase(self):
        self.assertEqual(greet("Zoë", uppercase=True), "HELLO, ZOË!")