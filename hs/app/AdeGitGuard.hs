-- | ade-git-guard: a `git` front door for what git's own hooks cannot see in a workspace another
-- agent owns.
--
-- Two enforcement points (O2, 2026-10-25; docs/git-guard.md): git's hooks guard refs, and this
-- guard covers what hooks cannot see: a foreign workspace (read-only allowlist), the shared
-- checkout's destructive forms, `worktree remove|move|prune`, `branch -m|-c` destinations, and it
-- fails closed on what it cannot read. The rules themselves live in bin/ade_claims.py, which this
-- port calls as `python3 -I -S ade_claims.py guard -- ARGS`, exactly as the shell shim did.
--
--   ade-git-guard git-ARGS...             the guard, called by name
--   ade-git-guard install [DIR]           install the hook stubs into DIR's repository
--   ade-git-guard --real-git              print the git this guard would run
--   ade-git-guard --help
--
-- Order of work: (1) not an agent process (neither ACP_RUN_AGENT=1 nor ADE_CLAIM_ID set): exec the
-- real git; (2) inside a git hook (GIT_INDEX_FILE or PRE_COMMIT set): exec the real git; (3) a
-- plain read (status log show diff ...): exec the real git without scanning arguments; (4) the
-- rules: exit 0 runs git, 77 refuses, anything else fails open with a warning.
--
-- Exit codes: 77 refused (EX_NOPERM); every other code is the real git's.
--
-- Environment: ADE_CLAIM_ID, ACP_RUN_AGENT, ADE_STATE_DIR, ADE_REAL_GIT (skip the PATH search),
-- ADE_PYTHON (default python3), and ADE_CLAIMS_PY (path to bin/ade_claims.py; the shell shim found
-- it next to itself through its symlink, which a compiled program cannot do).
--
-- Port notes: the shell shim decided "am I the shim" by comparing inodes; here ADE_GUARD_SELF names
-- the shim path to skip (the installer sets it). The `git` shim form is selected with
-- ADE_GUARD_AS_GIT=1, since the program's own name is not the tool's name under ade-hs-run.
module Main (main) where

import Control.Exception (IOException, try)
import Control.Monad (filterM)
import System.Directory (Permissions, canonicalizePath, doesFileExist, executable, findExecutable, getPermissions)
import System.Environment (getArgs, lookupEnv, setEnv)
import System.Exit (ExitCode (..), exitWith)
import System.IO (hPutStrLn, stderr)
import System.Posix.Process (executeFile)
import System.Process (rawSystem)

usage :: String
usage = unlines
  [ "ade-git-guard — a `git` front door for what git's own hooks cannot see in a workspace another"
  , "agent owns."
  , ""
  , "  git ARGS...                           (the shim) run the real git, or refuse with exit 77"
  , "  ade-git-guard git-ARGS...             the same, called by name"
  , "  ade-git-guard install [DIR]           install the hook stubs into DIR's repository (exit 2 not a"
  , "                                        repository, 78 core.hooksPath is set, 73 NAME.pre-ade is in the way)"
  , "  ade-git-guard --real-git              print the git this guard would run"
  , "  ade-git-guard --help"
  , ""
  , "Exit codes: 77 refused (EX_NOPERM); every other code is the real git's."
  , "Environment: ADE_CLAIM_ID, ACP_RUN_AGENT, ADE_STATE_DIR, ADE_REAL_GIT, ADE_PYTHON, ADE_CLAIMS_PY."
  ]

plainReads :: [String]
plainReads =
  [ "status", "log", "show", "diff", "rev-parse", "ls-files", "ls-tree", "cat-file", "blame", "describe"
  , "rev-list", "for-each-ref", "grep", "shortlog", "name-rev", "merge-base", "version", "help" ]

main :: IO ()
main = do
  args <- getArgs
  asGit <- lookupEnv "ADE_GUARD_AS_GIT"
  self <- maybe "" id <$> lookupEnv "ADE_GUARD_SELF"
  real <- findRealGit self
  case real of
    Nothing -> hPutStrLn stderr "ade-git-guard: no real git found on PATH" >> exitWith (ExitFailure 127)
    Just g -> dispatch asGit g args

dispatch :: Maybe String -> FilePath -> [String] -> IO ()
dispatch asGit real args
  | asGit == Nothing = case args of
      [] -> putStr usage >> exitWith ExitSuccess
      ["-h"] -> putStr usage >> exitWith ExitSuccess
      ["--help"] -> putStr usage >> exitWith ExitSuccess
      ["--real-git"] -> putStrLn real >> exitWith ExitSuccess
      ("install" : rest) -> do
        rc <- runPython ("install" : rest) real
        case rc of
          Nothing -> hPutStrLn stderr "ade-git-guard: install needs python3 and bin/ade_claims.py" >> exitWith (ExitFailure 1)
          Just c -> exitWith c
      _ -> guarded real args
  | otherwise = guarded real args

-- | Steps 1 to 4 of the guard, then exec the real git (or refuse).
guarded :: FilePath -> [String] -> IO ()
guarded real args = do
  agent <- lookupEnv "ADE_CLAIM_ID"
  runner <- lookupEnv "ACP_RUN_AGENT"
  indexFile <- lookupEnv "GIT_INDEX_FILE"
  preCommit <- lookupEnv "PRE_COMMIT"
  let notAgent = null (maybe "" id agent) && maybe True (`elem` ["", "0"]) runner
      inHook = maybe False (const True) indexFile || maybe False (const True) preCommit
  if notAgent || inHook
    then execGit real args
    else if plainRead args
      then execGit real args
      else do
        rc <- runPython ("guard" : "--" : args) real
        case rc of
          Just ExitSuccess -> execGit real args
          Just (ExitFailure 77) -> exitWith (ExitFailure 77)
          other -> do
            let code = case other of
                  Just (ExitFailure n) -> n
                  _ -> 126
            hPutStrLn stderr ("ade-git-guard: guard unavailable or failed (rc=" ++ show code ++ "); running git unguarded")
            execGit real args

-- | Subcommand after skipping -C DIR, -c K=V and the value-less global flags. An unknown dashed
-- word stops the scan and is not a plain read.
plainRead :: [String] -> Bool
plainRead = go
  where
    go [] = False
    go (a : as)
      | a `elem` ["-C", "-c"] = go (drop 1 as)
      | a `elem` ["--no-pager", "-P", "-p", "--paginate", "--no-optional-locks", "--no-replace-objects", "--literal-pathspecs"] = go as
      | take 10 a == "--git-dir=" || take 12 a == "--work-tree=" = go as
      | take 1 a == "-" = False
      | otherwise = a `elem` plainReads

-- | Run `python3 -I -S ade_claims.py ARGS`. Nothing when python or the library is missing.
runPython :: [String] -> FilePath -> IO (Maybe ExitCode)
runPython argv real = do
  py <- maybe "python3" id <$> lookupEnv "ADE_PYTHON"
  lib <- maybe "" id <$> lookupEnv "ADE_CLAIMS_PY"
  libOk <- if null lib then pure False else doesFileExist lib
  pyOk <- maybe False (const True) <$> findExecutable py
  if not (libOk && pyOk) then pure Nothing else do
    setEnv "ADE_REAL_GIT" real
    r <- try (rawSystem py (["-I", "-S", lib] ++ argv)) :: IO (Either IOException ExitCode)
    pure (either (const Nothing) Just r)

execGit :: FilePath -> [String] -> IO ()
execGit real args = do
  r <- try (executeFile real False args Nothing) :: IO (Either IOException ())
  case r of
    Left e -> hPutStrLn stderr ("ade-git-guard: cannot run " ++ real ++ ": " ++ show e) >> exitWith (ExitFailure 127)
    Right () -> pure ()

-- | The first executable `git` on PATH that is not the shim itself, else the usual install paths.
findRealGit :: FilePath -> IO (Maybe FilePath)
findRealGit self = do
  envReal <- lookupEnv "ADE_REAL_GIT"
  selfReal <- if null self then pure "" else canonicalizePath self
  case envReal of
    Just r | not (null r) -> do
      ok <- isExec r
      if ok then pure (Just r) else search selfReal
    _ -> search selfReal
  where
    search selfReal = do
      pathDirs <- maybe [] (splitOn ':') <$> lookupEnv "PATH"
      cands <- filterM isExec [d ++ "/git" | d <- pathDirs, not (null d)]
      fromPath <- firstNotSelf selfReal cands
      case fromPath of
        Just p -> pure (Just p)
        Nothing -> filterM isExec ["/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git"]
                     >>= firstNotSelf selfReal
    firstNotSelf _ [] = pure Nothing
    firstNotSelf selfReal (c : cs) = do
      cr <- canonicalizePath c
      if cr == selfReal then firstNotSelf selfReal cs else pure (Just c)

isExec :: FilePath -> IO Bool
isExec p = do
  ok <- doesFileExist p
  if not ok then pure False else do
    r <- try (getPermissions p) :: IO (Either IOException Permissions)
    pure (either (const False) executable r)

splitOn :: Char -> String -> [String]
splitOn c s = case break (== c) s of
  (a, []) -> [a]
  (a, _ : rest) -> a : splitOn c rest
