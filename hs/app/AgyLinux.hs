-- | agy-linux: run the Linux build of the Antigravity CLI (agy) in an Apple `container` on this
-- Mac, with the current directory as its working dir.
--
-- Usage: agy-linux [agy args...]     agy-linux stop    stop the container (state is kept)
--
-- Port of bin/agy-linux (HEAD). Same container name, image, state directory, environment
-- pass-through, retry default and exit codes. The original `container list | jq` pipeline runs as
-- two argv calls with the listing written to jq's stdin, and the final `exec` becomes an execve of
-- `container`, so the agy process inherits the terminal.
--
-- Why the original exists (site-private memory project_agy_cli_burst_lockout_2026-10-03.md): the
-- macOS agy build was refused by Google's quota for this account, the Linux build was not.
-- AGY_CLI_MODEL_API_MAX_RETRIES defaults to 0 because agy's default of 8 retries per failed
-- request is what turned a burst into a lockout. Agents still use `acp-run agy`, never this.
module Main (main) where

import Control.Exception (IOException, try)
import Control.Monad (unless, when)
import Data.List (isPrefixOf)
import System.Directory (createDirectoryIfMissing, getCurrentDirectory)
import System.Environment (getArgs, getEnvironment, lookupEnv, setEnv)
import System.Exit (ExitCode (..), exitSuccess, exitWith)
import System.IO (hFlush, hIsTerminalDevice, hPutStr, hPutStrLn, stderr, stdin, stdout)
import System.Posix.Process (executeFile)
import System.Process (readProcessWithExitCode)

-- | Where an argv call's stdout goes.
data OutDest = OutNull | OutToStdout | OutToStderr

-- | Run argv and return (status, stdout, stderr). A missing binary is status 127, as in a shell.
capture :: [String] -> IO (ExitCode, String, String)
capture [] = pure (ExitFailure 127, "", "empty argv")
capture (cmd : args) = do
  r <- try (readProcessWithExitCode cmd args "") :: IO (Either IOException (ExitCode, String, String))
  pure $ case r of
    Left e -> (ExitFailure 127, "", show e)
    Right t -> t

-- | Run argv with an optional stdin, returning (status, stdout, stderr).
feed :: String -> [String] -> String -> IO (ExitCode, String, String)
feed cmd args input = do
  r <- try (readProcessWithExitCode cmd args input) :: IO (Either IOException (ExitCode, String, String))
  pure $ case r of
    Left e -> (ExitFailure 127, "", show e)
    Right t -> t

-- | Run argv the way `set -e` does: stdout to the chosen destination, stderr passed through, and
-- a nonzero status ends this program with that same status.
runChecked :: OutDest -> [String] -> IO ()
runChecked dest argv = do
  (code, out, err) <- capture argv
  case dest of
    OutNull -> pure ()
    OutToStdout -> hPutStr stdout out
    OutToStderr -> hPutStr stderr out
  hPutStr stderr err
  exitIfFailed code

-- | Run argv and return only whether it succeeded; output is discarded.
probe :: [String] -> IO Bool
probe argv = do
  (code, _, _) <- capture argv
  pure (code == ExitSuccess)

exitIfFailed :: ExitCode -> IO ()
exitIfFailed ExitSuccess = pure ()
exitIfFailed code = hFlush stdout >> hFlush stderr >> exitWith code

-- | `${VAR:-default}`: an unset or empty variable takes the default.
envOr :: String -> String -> IO String
envOr k d = do
  m <- lookupEnv k
  pure $ case m of
    Just v | not (null v) -> v
    _ -> d

-- | The `status` shell function: the state of the named container, read from
-- `container list --all --format json` through jq. Failures of either stage end the program
-- with that status, as `st=$(status)` does under `set -e` with pipefail.
containerState :: String -> IO String
containerState name = do
  (c1, listing, _) <- capture ["container", "list", "--all", "--format", "json"]
  (c2, out, _) <- feed "jq" ["-r", "--arg", "n", name, jqFilter] listing
  let statuses = [c | c <- [c1, c2], c /= ExitSuccess]
  case statuses of
    [] -> pure (trimNewlines out)
    _ -> exitIfFailed (last statuses) >> pure ""
  where
    jqFilter = ".[] | select(.configuration.id == $n) | .status.state? // .status"
    trimNewlines = reverse . dropWhile (== '\n') . reverse

-- | Environment names agy-linux forwards into the container: AGY_* and CLOUD_CODE_URL, with
-- names limited to upper-case letters, digits and underscores (the grep this replaces).
forwardedName :: String -> Bool
forwardedName k =
  k == "CLOUD_CODE_URL" || ("AGY_" `isPrefixOf` k && all okChar k)
  where
    okChar c = (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_'

main :: IO ()
main = do
  path <- maybe "" id <$> lookupEnv "PATH"
  setEnv "PATH" ("/opt/homebrew/bin:" ++ path)
  home <- lookupEnv "HOME"
  home' <- case home of
    Just h -> pure h
    Nothing -> hPutStrLn stderr "agy-linux: HOME: unbound variable" >> exitWith (ExitFailure 1)
  name <- envOr "AGY_LINUX_CONTAINER" "agy-linux"
  let image = "docker.io/library/ubuntu:24.04"
      stateDir = home' ++ "/.local/share/agy-linux/root"
      agy = "/root/.local/bin/agy"
  args <- getArgs

  case args of
    ("stop" : _) -> do
      _ <- capture ["container", "stop", name]
      exitSuccess
    _ -> pure ()

  st <- containerState name
  if null st
    then do
      hPutStrLn stderr ("agy-linux: creating container " ++ name ++ " (one-time, about a minute)")
      createDirectoryIfMissing True stateDir
      runChecked OutNull
        ["container", "run", "-d", "--name", name, "-v", stateDir ++ ":/root", "-v", home' ++ ":" ++ home', image, "sleep", "infinity"]
      runChecked OutToStderr
        [ "container", "exec", name, "sh", "-c"
        , "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates >/dev/null 2>&1"
        ]
    else when (st /= "running") $ runChecked OutNull ["container", "start", name]

  installed <- probe ["container", "exec", name, "test", "-x", agy]
  unless installed $ do
    hPutStrLn stderr "agy-linux: installing agy with Google's installer"
    runChecked OutToStderr
      ["container", "exec", name, "bash", "-c", "curl -fsSL https://antigravity.google/cli/install.sh | bash"]

  cwd <- getCurrentDirectory
  wd <-
    if (home' ++ "/") `isPrefixOf` (cwd ++ "/")
      then pure cwd
      else do
        hPutStrLn stderr ("agy-linux: " ++ cwd ++ " is outside $HOME (not mounted); using /root")
        pure "/root"

  inTerm <- (&&) <$> hIsTerminalDevice stdin <*> hIsTerminalDevice stdout
  let flags = if inTerm then ["-it"] else ["-i"]
  term <- envOr "TERM" "xterm-256color"
  retries <- envOr "AGY_CLI_MODEL_API_MAX_RETRIES" "0"
  env <- getEnvironment
  let forwarded =
        [ "-e" : (k ++ "=" ++ v) : []
        | (k, v) <- env
        , forwardedName k
        , k /= "AGY_CLI_MODEL_API_MAX_RETRIES"
        ]
      envs =
        concat
          ( [ ["-e", "TERM=" ++ term]
            , ["-e", "AGY_CLI_MODEL_API_MAX_RETRIES=" ++ retries]
            ]
              ++ forwarded
          )

  hFlush stdout
  hFlush stderr
  _ <- executeFile "container" True (["exec"] ++ flags ++ envs ++ ["-w", wd, name, agy] ++ args) Nothing
  pure ()
