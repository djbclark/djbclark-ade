-- | git-commit-own: commit only your own paths, without pre-commit's whole-tree stash.
--
-- Usage:
--
--   git-commit-own "<message>" <path>...
--   git-commit-own --staged "<message>"
--
-- Why (djbclark, 2026-10-24): a plain `git commit` runs pre-commit, which stashes every unstaged
-- change in the worktree for the duration of the hook run and restores it afterwards. Other agents
-- editing the same repo meanwhile see their edits vanish, then conflict on the restore.
-- `pre-commit run --files` runs the same hooks on named files without stashing anything, so this
-- runs that on the given paths and then commits them with --no-verify. A hook that rewrites a file
-- (a formatter) fails the first run; the second run checks the rewritten file, and the commit picks
-- it up.
--
-- Paths may be files or directories; deletions are committed too. With --staged the hooks run on
-- the staged file names and the commit takes the index only (no pathspec).
--
-- Exit codes: the status of the failing git or pre-commit step; 2 for a usage error.
module Main (main) where

import Ade.Prelude (warn)
import Control.Exception (IOException, try)
import Control.Monad (unless, when)
import Data.List (sort, nub)
import System.Directory (doesFileExist, findExecutable)
import System.Environment (getArgs)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath ((</>))
import System.Process
  ( CreateProcess (..)
  , createProcess
  , proc
  , waitForProcess
  , readCreateProcessWithExitCode
  )

usage :: String
usage = "usage: git-commit-own \"<message>\" <path>...   |   git-commit-own --staged \"<message>\""

usageExit :: IO a
usageExit = warn usage >> exitWith (ExitFailure 2)

-- | Run a command with inherited stdio, optionally in a directory. Returns its exit status.
runInherit :: Maybe FilePath -> String -> [String] -> IO ExitCode
runInherit dir cmd args = do
  (_, _, _, ph) <- createProcess (proc cmd args) { cwd = dir }
  waitForProcess ph

-- | Run a command and capture (status, stdout, stderr). A command that cannot be started is
-- status 127, as a shell reports it.
capture :: String -> [String] -> IO (ExitCode, String)
capture cmd args = do
  res <- try (readCreateProcessWithExitCode (proc cmd args) "") :: IO (Either IOException (ExitCode, String, String))
  pure $ case res of
    Left _ -> (ExitFailure 127, "")
    Right (c, o, _) -> (c, o)

-- | Lines of a captured stdout (empty output gives no lines).
linesOf :: String -> [String]
linesOf s = filter (not . null) (lines s)

-- | Split NUL-separated output, as `git ls-files -z` prints it.
nulSplit :: String -> [String]
nulSplit s = case break (== '\0') s of
  (x, []) -> [x | not (null x)]
  (x, _ : rest) -> [x | not (null x)] ++ nulSplit rest

main :: IO ()
main = do
  args0 <- getArgs
  let (staged, args1) = case args0 of
        "--staged" : rest -> (True, rest)
        _ -> (False, args0)
  (msg, paths) <- case args1 of
    m : ps | not (null m) -> pure (m, ps)
    _ -> usageExit
  when (staged && not (null paths)) usageExit
  when (not staged && null paths) usageExit

  (rootRc, rootOut) <- capture "git" ["rev-parse", "--show-toplevel"]
  unless (rootRc == ExitSuccess) $ exitWith rootRc
  let root = takeWhile (/= '\n') rootOut

  changed <-
    if staged
      then do
        (_, o) <- capture "git" ["diff", "--cached", "--name-only", "--diff-filter=d"]
        pure (linesOf o)
      else do
        (_, d) <- capture "git" (["diff", "--name-only", "--diff-filter=d", "HEAD", "--"] ++ paths)
        (_, u) <- capture "git" (["ls-files", "--full-name", "-o", "--exclude-standard", "--"] ++ paths)
        pure (nub (sort (linesOf d ++ linesOf u)))

  hasConfig <- doesFileExist (root </> ".pre-commit-config.yaml")
  precommit <- findExecutable "pre-commit"
  when (not (null changed) && hasConfig && precommit /= Nothing) $ do
    let run = runInherit (Just root) "pre-commit" (["run", "--files"] ++ changed)
    first <- run
    case first of
      ExitSuccess -> pure ()
      ExitFailure _ -> do
        second <- run
        unless (second == ExitSuccess) $ exitWith second

  if staged
    then do
      rc <- runInherit Nothing "git" ["commit", "--no-verify", "-m", msg]
      exitWith rc
    else do
      -- Untracked files need adding before a pathspec commit can take them.
      (_, untrackedOut) <- capture "git" (["ls-files", "-o", "--exclude-standard", "-z", "--"] ++ paths)
      let untracked = nulSplit untrackedOut
      unless (null untracked) $ do
        rc <- runInherit Nothing "git" (["add", "--"] ++ untracked)
        unless (rc == ExitSuccess) $ exitWith rc
      rc <- runInherit Nothing "git" (["commit", "--no-verify", "-m", msg, "--"] ++ paths)
      exitWith rc
