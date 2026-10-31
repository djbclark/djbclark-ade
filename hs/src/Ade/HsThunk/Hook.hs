-- | Shared helpers for the hs-thunk hook ports (see docs/adr/0042-bin-port-target.md).
-- Boot packages only. Every hook reads Claude Code hook JSON from stdin and writes its decision to
-- stdout; these helpers keep the Python originals' edge behaviour (missing fields, falsy values,
-- compact json.dumps output) in one place.
module Ade.HsThunk.Hook
  ( setUtf8
  , readStdin
  , tryAny
  , field
  , strField
  , jTruthy
  , renderCompact
  , homeDir
  , safeSlug
  , gitRoot
  , runGit
  , strip
  , writeAtomic
  , relParts
  ) where

import Ade.HsThunk.Sha1 (sha1Hex)
import Ade.JsonLite (Json (..), objLookup)
import Control.Exception (SomeException, onException, try)
import Data.Char (isSpace)
import Data.List (dropWhileEnd, intercalate, isPrefixOf)
import Data.Maybe (fromMaybe)
import Numeric (showHex)
import System.Directory
  ( createDirectoryIfMissing, doesDirectoryExist, doesFileExist, getHomeDirectory, removeFile
  , renameFile )
import System.Exit (ExitCode (..))
import System.FilePath
  ( dropTrailingPathSeparator, splitDirectories, takeDirectory, takeFileName, (</>) )
import System.IO
  ( hClose, hPutStr, hSetEncoding, openTempFile, stderr, stdin, stdout, utf8, getContents' )
import System.Process (CreateProcess (..), proc, readCreateProcessWithExitCode)
import System.Timeout (timeout)

-- | UTF-8 on all three standard streams, as the Python hooks run under a UTF-8 locale.
setUtf8 :: IO ()
setUtf8 = mapM_ (`hSetEncoding` utf8) [stdin, stdout, stderr]

-- | All of stdin as text; "" when it cannot be read (the hooks treat that as no input).
readStdin :: IO String
readStdin = do
  hSetEncoding stdin utf8
  r <- tryAny getContents'
  pure (either (const "") id r)

tryAny :: IO a -> IO (Either SomeException a)
tryAny = try

-- | dict.get(key): the value, or JNull when the key is missing or the object is not one.
field :: String -> Json -> Json
field k j = fromMaybe JNull (objLookup k j)

-- | A string field; any non-string value (including a missing one) reads as "".
strField :: String -> Json -> String
strField k j = case field k j of
  JStr s -> s
  _ -> ""

-- | Python truthiness of a parsed JSON value.
jTruthy :: Json -> Bool
jTruthy JNull = False
jTruthy (JBool b) = b
jTruthy (JNum n) = not (all (`elem` "0.-+eE") n)
jTruthy (JStr s) = not (null s)
jTruthy (JArr xs) = not (null xs)
jTruthy (JObj kvs) = not (null kvs)

-- | json.dumps(value) with Python's default separators (", " and ": "), ensure_ascii off.
renderCompact :: Json -> String
renderCompact JNull = "null"
renderCompact (JBool b) = if b then "true" else "false"
renderCompact (JNum n) = n
renderCompact (JStr s) = quoteJson s
renderCompact (JArr xs) = "[" ++ intercalate ", " (map renderCompact xs) ++ "]"
renderCompact (JObj kvs) =
  "{" ++ intercalate ", " [quoteJson k ++ ": " ++ renderCompact v | (k, v) <- kvs] ++ "}"

quoteJson :: String -> String
quoteJson s = '"' : concatMap esc s ++ "\""
  where
    esc '"' = "\\\""
    esc '\\' = "\\\\"
    esc '\n' = "\\n"
    esc '\r' = "\\r"
    esc '\t' = "\\t"
    esc '\b' = "\\b"
    esc '\f' = "\\f"
    esc c
      | c < ' ' = "\\u" ++ pad4 (showHex (fromEnum c) "")
      | otherwise = [c]
    pad4 h = replicate (4 - length h) '0' ++ h

homeDir :: IO FilePath
homeDir = getHomeDirectory

-- | _safe_slug: runs outside [A-Za-z0-9._-] become "-", dashes collapse and trim, "root" when
-- nothing is left, and anything over 120 characters is cut to 80 plus "-" and an 8-hex SHA-1.
safeSlug :: String -> String
safeSlug value
  | length slug > 120 = take 80 slug ++ "-" ++ take 8 (sha1Hex slug)
  | otherwise = slug
  where
    trimmed = dropWhileEnd (== '-') (dropWhile (== '-') (dedupDash (subRuns value)))
    slug = if null trimmed then "root" else trimmed

subRuns :: String -> String
subRuns [] = []
subRuns (c : cs)
  | keep c = c : subRuns cs
  | otherwise = '-' : subRuns (dropWhile (not . keep) cs)
  where
    keep x = isAsciiAlnum x || x `elem` "._-"

isAsciiAlnum :: Char -> Bool
isAsciiAlnum x = (x >= 'a' && x <= 'z') || (x >= 'A' && x <= 'Z') || (x >= '0' && x <= '9')

dedupDash :: String -> String
dedupDash ('-' : '-' : r) = dedupDash ('-' : r)
dedupDash (c : r) = c : dedupDash r
dedupDash [] = []

-- | Upward search for a normal, worktree (.git file) or bare (HEAD + objects/) root, 64 levels max.
gitRoot :: FilePath -> IO (Maybe FilePath)
gitRoot = go (64 :: Int)
  where
    go 0 _ = pure Nothing
    go n cur = do
      dotGit <- (||) <$> doesDirectoryExist (cur </> ".git") <*> doesFileExist (cur </> ".git")
      bare <- (&&) <$> doesFileExist (cur </> "HEAD") <*> doesDirectoryExist (cur </> "objects")
      if dotGit || bare
        then pure (Just cur)
        else do
          let parent = takeDirectory (dropTrailingPathSeparator cur)
          if parent == cur then pure Nothing else go (n - 1) parent

-- | git <args> in dir, stripped stdout; "" on any failure, non-zero exit or a 10 s timeout.
runGit :: FilePath -> [String] -> IO String
runGit dir args = do
  r <- tryAny (timeout 10000000 (readCreateProcessWithExitCode ((proc "git" args) { cwd = Just dir }) ""))
  pure $ case r of
    Right (Just (ExitSuccess, out, _)) -> strip out
    _ -> ""

-- | Python str.strip() for the whitespace that matters here.
strip :: String -> String
strip = dropWhileEnd isSpace . dropWhile isSpace

-- | Write the file through a temp file beside it and rename it into place (temp + os.replace).
writeAtomic :: FilePath -> String -> IO ()
writeAtomic dest body = do
  let dir = takeDirectory dest
  createDirectoryIfMissing True dir
  (tmp, h) <- openTempFile dir ("." ++ takeFileName dest ++ ".tmp")
  (do hSetEncoding h utf8
      hPutStr h body
      hClose h
      renameFile tmp dest) `onException` (hClose h >> tryAny (removeFile tmp) >> pure ())

-- | Path components of p under base, or Nothing when p is not under base (Path.relative_to).
relParts :: FilePath -> FilePath -> Maybe [String]
relParts base p =
  let bs = splitDirectories (dropTrailingPathSeparator base)
      ps = splitDirectories (dropTrailingPathSeparator p)
  in if bs `isPrefixOf` ps then Just (drop (length bs) ps) else Nothing
