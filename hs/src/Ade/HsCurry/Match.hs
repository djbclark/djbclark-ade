-- | Regex-shaped matchers for the hs-curry hook ports (hs/app/hooks). The boot packages have no
-- regex library, so these combinators stand in for the few `re` patterns the Python hooks use.
-- A matcher returns every remainder it can leave, so backtracking works as it does in Python's
-- `re` for these shapes: an optional or a star tries the longer match first and falls back.
module Ade.HsCurry.Match
  ( RM
  , lit
  , oneOfC
  , runs
  , optM
  , starM
  , seqM
  , altM
  , pureM
  , guardM
  , isWordChar
  , pyStrip
  , stripLiterals
  ) where

import Data.Char (isAlphaNum, isSpace)
import Data.List (dropWhileEnd, intercalate, isPrefixOf)

-- | Every remainder left after a match at the front of the text.
type RM = String -> [String]

pureM :: RM
pureM s = [s]

-- | Consumes nothing; succeeds only when the predicate holds for the text that follows.
guardM :: (String -> Bool) -> RM
guardM p s = [s | p s]

lit :: String -> RM
lit l s = [drop (length l) s | l `isPrefixOf` s]

oneOfC :: String -> RM
oneOfC cs (c : r) | c `elem` cs = [r]
oneOfC _ _ = []

-- | A run of characters satisfying p, at least lo long, longest first (greedy).
runs :: (Char -> Bool) -> Int -> RM
runs p lo s = [drop k s | k <- [n, n - 1 .. lo]]
  where
    n = length (takeWhile p s)

optM :: RM -> RM
optM m s = m s ++ [s]

starM :: RM -> RM
starM m s = s : [r | s1 <- m s, s1 /= s, r <- starM m s1]

seqM :: [RM] -> RM
seqM ms s = foldl (\acc m -> concatMap m acc) [s] ms

altM :: [RM] -> RM
altM ms s = concatMap ($ s) ms

isWordChar :: Char -> Bool
isWordChar c = isAlphaNum c || c == '_'

-- | Python's str.strip() for the whitespace these hooks see.
pyStrip :: String -> String
pyStrip = dropWhileEnd isSpace . dropWhile isSpace

-- | bg-gate's strip_literals: drop heredoc bodies, then quoted strings, so words inside text do not count.
stripLiterals :: String -> String
stripLiterals cmd =
  subQuoted '"' "\"\"" (subQuoted '\'' "''" (intercalate "\n" (stripHeredocs (splitNL cmd))))

splitNL :: String -> [String]
splitNL s = case break (== '\n') s of
  (a, _ : rest) -> a : splitNL rest
  (a, []) -> [a]

-- | `<<-?\s*['"]?(\w+)['"]?` searched in one line: the captured word, if any.
heredocDelim :: String -> Maybe String
heredocDelim line =
  case [w | i <- [0 .. length line - 1], "<<" `isPrefixOf` drop i line, Just w <- [delim (drop (i + 2) line)]] of
    (w : _) -> Just w
    [] -> Nothing
  where
    delim r =
      let r1 = case r of
            ('-' : t) -> t
            _ -> r
          r2 = dropWhile isSpace r1
          r3 = case r2 of
            (q : t) | q `elem` "'\"" -> t
            _ -> r2
          w = takeWhile isWordChar r3
       in if null w then Nothing else Just w

-- | Drop each heredoc body and its terminator line; the opening line stays.
stripHeredocs :: [String] -> [String]
stripHeredocs [] = []
stripHeredocs (l : ls) = case heredocDelim l of
  Nothing -> l : stripHeredocs ls
  Just d -> l : stripHeredocs (drop 1 (dropWhile ((/= d) . pyStrip) ls))

-- | re.sub(q ... q, repl) for one quote character: a complete pair is replaced, an unclosed quote is kept.
subQuoted :: Char -> String -> String -> String
subQuoted q repl = go
  where
    go [] = []
    go (c : cs)
      | c == q = case break (== q) cs of
          (_, _ : after) -> repl ++ go after
          _ -> c : go cs
      | otherwise = c : go cs
