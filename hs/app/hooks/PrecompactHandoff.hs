-- | precompact_handoff: PreCompact safety net and workspace resolver (hs-thunk port).
--
-- Hook mode (default): read Claude Code hook JSON on stdin and write a Tier 1 sidecar checkpoint,
-- precompact-<utc-ts>.md. Always exits 0: a compaction is never failed or delayed.
-- Resolve mode: `--resolve <dir>` prints "<repo>/<task>".
--
-- Port notes: the detached enrichment uses process's new_session (the Python start_new_session).
-- The workspace rules and the body layout are the original's, line for line.
module Main (main) where

import Ade.HsThunk.Hook
import Ade.JsonLite (Json (..), parseJson)
import Control.Monad (unless, when)
import Data.List (intercalate)
import Data.Maybe (fromMaybe)
import Data.Time (formatTime, defaultTimeLocale, getCurrentTime, getZonedTime)
import System.Directory
  ( canonicalizePath, createDirectoryIfMissing, doesFileExist, getCurrentDirectory )
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (takeFileName, (</>))
import System.IO (IOMode (..), withFile)
import System.Process (CreateProcess (..), StdStream (..), createProcess, proc)

-- | (repo, task) for any directory; ("no-git", "root") if anything goes wrong.
resolveWorkspace :: FilePath -> IO (String, String)
resolveWorkspace dir = do
  r <- tryAny (resolveInner dir)
  pure (either (const ("no-git", "root")) id r)

resolveInner :: FilePath -> IO (String, String)
resolveInner dir = do
  d <- canonicalizePath dir
  home <- homeDir
  let wt = relParts (home </> "src" </> "ops-worktrees") d
      ops = relParts (home </> "ops") d
  case wt of
    Just (task : repo : _) | task /= ".store" -> pure (repo, task)
    _ -> case ops of
      Just (repo : _) -> pure (repo, "ops")
      _ -> do
        mroot <- gitRoot d
        case mroot of
          Just root -> do
            let task = if d == root then "root" else intercalate "/" (fromMaybe [] (relParts root d))
            pure (safeSlug (takeFileName root), safeSlug task)
          Nothing -> pure ("no-git", safeSlug d)

-- | Parse the hook's stdin; anything unreadable is an empty object, as in the original.
parseStdin :: String -> Json
parseStdin raw
  | null (strip raw) = JObj []
  | otherwise = either (const (JObj [])) id (parseJson raw)

hookMain :: IO ()
hookMain = do
  raw <- readStdin
  let dataV = parseStdin raw
  cwdPath <- getCurrentDirectory
  (repo, task) <- resolveWorkspace cwdPath
  branch0 <- runGit cwdPath ["branch", "--show-current"]
  let branch = if null branch0 then "(not a git tree)" else branch0
  headSha <- runGit cwdPath ["rev-parse", "HEAD"]
  dirtyOut <- runGit cwdPath ["status", "--porcelain"]
  let dirty = intercalate "\n" (take 40 (lines dirtyOut))
  home <- homeDir
  let stateDir = home </> ".local/state/handoffs" </> repo </> task
  made <- tryAny (createDirectoryIfMissing True stateDir)
  case made of
    Left _ -> pure ()
    Right () -> case dataV of
      JObj _ -> checkpoint dataV stateDir repo task branch headSha dirty home
      _ -> pure ()  -- the original's data.get() raises here, after the mkdir, and exits 0

checkpoint :: Json -> FilePath -> String -> String -> String -> String -> String -> FilePath -> IO ()
checkpoint dataV stateDir repo task branch headSha dirty home = do
  now <- getZonedTime
  utcNow <- getCurrentTime
  let tsFile = formatTime defaultTimeLocale "%Y%m%dT%H%M%SZ" utcNow
      updated = formatTime defaultTimeLocale "%Y-%m-%dT%H:%M:%S%z" now
      trigger = textOr "unknown" "trigger"
      sessionId = textOr "unknown" "session_id"
      transcript = textOr "" "transcript_path"
      textOr def k = case field k dataV of
        JNull -> def
        JStr s -> s
        v -> renderCompact v
      body = intercalate "\n"
        [ "---"
        , "schema_version: 1"
        , "compacted: true"
        , "trigger: " ++ trigger
        , "updated_at: " ++ updated
        , "session_id: " ++ sessionId
        , "transcript_path: " ++ transcript
        , "repo: " ++ repo
        , "workspace: " ++ task
        , "branch: " ++ branch
        , "head_sha: " ++ headSha
        , "---"
        , ""
        , "## Dirty files at compaction"
        , ""
        , if null dirty then "clean" else "```\n" ++ dirty ++ "\n```"
        , ""
        , "Unplanned checkpoint written by precompact_handoff.py. Fold into"
        , "SESSION_LOG.md Recent History on next owned write, then delete me."
        , ""
        ]
      sidecar = stateDir </> ("precompact-" ++ tsFile ++ ".md")
  written <- tryAny (writeAtomic sidecar body)
  case written of
    Left _ -> pure ()
    Right () -> enrich home stateDir sidecar transcript

-- | Best-effort detached enrichment (the Haiku archivist mines the transcript). Single-shot,
-- never blocks, never fails the compaction.
enrich :: FilePath -> FilePath -> FilePath -> String -> IO ()
enrich home stateDir sidecar transcript = do
  flag <- lookupEnv "HANDOFF_ENRICH"
  unless (flag == Just "0") $ do
    let tools = home </> ".claude/hooks/handoff-tools"
        venvPy = tools </> ".venv/bin/python"
        enricher = tools </> "enrich_checkpoint.py"
    venvOk <- doesFileExist venvPy
    encOk <- doesFileExist enricher
    when (venvOk && encOk && not (null transcript)) $ do
      _ <- tryAny $ withFile (stateDir </> "enrich.log") AppendMode $ \logH -> do
        _ <- createProcess (proc venvPy [enricher, sidecar, transcript])
               { std_out = UseHandle logH, std_err = UseHandle logH, new_session = True }
        pure ()
      pure ()

main :: IO ()
main = do
  setUtf8
  args <- getArgs
  _ <- tryAny $ case args of
    ("--resolve" : dir : _) -> do
      (repo, task) <- resolveWorkspace dir
      putStrLn (repo ++ "/" ++ task)
    _ -> hookMain
  exitWith ExitSuccess
