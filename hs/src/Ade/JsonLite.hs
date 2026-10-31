-- | A small JSON value type with a parser and a renderer that matches Python's
-- @json.dumps(value, indent=2, ensure_ascii=False)@ layout. Only GHC boot packages are used,
-- so there is no aeson. Numbers are kept as their source text so that a round trip does not
-- reformat them. Object keys keep their file order.
module Ade.JsonLite
  ( Json (..)
  , parseJson
  , renderJson
  , renderWith
  , objLookup
  , objSet
  ) where

import Data.Char (chr, digitToInt, isDigit, isHexDigit)
import Data.List (intercalate)
import Numeric (showHex)

data Json
  = JNull
  | JBool Bool
  | JNum String
  | JStr String
  | JArr [Json]
  | JObj [(String, Json)]
  deriving (Eq, Show)

-- | Parse one JSON document (surrounding whitespace allowed).
parseJson :: String -> Either String Json
parseJson s = case value (skipWs s) of
  Left e -> Left e
  Right (v, rest)
    | all (`elem` " \t\r\n") rest -> Right v
    | otherwise -> Left "trailing data after JSON value"

skipWs :: String -> String
skipWs = dropWhile (`elem` " \t\r\n")

value :: String -> Either String (Json, String)
value ('n' : 'u' : 'l' : 'l' : r) = Right (JNull, skipWs r)
value ('t' : 'r' : 'u' : 'e' : r) = Right (JBool True, skipWs r)
value ('f' : 'a' : 'l' : 's' : 'e' : r) = Right (JBool False, skipWs r)
value ('"' : r) = do
  (str, r') <- stringBody r
  pure (JStr str, skipWs r')
value ('[' : r) = array (skipWs r) []
value ('{' : r) = object (skipWs r) []
value s@(c : _)
  | c == '-' || isDigit c = do
      let (num, r) = span (\x -> isDigit x || x `elem` "-+.eE") s
      pure (JNum num, skipWs r)
value _ = Left "unexpected token in JSON"

array :: String -> [Json] -> Either String (Json, String)
array (']' : r) [] = Right (JArr [], skipWs r)
array s acc = do
  (v, r) <- value s
  case r of
    (',' : r') -> array (skipWs r') (v : acc)
    (']' : r') -> Right (JArr (reverse (v : acc)), skipWs r')
    _ -> Left "expected , or ] in array"

object :: String -> [(String, Json)] -> Either String (Json, String)
object ('}' : r) [] = Right (JObj [], skipWs r)
object ('"' : s) acc = do
  (k, r) <- stringBody s
  case skipWs r of
    (':' : r1) -> do
      (v, r2) <- value (skipWs r1)
      case r2 of
        (',' : r3) -> object (skipWs r3) ((k, v) : acc)
        ('}' : r3) -> Right (JObj (reverse ((k, v) : acc)), skipWs r3)
        _ -> Left "expected , or } in object"
    _ -> Left "expected : after object key"
object _ _ = Left "expected object key"

-- | The body of a string after its opening quote; returns the decoded text and the rest.
stringBody :: String -> Either String (String, String)
stringBody = go []
  where
    go acc ('"' : r) = Right (reverse acc, r)
    go acc ('\\' : c : r) = case c of
      '"' -> go ('"' : acc) r
      '\\' -> go ('\\' : acc) r
      '/' -> go ('/' : acc) r
      'b' -> go ('\b' : acc) r
      'f' -> go ('\f' : acc) r
      'n' -> go ('\n' : acc) r
      'r' -> go ('\r' : acc) r
      't' -> go ('\t' : acc) r
      'u' | (h, r') <- splitAt 4 r, length h == 4, all isHexDigit h ->
              go (chr (foldl (\a d -> a * 16 + digitToInt d) 0 h) : acc) r'
      _ -> Left "bad escape in JSON string"
    go acc (c : r) = go (c : acc) r
    go _ [] = Left "unterminated JSON string"

-- | Render with two-space indentation, as json.dumps(indent=2, ensure_ascii=False) does.
renderJson :: Json -> String
renderJson = renderWith 2

-- | Render with the given indent width (json.dumps(indent=n, ensure_ascii=False)).
renderWith :: Int -> Json -> String
renderWith w = render w 0

render :: Int -> Int -> Json -> String
render _ _ JNull = "null"
render _ _ (JBool b) = if b then "true" else "false"
render _ _ (JNum n) = n
render _ _ (JStr s) = quote s
render _ _ (JArr []) = "[]"
render w i (JArr xs) = wrap w "[" "]" i [render w (i + 1) x | x <- xs]
render _ _ (JObj []) = "{}"
render w i (JObj kvs) = wrap w "{" "}" i [quote k ++ ": " ++ render w (i + 1) v | (k, v) <- kvs]

wrap :: Int -> String -> String -> Int -> [String] -> String
wrap w open close i items =
  open ++ "\n" ++ intercalate ",\n" [pad (i + 1) ++ it | it <- items] ++ "\n" ++ pad i ++ close
  where pad n = replicate (w * n) ' '

quote :: String -> String
quote s = '"' : concatMap esc s ++ "\""
  where
    esc '"' = "\\\""
    esc '\\' = "\\\\"
    esc '\n' = "\\n"
    esc '\r' = "\\r"
    esc '\t' = "\\t"
    esc '\b' = "\\b"
    esc '\f' = "\\f"
    esc c
      | c < ' ' = "\\u" ++ replicate (4 - length h) '0' ++ h
      | otherwise = [c]
      where h = showHex (fromEnum c) ""

objLookup :: String -> Json -> Maybe Json
objLookup k (JObj kvs) = lookup k kvs
objLookup _ _ = Nothing

-- | Set a key in an object, keeping its position when it exists and appending it otherwise.
objSet :: String -> Json -> Json -> Json
objSet k v (JObj kvs)
  | any ((== k) . fst) kvs = JObj [(k', if k' == k then v else x) | (k', x) <- kvs]
  | otherwise = JObj (kvs ++ [(k, v)])
objSet _ _ other = other
