-- | Minimal test harness for hs/test (boot packages only; no hspec or tasty on this machine).
module Harness (Test, roundTrip, rejects, runTests) where

import Control.Monad (forM)
import System.Exit (exitFailure)

data Test = Test String Bool

roundTrip :: Eq a => String -> (a -> [(String, String)]) -> ([(String, String)] -> Either String a) -> a -> Test
roundTrip name enc dec x = Test name (dec (enc x) == Right x)

rejects :: String -> Either String a -> Test
rejects name r = Test name (either (const True) (const False) r)

runTests :: [Test] -> IO ()
runTests ts = do
  bad <- forM ts $ \(Test n ok) -> if ok then pure 0 else putStrLn ("FAIL " ++ n) >> pure (1 :: Int)
  let failures = sum bad
  putStrLn (show (length ts - failures) ++ "/" ++ show (length ts) ++ " passed")
  if failures > 0 then exitFailure else pure ()
