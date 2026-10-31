-- | Shared plumbing for the hs-curry hook ports: JSON on stdin, Python-spelled JSON on stdout, and the
-- few Python truthiness and str() rules the hooks depend on.
module Ade.HsCurry.Hook
  ( J (..)
  , fromValue
  , render
  , emit
  , readHookInput
  , pyTruthy
  , pyStr
  , orDefault
  , objOf
  , strField
  , envSet
  , setKey
  ) where

import Ade.Json (Value (..), parseJson)
import Data.List (intercalate)
import Numeric (showHex)
import System.Environment (lookupEnv)
import System.IO (hSetEncoding, stdin, utf8)

-- | Output JSON. JRaw carries a pre-rendered literal (numbers, true, false, null).
data J = JStr String | JRaw String | JObj [(String, J)] | JArr [J]

fromValue :: Value -> J
fromValue v = case v of
  VObj kvs -> JObj [(k, fromValue x) | (k, x) <- kvs]
  VArr xs -> JArr (map fromValue xs)
  VStr s -> JStr s
  VNum n -> JRaw n
  VBool b -> JRaw (if b then "true" else "false")
  VNull -> JRaw "null"

-- | json.dumps with Python's default separators (", " and ": ") and ensure_ascii on.
render :: J -> String
render (JStr s) = quoteJson s
render (JRaw r) = r
render (JObj kvs) = "{" ++ intercalate ", " [quoteJson k ++ ": " ++ render v | (k, v) <- kvs] ++ "}"
render (JArr xs) = "[" ++ intercalate ", " (map render xs) ++ "]"

quoteJson :: String -> String
quoteJson s = "\"" ++ concatMap esc s ++ "\""
  where
    esc '"' = "\\\""
    esc '\\' = "\\\\"
    esc '\n' = "\\n"
    esc '\r' = "\\r"
    esc '\t' = "\\t"
    esc '\b' = "\\b"
    esc '\f' = "\\f"
    esc c
      | c < ' ' || c > '~' = concatMap unit (units (fromEnum c))
      | otherwise = [c]
    units n
      | n > 0xFFFF = let m = n - 0x10000 in [0xD800 + m `div` 0x400, 0xDC00 + m `mod` 0x400]
      | otherwise = [n]
    unit n = let h = showHex n "" in "\\u" ++ replicate (4 - length h) '0' ++ h

emit :: J -> IO ()
emit = putStrLn . render

-- | The hook's stdin as a JSON value. Nothing when the input is not JSON (json.load raised).
readHookInput :: IO (Maybe Value)
readHookInput = do
  hSetEncoding stdin utf8
  parseJson <$> getContents

-- | Python truthiness of a parsed JSON value.
pyTruthy :: Value -> Bool
pyTruthy v = case v of
  VStr s -> not (null s)
  VNum n -> any (`elem` "123456789") (takeWhile (`notElem` "eE") n)
  VBool b -> b
  VNull -> False
  VArr xs -> not (null xs)
  VObj kvs -> not (null kvs)

-- | str() of a scalar. Containers are rendered as JSON, an approximation of Python's repr.
pyStr :: Value -> String
pyStr v = case v of
  VStr s -> s
  VNum n -> n
  VBool b -> if b then "True" else "False"
  VNull -> "None"
  other -> render (fromValue other)

-- | str(x or default) for an optional field.
orDefault :: String -> Maybe Value -> String
orDefault _ (Just v) | pyTruthy v = pyStr v
orDefault d _ = d

-- | `(x or {})` used as a dict: Nothing when the Python would raise AttributeError on `.get`.
objOf :: Maybe Value -> Maybe [(String, Value)]
objOf Nothing = Just []
objOf (Just v)
  | not (pyTruthy v) = Just []
  | VObj kvs <- v = Just kvs
  | otherwise = Nothing

-- | A string field, or "" when it is missing or not a string.
strField :: String -> [(String, Value)] -> String
strField k kvs = case lookup k kvs of
  Just (VStr s) -> s
  _ -> ""

-- | True when the environment variable is set and non-empty (Python's os.environ.get truthiness).
envSet :: String -> IO Bool
envSet k = maybe False (not . null) <$> lookupEnv k

-- | dict update: replace the key in place, else append, as Python's dict does.
setKey :: String -> J -> [(String, J)] -> [(String, J)]
setKey k v kvs
  | k `elem` map fst kvs = [(k', if k' == k then v else x) | (k', x) <- kvs]
  | otherwise = kvs ++ [(k, v)]
