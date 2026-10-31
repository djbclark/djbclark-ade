-- | A small JSON reader and a Python-compatible `json.dumps(indent=1)` writer for ade-hs entry
-- points. Only the boot packages are available, so there is no aeson; the reader is strict about
-- syntax and returns Nothing on any error.
module Ade.Json
  ( Value (..)
  , parseJson
  , field
  , asStr
  , asInteger
  , Out (..)
  , encodeIndent1
  ) where

import Data.Char (chr, isDigit, isSpace)
import Numeric (readHex)

data Value
  = VObj [(String, Value)]
  | VArr [Value]
  | VStr String
  | VNum String
  | VBool Bool
  | VNull
  deriving (Eq, Show)

-- | Parse one complete JSON document (surrounding whitespace allowed).
parseJson :: String -> Maybe Value
parseJson s = case value (ws s) of
  Just (v, r) | all isSpace r -> Just v
  _ -> Nothing

ws :: String -> String
ws = dropWhile isSpace

value :: String -> Maybe (Value, String)
value s = case s of
  '{' : r -> object (ws r)
  '[' : r -> array (ws r)
  '"' : r -> (\(t, r') -> (VStr t, r')) <$> stringBody r
  't' : 'r' : 'u' : 'e' : r -> Just (VBool True, r)
  'f' : 'a' : 'l' : 's' : 'e' : r -> Just (VBool False, r)
  'n' : 'u' : 'l' : 'l' : r -> Just (VNull, r)
  c : _ | c == '-' || isDigit c ->
    let (n, r) = span (\x -> isDigit x || x `elem` "+-.eE") s
     in Just (VNum n, r)
  _ -> Nothing

object :: String -> Maybe (Value, String)
object ('}' : r) = Just (VObj [], r)
object s0 = go s0 []
  where
    go s acc = do
      (k, r1) <- case s of
        '"' : r -> stringBody r
        _ -> Nothing
      r2 <- case ws r1 of
        ':' : r -> Just (ws r)
        _ -> Nothing
      (v, r3) <- value r2
      case ws r3 of
        ',' : r4 -> go (ws r4) ((k, v) : acc)
        '}' : r4 -> Just (VObj (reverse ((k, v) : acc)), r4)
        _ -> Nothing

array :: String -> Maybe (Value, String)
array (']' : r) = Just (VArr [], r)
array s0 = go s0 []
  where
    go s acc = do
      (v, r1) <- value s
      case ws r1 of
        ',' : r2 -> go (ws r2) (v : acc)
        ']' : r2 -> Just (VArr (reverse (v : acc)), r2)
        _ -> Nothing

-- | The body of a string after its opening quote.
stringBody :: String -> Maybe (String, String)
stringBody = go ""
  where
    go acc ('"' : r) = Just (reverse acc, r)
    go acc ('\\' : c : r) = case c of
      'n' -> go ('\n' : acc) r
      't' -> go ('\t' : acc) r
      'r' -> go ('\r' : acc) r
      'b' -> go ('\b' : acc) r
      'f' -> go ('\f' : acc) r
      'u' | (h, r') <- splitAt 4 r, length h == 4, [(n, "")] <- readHex h -> go (chr n : acc) r'
      _ -> go (c : acc) r
    go acc (c : r) = go (c : acc) r
    go _ [] = Nothing

-- | Member lookup on an object.
field :: String -> Value -> Maybe Value
field k (VObj kvs) = lookup k kvs
field _ _ = Nothing

asStr :: Maybe Value -> Maybe String
asStr (Just (VStr t)) = Just t
asStr _ = Nothing

-- | A whole number from a JSON number literal ("3", "300000.0" both count).
asInteger :: Maybe Value -> Maybe Integer
asInteger (Just (VNum t))
  | not (null digits) && all isDigit digits = Just (sign (read digits))
  | [(d, "")] <- reads (fixup t) :: [(Double, String)]
  , d == fromIntegral (round d :: Integer) = Just (round d)
  | otherwise = Nothing
  where
    (sign, digits) = case t of
      '-' : r -> (negate, r)
      _ -> (id, t)
    fixup x = if take 1 x == "-" then '-' : fixLead (drop 1 x) else fixLead x
    fixLead x = if take 1 x == "." then '0' : x else x
asInteger _ = Nothing

-- | Output values for the writer, keeping Python's json.dumps spelling.
data Out
  = OStr String
  | OInt Integer
  | OFloat Double
  | ONull
  | OBool Bool
  | OList [Out]
  | OObj [(String, Out)]

-- | `json.dumps(x, indent=1)` with ensure_ascii on.
encodeIndent1 :: Out -> String
encodeIndent1 = render 0
  where
    render _ (OStr t) = quote t
    render _ (OInt n) = show n
    render _ (OFloat d) = show d
    render _ ONull = "null"
    render _ (OBool b) = if b then "true" else "false"
    render _ (OList []) = "[]"
    render d (OList xs) =
      "[\n" ++ commaSep [pad (d + 1) ++ render (d + 1) x | x <- xs] ++ "\n" ++ pad d ++ "]"
    render _ (OObj []) = "{}"
    render d (OObj kvs) =
      "{\n" ++ commaSep [pad (d + 1) ++ quote k ++ ": " ++ render (d + 1) v | (k, v) <- kvs] ++ "\n" ++ pad d ++ "}"
    pad n = replicate n ' '
    commaSep = foldr1' (\a b -> a ++ ",\n" ++ b)
    foldr1' _ [] = ""
    foldr1' f xs = foldr1 f xs
    quote t = "\"" ++ concatMap esc t ++ "\""
    esc c
      | c == '"' = "\\\""
      | c == '\\' = "\\\\"
      | c == '\n' = "\\n"
      | c == '\r' = "\\r"
      | c == '\t' = "\\t"
      | c == '\b' = "\\b"
      | c == '\f' = "\\f"
      | c < ' ' || c > '~' = if c > '\xffff'
          then let v = fromEnum c - 0x10000 in hex4 (0xd800 + v `div` 0x400) ++ hex4 (0xdc00 + v `mod` 0x400)
          else hex4 (fromEnum c)
      | otherwise = [c]
    hex4 n = "\\u" ++ let h = showHex4 n in replicate (4 - length h) '0' ++ h
    showHex4 n = let go 0 acc = if null acc then "0" else acc
                     go m acc = go (m `div` 16) ("0123456789abcdef" !! (m `mod` 16) : acc)
                  in go n ""
