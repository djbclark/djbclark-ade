-- | paseo-new-seat: create a Paseo seat with auto_accept ON from the first tool call.
--
-- WHY THIS EXISTS (2026-10-25)
--
-- `auto_accept` is defaulted to true only for an "unattended" create (Paseo's resolveACPCreateConfig), and
-- `paseo agent run` has no `--unattended` flag, so every seat created that way is an interactive create with
-- the feature undefined: a grey shield and a prompt on the first tool call. Setting the flag after creation
-- cannot fix a prompt that already fired, so the create must carry the feature. This tool uses the daemon's
-- own client (the path paseo-set-model uses) to create the agent with that config, then verifies the shield
-- from the agent's state file.
--
-- USAGE
--   paseo-new-seat --title "Dann Chat 3" --prompt "..." [--provider cline] [--model M]
--                  [--cwd DIR] [--workspace ID] [--thinking ID] [--mode ID] [--label k=v]... [--json]
--                  [--no-auto-accept] [--dry-run] [--probe]
--
-- --probe is for a throwaway test seat: it waits for the turn to end, then archives the agent (exit 5 when
-- the agent was created but could not be archived). Prefer --dry-run; use --probe only when the real create
-- path must run.
--
-- --mode is the provider's own permission-mode id. A claude seat gets `bypassPermissions` unless --mode says
-- otherwise; any other provider keeps its own default. --no-auto-accept drops that default too.
--
-- Exit: 0 created and verified; 1 error; 2 usage; 4 created but the shield did not come up green;
-- 5 --probe: created but not archived.
--
-- Port of bin/paseo-new-seat (HEAD). The Electron helper and the node module paseo-new-seat.mjs are
-- still run as before; the module is taken from PASEO_NEW_SEAT_MJS, or from the directory of this
-- binary. `-h` prints the USAGE block (the Python version prints its whole docstring).
module Main (main) where

import Control.Exception (IOException, try)
import Control.Monad (when)
import Data.Char (isSpace)
import Data.Maybe (fromMaybe)
import System.Directory (getHomeDirectory)
import System.Environment (getArgs, getEnvironment, getExecutablePath, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (takeDirectory, (</>))
import System.IO (Handle, hFlush, hPutStr, hPutStrLn, stderr, stdout)
import System.Process (ProcessHandle, createProcess, env, proc, readCreateProcessWithExitCode, readProcessWithExitCode, waitForProcess)
import Control.Concurrent (threadDelay)
import Text.Read (readMaybe)
import Ade.Json

appDir, defaultHelper, defaultCliDist :: FilePath
appDir = "/Applications/Paseo.app/Contents"
defaultHelper = appDir </> "Frameworks/Paseo Helper.app/Contents/MacOS/Paseo Helper"
defaultCliDist = appDir </> "Resources/app.asar/node_modules/@getpaseo/cli/dist"

usageText :: String
usageText = unlines
  [ "usage: paseo-new-seat --title TITLE [--prompt PROMPT] [--provider PROVIDER] [--model MODEL]"
  , "                      [--cwd CWD] [--workspace WORKSPACE] [--allow-new-workspace] [--mode MODE]"
  , "                      [--thinking THINKING] [--label LABEL] [--json] [--no-auto-accept] [--dry-run]"
  , "                      [--probe] [-h]"
  ]

usage :: IO ExitCode
usage = do
  hPutStr stderr usageText
  pure (ExitFailure 2)

data Opts = Opts
  { oTitle :: Maybe String
  , oPrompt :: String
  , oProvider :: String
  , oModel :: String
  , oCwd :: Maybe String
  , oWorkspace :: String
  , oAllowNew :: Bool
  , oMode :: String
  , oThinking :: String
  , oLabels :: [String]
  , oJson :: Bool
  , oNoAuto :: Bool
  , oDryRun :: Bool
  , oProbe :: Bool
  , oHelp :: Bool
  }

defaultOpts :: Opts
defaultOpts = Opts Nothing "" "cline" "cline-pass/deepseek-v4.1-flash" Nothing "" False "" "" [] False False False False False

-- | Parse argv as argparse would for these options; Nothing on any usage error.
parseOpts :: [String] -> Maybe Opts
parseOpts = go defaultOpts
  where
    go o [] = Just o { oLabels = reverse (oLabels o) }
    go o (x : rest) = case x of
      "-h" -> go o { oHelp = True } rest
      "--help" -> go o { oHelp = True } rest
      "--json" -> go o { oJson = True } rest
      "--no-auto-accept" -> go o { oNoAuto = True } rest
      "--dry-run" -> go o { oDryRun = True } rest
      "--probe" -> go o { oProbe = True } rest
      "--allow-new-workspace" -> go o { oAllowNew = True } rest
      _ | Just (name, val) <- splitEq x, name `elem` valued -> set name val rest o
        | x `elem` valued -> case rest of
            (v : more) -> set x v more o
            [] -> Nothing
        | otherwise -> Nothing
    valued = ["--title", "--prompt", "--provider", "--model", "--cwd", "--workspace", "--mode", "--thinking", "--label"]
    splitEq s = case break (== '=') s of
      (a, '=' : b) | take 2 a == "--" -> Just (a, b)
      _ -> Nothing
    set name v rest o = case name of
      "--title" -> go o { oTitle = Just v } rest
      "--prompt" -> go o { oPrompt = v } rest
      "--provider" -> go o { oProvider = v } rest
      "--model" -> go o { oModel = v } rest
      "--cwd" -> go o { oCwd = Just v } rest
      "--workspace" -> go o { oWorkspace = v } rest
      "--mode" -> go o { oMode = v } rest
      "--thinking" -> go o { oThinking = v } rest
      "--label" -> go o { oLabels = v : oLabels o } rest
      _ -> Nothing

-- | `float(os.environ[name])` with the Python fallback rules: non-finite or negative values use the default.
envFloat :: String -> Double -> IO Double
envFloat name def = do
  m <- lookupEnv name
  pure $ case m of
    Just v | not (null v) -> case readMaybe (fixLead v) of
      Just d | not (isNaN d), not (isInfinite d), d >= 0 -> d
      _ -> def
    _ -> def
  where
    fixLead x = if take 1 x == "." then '0' : x else x

paseoCmd :: IO String
paseoCmd = fromMaybe "paseo" <$> nonEmptyEnv "PASEO_NEW_SEAT_PASEO"

nonEmptyEnv :: String -> IO (Maybe String)
nonEmptyEnv k = do
  m <- lookupEnv k
  pure $ case m of
    Just v | not (null v) -> Just v
    _ -> Nothing

runPaseo :: [String] -> IO (ExitCode, String, String)
runPaseo argv = do
  cli <- paseoCmd
  r <- try (readProcessWithExitCode cli argv "") :: IO (Either IOException (ExitCode, String, String))
  pure $ case r of
    Left e -> (ExitFailure 127, "", show e)
    Right t -> t

-- | Wait for the probe's turn to end, then archive it. Never leaves the tab open silently.
archiveProbe :: String -> Double -> IO ExitCode
archiveProbe agentId waitS = do
  poll <- envFloat "PASEO_NEW_SEAT_POLL" 2
  let loop remaining
        | remaining <= 0 = pure ()
        | otherwise = do
            (code, out, _) <- runPaseo ["agent", "ls", "-g", "--json"]
            let rows = case parseJson out of
                  Just (VArr xs) | code == ExitSuccess -> [x | x@(VObj _) <- xs]
                  _ -> []
                row = [x | x <- rows, asStr (field "id" x) == Just agentId]
                done = case row of
                  (x : _) -> asStr (field "status" x) `notElem` [Just "running", Just "initializing"]
                  [] -> False
            if done
              then pure ()
              else do
                threadDelay (round (poll * 1000000))
                loop (remaining - poll)
  loop waitS
  (code, out, err) <- runPaseo ["agent", "archive", agentId]
  if code /= ExitSuccess
    then do
      let why = trim (if null (trim err) then out else err)
      hPutStrLn stderr ("paseo-new-seat: probe " ++ take 8 agentId ++ " created but not archived: " ++ why)
      pure (ExitFailure 5)
    else pure ExitSuccess
  where
    trim = dropWhile isSpace . reverse . dropWhile isSpace . reverse

defaultMode :: String -> String
defaultMode provider = if provider == "claude" then "bypassPermissions" else ""

main :: IO ()
main = do
  argv <- getArgs
  code <- run argv
  exitWith code

run :: [String] -> IO ExitCode
run argv = case parseOpts argv of
  Nothing -> usage
  Just o
    | oHelp o -> hPutStr stdout usageText >> pure ExitSuccess
    | otherwise -> case oTitle o of
        Nothing -> usage
        Just title -> launch o title

launch :: Opts -> String -> IO ExitCode
launch o title = do
  home <- getHomeDirectory
  let cwd = fromMaybe (home </> "src/techno-euphora") (oCwd o)
  if take 1 (oMode o) == "-"
    then do
      hPutStrLn stderr ("paseo-new-seat: --mode " ++ show (oMode o) ++ " is not a mode id")
      pure (ExitFailure 2)
    else do
      let mode
            | not (null (oMode o)) = oMode o
            | oNoAuto o = ""
            | otherwise = defaultMode (oProvider o)
          args =
            ["create", "--title", title, "--provider", oProvider o, "--model", oModel o, "--cwd", cwd]
              ++ opt "--prompt" (oPrompt o)
              ++ opt "--workspace" (oWorkspace o)
              ++ (if null mode then [] else ["--mode", mode])
              ++ (if oProvider o == "claude" && mode /= "bypassPermissions" then ["--label", "perm=ask"] else [])
              ++ opt "--thinking" (oThinking o)
              ++ concat [["--label", l] | l <- oLabels o]
              ++ (if oJson o || (oProbe o && not (oDryRun o)) then ["--json"] else [])
              ++ (if oAllowNew o then ["--allow-new-workspace"] else [])
              ++ (if oNoAuto o then [] else ["--auto-accept"])
              ++ (if oDryRun o then ["--dry-run"] else [])
      helperEnv <- nonEmptyEnv "PASEO_NEW_SEAT_HELPER"
      cliDist <- nonEmptyEnv "PASEO_NEW_SEAT_CLI_DIST"
      mjsOverride <- nonEmptyEnv "PASEO_NEW_SEAT_MJS"
      exe <- getExecutablePath
      let helper = fromMaybe defaultHelper helperEnv
          mjs = fromMaybe (takeDirectory exe </> "paseo-new-seat.mjs") mjsOverride
      base <- getEnvironment
      let childEnv =
            [ ("ELECTRON_RUN_AS_NODE", "1")
            , ("PASEO_NODE_ENV", "production")
            , ("PASEO_NEW_SEAT_CLI_DIST", fromMaybe defaultCliDist cliDist)
            ]
              ++ filter (\(k, _) -> k `notElem` map fst childEnv) base
          helperArgs = ["--disable-warning=DEP0040", mjs] ++ args
      if not (oProbe o) || oDryRun o
        then do
          hFlush stdout
          r <- try (createProcess (proc helper helperArgs) { env = Just childEnv })
            :: IO (Either IOException (Maybe Handle, Maybe Handle, Maybe Handle, ProcessHandle))
          case r of
            Left e -> do
              hPutStrLn stderr ("paseo-new-seat: cannot run " ++ helper ++ ": " ++ show e)
              pure (ExitFailure 1)
            Right (_, _, _, ph) -> do
              c <- waitForProcess ph
              pure c
        else probeRun helper helperArgs childEnv
  where
    opt k v = if null v then [] else [k, v]

-- | The --probe path: capture the helper's output, read the new agent id from its last line, archive.
probeRun :: FilePath -> [String] -> [(String, String)] -> IO ExitCode
probeRun helper helperArgs childEnv = do
  r <- try (readCreateProcessWithExitCode (proc helper helperArgs) { env = Just childEnv } "")
    :: IO (Either IOException (ExitCode, String, String))
  case r of
    Left e -> do
      hPutStrLn stderr ("paseo-new-seat: cannot run " ++ helper ++ ": " ++ show e)
      pure (ExitFailure 1)
    Right (rc, out, err) -> do
      hPutStr stdout out
      hPutStr stderr err
      let code = exitStatus rc
          agentId = case reverse (lines out) of
            (lastLine : _) -> parseJson lastLine >>= \v -> asStr (field "id" v)
            [] -> Nothing
      case agentId of
        Nothing -> do
          if code `elem` [0, 4]
            then hPutStrLn stderr "paseo-new-seat: --probe could not read the new agent id; not archived" >> pure (ExitFailure 5)
            else do
              when (code == 1) $
                hPutStrLn stderr "paseo-new-seat: helper failed; a seat may have been created and left open (paseo agent ls)"
              pure rc
        Just i
          | code `notElem` [0, 4] -> do
              a <- archiveProbe i 0
              pure (if a /= ExitSuccess then a else rc)
          | otherwise -> do
              wait <- envFloat "PASEO_NEW_SEAT_PROBE_WAIT" 120
              a <- archiveProbe i wait
              pure (if a /= ExitSuccess then a else rc)
  where
    exitStatus ExitSuccess = 0
    exitStatus (ExitFailure n) = n
