import unittest
from fizz import fizzbuzz
class T(unittest.TestCase):
    def test_len(self): self.assertEqual(len(fizzbuzz(15)), 15)
    def test_fb(self): self.assertEqual(fizzbuzz(15)[-1], "FizzBuzz")
    def test_start(self): self.assertEqual(fizzbuzz(5), ["1","2","Fizz","4","Buzz"])
if __name__ == "__main__": unittest.main()
