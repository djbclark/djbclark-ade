-- | PreToolUse (Grep|Glob|Bash): once per session, in a graft-indexed repo, remind the model to try
-- graft first. Port of claude/hooks/graft_grep_nudge.py (hs-curry). Non-blocking: additionalContext only.
--
-- Port notes: the Bash search test (`(?:^|[|;&(]\s*|\s)(?:grep|...|fd)\s`) is a direct scan in
-- searchesForCode, and the literal stripping is shared with the bg gate. The once-per-session marker
-- lives in getTemporaryDirectory, as tempfile.gettempdir() does. A non-object input exits 1, as the
-- Python AttributeError does (that code sits outside the try in the original).
module Main (main) where

import Ade.HsCurry.Hook
import Ade.HsCurry.Match (stripLiterals)
import Ade.Json (Value (..))
import Control.Exception (IOException, try)
import Control.Monad (unless, when)
import Data.Char (isSpace)
import Data.List (isPrefixOf)
import Data.Maybe (catMaybes, fromMaybe, listToMaybe)
import System.Directory (doesFileExist, doesPathExist, getCurrentDirectory, getTemporaryDirectory)
import System.Environment (lookupEnv)
import System.Exit (ExitCode (..), exitSuccess, exitWith)
import System.FilePath ((</>))
import System.IO (hPutStrLn, stderr)

hint :: String
hint =
  "This repo is indexed by graft. Before grepping/globbing for code, try "
    ++ "`graft ask` (how/where), `graft grep` (every occurrence), "
    ++ "`graft callers` (callers/blast radius) or `graft skeleton` (a file's API). "
    ++ "Fall back to Grep/Glob for non-code text or when graft misses."

-- | `(?:^|[|;&(]\s*|\s)(?:grep|egrep|rg|ag|ack|find|fd)\s` searched anywhere in the command.
searchesForCode :: String -> Bool
searchesForCode s = any wordAt (filter startOk [0 .. length s - 1])
  where
    startOk w =
      w == 0
        || isSpace (s !! (w - 1))
        || (let j = backOverSpaces w in j > 0 && s !! (j - 1) `elem` "|;&(")
    backOverSpaces w = if w > 0 && isSpace (s !! (w - 1)) then backOverSpaces (w - 1) else w
    wordAt w = any (matchesWord w) words'
    matchesWord w wd = wd `isPrefixOf` drop w s && afterOk (drop (w + length wd) s)
    afterOk r = case r of
      (c : _) -> isSpace c
      [] -> False
    words' = ["grep", "egrep", "rg", "ag", "ack", "find", "fd"]

nudge :: [(String, Value)] -> IO ()
nudge kvs = do
  tmp <- getTemporaryDirectory
  let sid = orDefault "default" (lookup "session_id" kvs)
      marker = tmp </> ("graft-nudge-" ++ sid)
  already <- doesPathExist marker
  when already exitSuccess
  _ <- try (writeFile marker "") :: IO (Either IOException ())
  emit
    ( JObj
        [
          ( "hookSpecificOutput"
          , JObj [("hookEventName", JStr "PreToolUse"), ("additionalContext", JStr hint)]
          )
        ]
    )

body :: [(String, Value)] -> IO ()
body kvs = do
  cwdNow <- getCurrentDirectory
  envProj <- lookupEnv "CLAUDE_PROJECT_DIR"
  let fromCwd = case lookup "cwd" kvs of
        Just v | pyTruthy v -> Just (pyStr v)
        _ -> Nothing
      fromEnv = case envProj of
        Just p | not (null p) -> Just p
        _ -> Nothing
      root = fromMaybe cwdNow (listToMaybe (catMaybes [fromCwd, fromEnv]))
  indexed <- doesFileExist (root </> "graft" </> "INDEX.md")
  unless indexed exitSuccess
  if strField "tool_name" kvs == "Bash"
    then case objOf (lookup "tool_input" kvs) of
      Nothing -> do
        hPutStrLn stderr "AttributeError: 'tool_input' has no attribute 'get'"
        exitWith (ExitFailure 1)
      Just tin -> do
        let cmd = stripLiterals (orDefault "" (lookup "command" tin))
        unless (searchesForCode cmd) exitSuccess
        nudge kvs
    else nudge kvs

main :: IO ()
main = do
  mv <- readHookInput
  case mv of
    Nothing -> exitSuccess
    Just (VObj kvs) -> body kvs
    Just _ -> do
      hPutStrLn stderr "AttributeError: hook input is not a JSON object (no attribute 'get')"
      exitWith (ExitFailure 1)
