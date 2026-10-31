-- | orca-reorg-watch: watch upstream Orca for movement on the structural-reorg gaps.
--
-- Tracks the issues and PRs behind stablyai/orca#23272 and probes the installed `orca` CLI for the
-- verbs those issues ask for. Exit codes follow the orca_upstream_watch.py convention: 0 = no change,
-- 10 = something moved, 2 = could not probe. State lives in ~/.local/state/orca-reorg-watch.json.
--
--   orca-reorg-watch          compare against last snapshot, print changes
--   orca-reorg-watch --show   print current state without comparing or saving
--   orca-reorg-watch --reset  overwrite the snapshot with current state
module Main (main) where

import Ade.Json (Out (..), Value (..), asInteger, asStr, encodeIndent1, field, parseJson)
import Control.Monad (forM, when)
import Control.Monad.IO.Class (liftIO)
import Control.Monad.Trans.Except (ExceptT (..), runExceptT, throwE)
import Data.List (intercalate, isInfixOf)
import System.Directory (createDirectoryIfMissing, doesFileExist, getHomeDirectory)
import System.Environment (getArgs)
import Control.Exception (IOException, try)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (takeDirectory)
import System.IO (hPutStrLn, stderr)
import System.Process (readProcessWithExitCode)

repo :: String
repo = "stablyai/orca"

-- | Issue number and why it matters (herdr analog in parentheses).
tracked :: [(Int, String)]
tracked =
  [ (23272, "umbrella: structural reorg parity (filed by us)")
  , (9632, "terminal move across worktrees (herdr pane move --tab)")
  , (15108, "PR: orca terminal move")
  , (12083, "Move Tab to Split as a command (herdr pane move --split)")
  , (15771, "terminal split --ratio (herdr pane resize)")
  , (12306, "worktree ordering / --place (sidebar order)")
  , (8766, "project-group CLI")
  , (22433, "orca repo rm")
  , (20515, "tab reorder shortcut")
  , (10055, "Move Tab to Split shortcut")
  , (1548, "PR: declarative layout rules in orca.yaml")
  , (22759, "open tab in chosen editor group from CLI")
  ]

-- | (label, argv, substring that means the verb now exists).
cliProbes :: [(String, [String], String)]
cliProbes =
  [ ("terminal move", ["terminal", "--help"], "move ")
  , ("terminal swap", ["terminal", "--help"], "swap ")
  , ("terminal resize", ["terminal", "--help"], "resize ")
  , ("terminal layout", ["terminal", "--help"], "layout ")
  , ("repo rm", ["repo", "--help"], "  rm ")
  , ("worktree set --sort-order", ["worktree", "set", "--help"], "--sort-order")
  , ("worktree set --before", ["worktree", "set", "--help"], "--before")
  ]

type Probe = ExceptT String IO

-- | Run argv (never a shell). A missing binary is an error, as Python's FileNotFoundError is.
runProc :: String -> [String] -> Probe (ExitCode, String, String)
runProc cmd args = ExceptT $ do
  r <- try (readProcessWithExitCode cmd args "") :: IO (Either IOException (ExitCode, String, String))
  pure $ either (Left . show) Right r

-- | `subprocess.run(..., check=True)`: a nonzero exit is an error.
runChecked :: String -> [String] -> Probe String
runChecked cmd args = do
  (rc, out, _) <- runProc cmd args
  case rc of
    ExitSuccess -> pure out
    ExitFailure n -> throwE ("Command '" ++ show (cmd : args) ++ "' returned non-zero exit status " ++ show n ++ ".")

-- | The fields the watch compares for one issue, from `gh api repos/.../issues/N`.
fetchIssue :: Int -> Probe Value
fetchIssue n = do
  out <- runChecked "gh" ["api", "repos/" ++ repo ++ "/issues/" ++ show n]
  d <- maybe (liftIO (failParse "not a JSON object")) pure (parseJson out)
  let str k = maybe (error ("orca-reorg-watch: issue field " ++ k ++ " is not a string")) id (asStr (field k d))
      num k = maybe (error ("orca-reorg-watch: issue field " ++ k ++ " is not a number")) id (asInteger (field k d))
      mergedAt = case field "pull_request" d >>= field "merged_at" of
        Just (VStr t) -> not (null t)
        _ -> False
  pure $ VObj
    [ ("state", VStr (str "state"))
    , ("merged", VBool mergedAt)
    , ("comments", VNum (show (num "comments")))
    , ("updated", VStr (str "updated_at"))
    , ("title", VStr (str "title"))
    ]

-- | Unreadable gh output: the Python tool lets the JSON error escape, so it exits 1 with a message.
failParse :: String -> IO a
failParse e = do
  hPutStrLn stderr ("orca-reorg-watch: unreadable gh output: " ++ e)
  exitWith (ExitFailure 1)

probe :: [String] -> String -> Probe Bool
probe argv needle = do
  (_, out, err) <- runProc "orca" argv
  pure (needle `isInfixOf` (out ++ err))

snapshot :: Probe Value
snapshot = do
  issues <- forM tracked $ \(n, _) -> do
    j <- fetchIssue n
    pure (show n, j)
  cli <- forM cliProbes $ \(label, argv, needle) -> do
    has <- probe argv needle
    pure (label, VBool has)
  v <- runChecked "orca" ["--version"]
  pure $ VObj
    [ ("issues", VObj issues)
    , ("cli", VObj cli)
    , ("orca_version", VStr (trimEnd v))
    ]
  where
    trimEnd = reverse . dropWhile (`elem` " \t\r\n") . reverse

-- | Python's str() of a JSON scalar, as an f-string shows it.
showScalar :: Maybe Value -> String
showScalar m = case m of
  Just (VStr s) -> s
  Just (VNum n) -> n
  Just (VBool True) -> "True"
  Just (VBool False) -> "False"
  Just VNull -> "None"
  Nothing -> "None"
  Just _ -> "<object>"

members :: String -> Value -> [(String, Value)]
members k v = case field k v of
  Just (VObj kvs) -> kvs
  _ -> []

-- | The snapshot as an output tree for the writer.
toOut :: Value -> Out
toOut v = case v of
  VObj kvs -> OObj [(k, toOut x) | (k, x) <- kvs]
  VArr xs -> OList (map toOut xs)
  VStr t -> OStr t
  VNum t -> maybe (OStr t) OInt (asInteger (Just v))
  VBool b -> OBool b
  VNull -> ONull

-- | Human-readable changes between two snapshots.
diffSnapshots :: Value -> Value -> [String]
diffSnapshots old new = issueMsgs ++ cliMsgs ++ versionMsgs
  where
    newIssues = members "issues" new
    oldIssues = members "issues" old
    issueMsgs = concat
      [ case lookup n oldIssues of
          Nothing -> ["#" ++ n ++ " newly tracked (" ++ why ++ ")"]
          Just prev -> [ "#" ++ n ++ " " ++ k ++ ": " ++ showScalar (field k prev)
                         ++ " -> " ++ showScalar (field k cur) ++ "  [" ++ why ++ "]"
                       | k <- ["state", "merged", "comments"]
                       , field k prev /= field k cur ]
      | (n, cur) <- newIssues
      , let why = maybe "" id (lookup (read n) tracked)
      ]
    newCli = members "cli" new
    oldCli = members "cli" old
    cliMsgs =
      [ "CLI now has: orca " ++ label
      | (label, VBool True) <- newCli
      , lookup label oldCli /= Just (VBool True)
      ]
    versionMsgs =
      let ov = field "orca_version" old
          nv = field "orca_version" new
      in [ "orca version " ++ showScalar ov ++ " -> " ++ showScalar nv | ov /= nv ]

main :: IO ()
main = do
  args <- getArgs
  home <- getHomeDirectory
  let statePath = home ++ "/.local/state/orca-reorg-watch.json"
  snap <- runExceptT snapshot
  new <- case snap of
    Left e -> do
      hPutStrLn stderr ("probe failed: " ++ e)
      exitWith (ExitFailure 2)
    Right j -> pure j
  if "--show" `elem` args
    then do
      putStrLn (encodeIndent1 (toOut new))
      exitWith ExitSuccess
    else pure ()
  createDirectoryIfMissing True (takeDirectory statePath)
  exists <- doesFileExist statePath
  when ("--reset" `elem` args || not exists) $ do
    writeFile statePath (encodeIndent1 (toOut new))
    putStrLn "snapshot saved"
    exitWith ExitSuccess
  oldText <- readFile statePath
  old <- maybe (hPutStrLn stderr "orca-reorg-watch: unreadable state" >> exitWith (ExitFailure 1))
               pure (parseJson oldText)
  let msgs = diffSnapshots old new
  when (null msgs) $ do
    putStrLn "no change"
    exitWith ExitSuccess
  putStrLn (intercalate "\n" msgs)
  writeFile statePath (encodeIndent1 (toOut new))
  exitWith (ExitFailure 10)
