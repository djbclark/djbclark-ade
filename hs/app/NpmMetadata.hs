-- | npm-metadata: parse npm's scalar and workspace-array version metadata without guessing.
--
-- Reads the JSON text of `npm view ... version` (a string, or an array of strings for workspace
-- packages) on stdin and prints the one exact version. Exit 0 with the version on stdout; exit 1
-- with a message on stderr when the input is malformed, empty, not a version string, or carries
-- more than one distinct version.
module Main (main) where

import Ade.Json (Value (..), parseJson)
import Ade.Prelude (warn)
import Data.List (nub)
import System.Exit (ExitCode (..), exitWith)
import System.IO (hGetContents, stdin)

-- | Semantic-version shape: MAJOR.MINOR.PATCH, optional -PRERELEASE and +BUILD, each identifier
-- made of ASCII letters, digits, '.' and '-'.
isExactVersion :: String -> Bool
isExactVersion s =
  case break (`elem` "-+") s of
    (core, rest) -> isCore core && isTail rest
  where
    isCore core = case splitDots core of
      [a, b, c] -> all (\p -> not (null p) && all isDigitAscii p) [a, b, c]
      _ -> False
    splitDots str = case break (== '.') str of
      (x, []) -> [x]
      (x, _ : more) -> x : splitDots more
    isDigitAscii c = c >= '0' && c <= '9'
    ident c = isDigitAscii c || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '.' || c == '-'
    isTail [] = True
    isTail ('-' : t) = case span ident t of
      (pre, r) -> not (null pre) && plusPart r
    isTail r = plusPart r
    plusPart [] = True
    plusPart ('+' : b) = not (null b) && all ident b
    plusPart _ = False

-- | Return exactly one version, rejecting ambiguous or malformed npm output.
parseVersionMetadata :: String -> Either String String
parseVersionMetadata raw = do
  value <- maybe (Left "npm metadata is not valid JSON") Right (parseJson raw)
  let versions = case value of
        VArr xs -> xs
        v -> [v]
      strings = [s | VStr s <- versions]
  if null versions || length strings /= length versions
    then Left "npm metadata must contain exact version strings"
    else Right ()
  if not (all isExactVersion strings)
    then Left "npm metadata must contain exact version strings"
    else Right ()
  case nub strings of
    [only] -> Right only
    _ -> Left "npm metadata contains multiple distinct versions"

main :: IO ()
main = do
  raw <- hGetContents stdin
  case parseVersionMetadata raw of
    Right v -> putStrLn v
    Left msg -> warn ("npm-metadata: " ++ msg) >> exitWith (ExitFailure 1)
