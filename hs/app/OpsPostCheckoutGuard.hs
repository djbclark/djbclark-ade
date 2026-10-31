-- | ops-post-checkout-guard: post-checkout guard for ~/ops/* deploy checkouts.
--
-- Deploy checkouts must stay on master (see CLAUDE.md's "Where work happens" policy). After a
-- branch checkout this reacts after the fact: it heals the checkout back to master, pulls, and
-- prunes the stale branch, but only when the tree is clean and the branch's PR is merged. Anything
-- else is left alone and flagged on stderr.
--
-- Install: copy the wrapper that execs this entry point to .git/hooks/post-checkout in a deploy
-- checkout and chmod +x it. Git passes $1 = old HEAD, $2 = new HEAD, $3 = 1 for a branch checkout.
module Main (main) where

import Ade.Prelude (runCapture, warn)
import Control.Monad (unless, when)
import Data.List (isSuffixOf)
import System.Directory (findExecutable)
import System.Environment (getArgs)
import System.Exit (ExitCode (..), exitSuccess, exitWith)

-- | Trim trailing newlines and spaces, as command substitution does.
trimOut :: String -> String
trimOut = reverse . dropWhile (`elem` " \t\r\n") . reverse

-- | Run a git command in the current directory and return its trimmed stdout.
gitOut :: [String] -> IO (Int, String)
gitOut args = do
  (rc, out, _) <- runCapture ("git" : args)
  pure (rc, trimOut out)

-- | Exit with the failing command's status, as `set -e` does.
must :: (Int, String, String) -> IO ()
must (rc, _, _) = when (rc /= 0) $ exitWith (ExitFailure rc)

-- | `basename -s .git`: the last path component with a trailing `.git` removed.
baseNameNoGit :: String -> String
baseNameNoGit s =
  let trimmed = reverse (dropWhile (== '/') (reverse s))
      name = reverse (takeWhile (/= '/') (reverse trimmed))
  in if ".git" `isSuffixOf` name then take (length name - 4) name else name

-- | `basename "$(dirname "$url")"`.
ownerOf :: String -> String
ownerOf url =
  let dir = reverse (drop 1 (dropWhile (/= '/') (reverse url)))
  in reverse (takeWhile (/= '/') (reverse dir))

main :: IO ()
main = do
  args <- getArgs
  let isBranch = case drop 2 args of
        (x : _) -> x
        [] -> "0"
  unless (isBranch == "1") exitSuccess

  -- A linked worktree shares this hook but is not the deploy checkout: only the main working tree is
  -- guarded.
  (_, gitDir) <- gitOut ["rev-parse", "--path-format=absolute", "--absolute-git-dir"]
  (_, commonDir) <- gitOut ["rev-parse", "--path-format=absolute", "--git-common-dir"]
  unless (null gitDir || gitDir == commonDir) exitSuccess

  (_, branch) <- gitOut ["rev-parse", "--abbrev-ref", "HEAD"]
  when (null branch || branch == "master" || branch == "HEAD") exitSuccess

  warn ("\x26a0\xfe0f  post-checkout-guard: deploy checkout is now on '" ++ branch ++ "', not master.")

  (_, status) <- gitOut ["status", "--porcelain"]
  unless (null status) $ do
    warn "\x26a0\xfe0f  post-checkout-guard: working tree is DIRTY \x2014 refusing to auto-heal."
    warn "    A human needs to look at this before it's safe to touch. Leaving as-is."
    exitSuccess

  _ <- runCapture ["git", "fetch", "origin", "master", "-q"]

  (_, remoteUrl) <- gitOut ["config", "--get", "remote.origin.url"]
  let repoSlug = baseNameNoGit remoteUrl
      ownerSlug = ownerOf remoteUrl

  ghPath <- findExecutable "gh"
  merged <- case ghPath of
    Just _ | not (null repoSlug) && not (null ownerSlug) -> do
      (rc, out, _) <- runCapture
        [ "gh", "pr", "list", "--repo", ownerSlug ++ "/" ++ repoSlug
        , "--head", branch, "--state", "merged", "--json", "number", "--jq", "length" ]
      let prState = if rc /= 0 then "0" else trimOut out
      pure (prState /= "0")
    _ -> pure False

  if merged
    then do
      warn ("\x2705 post-checkout-guard: '" ++ branch ++ "' has a merged PR and the tree is clean \x2014 auto-healing to master.")
      must =<< runCapture ["git", "checkout", "master", "-q"]
      must =<< runCapture ["git", "pull", "-q", "origin", "master"]
      _ <- runCapture ["git", "branch", "-D", branch]
      (_, logLine) <- gitOut ["log", "--oneline", "-1"]
      warn ("\x2705 post-checkout-guard: back on master (" ++ logLine ++ ").")
    else do
      warn ("\x26a0\xfe0f  post-checkout-guard: could not confirm '" ++ branch ++ "' is merged \x2014 leaving it checked out.")
      warn "    If this branch's work is done, merge its PR (or check it out from a"
      warn "    task worktree instead) \x2014 this checkout should not be doing dev work."
