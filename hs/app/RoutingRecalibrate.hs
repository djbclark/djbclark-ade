-- | routing-recalibrate: monthly AI re-rank of routing.toml good_at from calibrate suggestions. No model.
--
--     routing-recalibrate [--dry-run]
--
-- Runs `route_agent.py calibrate --json --since 30`. With no suggestions, exits 0 after a one-line
-- note. Otherwise writes a brief under `~/.local/state/bigteam/routing-recalibrate/<date>/`,
-- dispatches it to Claude Opus high (`acp-dispatch ... --kind judgment --detach --no-wait`), and
-- hermes-pings. `--dry-run` prints the brief and the dispatch command and runs nothing (no write,
-- no dispatch, no ping).
--
-- Env: ROUTING_RECALIBRATE_STATE (brief root), ACP_DISPATCH (binary), ACP_DISPATCH_STATE
-- (calibrate input, via route_agent), ROUTING_RECALIBRATE_REPO (dispatch -C),
-- ROUTING_RECALIBRATE_PING (hermes-ping path), ADE_ROOT (the djbclark-ade checkout; the Python
-- original derived it from its own file path, a compiled program cannot), ADE_PYTHON (default
-- python3).
module Main (main) where

import Ade.JsonLite (Json (..), objLookup, parseJson, renderJson)
import Control.Exception (IOException, try)
import Data.List (intercalate, sortOn)
import Data.Time (defaultTimeLocale, formatTime, getZonedTime)
import System.Directory (createDirectoryIfMissing, doesFileExist, getHomeDirectory)
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath ((</>))
import System.IO (hPutStrLn, stderr)
import System.Process (proc, readCreateProcessWithExitCode, rawSystem)
import System.Timeout (timeout)

data Opts = Opts { optDryRun :: Bool }

main :: IO ()
main = do
  args <- getArgs
  case args of
    [] -> run (Opts False)
    ["--dry-run"] -> run (Opts True)
    _ -> do
      hPutStrLn stderr "usage: routing-recalibrate [-h] [--dry-run]"
      hPutStrLn stderr "routing-recalibrate: error: unrecognized arguments"
      exitWith (ExitFailure 2)

run :: Opts -> IO ()
run opts = do
  home <- getHomeDirectory
  ade <- maybe "." id <$> lookupEnv "ADE_ROOT"
  stateDir <- maybe (home </> ".local" </> "state" </> "bigteam" </> "routing-recalibrate") id
                <$> lookupEnv "ROUTING_RECALIBRATE_STATE"
  repo <- maybe ade id <$> lookupEnv "ROUTING_RECALIBRATE_REPO"
  acp <- maybe (ade </> "bin" </> "acp-dispatch") id <$> lookupEnv "ACP_DISPATCH"
  pingPath <- maybe (home </> ".local" </> "bin" </> "hermes-ping") id <$> lookupEnv "ROUTING_RECALIBRATE_PING"
  py <- maybe "python3" id <$> lookupEnv "ADE_PYTHON"
  -- The state dir exists before any write, so launchd can open its log paths on first load.
  createDirectoryIfMissing True stateDir
  report <- runCalibrate py (ade </> "bin" </> "route_agent.py")
  let suggestions = arrOf (objLookup "suggestions" report)
  date <- today
  if null suggestions
    then putStrLn ("routing-recalibrate: no suggestions (min_n=" ++ maybe "None" pyStr (objLookup "min_n" report) ++ ")")
    else do
      let briefText = buildBrief report suggestions date
          outDir = stateDir </> date
          briefPath = outDir </> "brief.md"
          cmd = dispatchCmd acp repo date briefPath
      if optDryRun opts
        then do
          putStrLn briefText
          putStrLn ("# dispatch: " ++ unwords cmd)
        else do
          createDirectoryIfMissing True outDir
          writeFile briefPath briefText
          writeFile (outDir </> "calibrate.json") (renderSorted report ++ "\n")
          rc <- rawSystem (head cmd) (tail cmd)
          case rc of
            ExitFailure n -> do
              hPutStrLn stderr ("routing-recalibrate: dispatch exited " ++ show n)
              hermesPing pingPath ("djbclark-ade: routing recalibrate dispatch failed (rc=" ++ show n ++ ")")
              exitWith (ExitFailure n)
            ExitSuccess -> do
              hermesPing pingPath ("djbclark-ade: routing recalibrate dispatched ("
                                   ++ show (length suggestions) ++ " suggestions)")
              putStrLn ("routing-recalibrate: brief " ++ briefPath)

-- | `route_agent.py calibrate --json --since 30`; a failure is passed on with its status.
runCalibrate :: String -> FilePath -> IO Json
runCalibrate py route = do
  r <- try (timeout (120 * 1000000)
              (readCreateProcessWithExitCode (proc py [route, "calibrate", "--json", "--since", "30"]) ""))
         :: IO (Either IOException (Maybe (ExitCode, String, String)))
  case r of
    Left e -> hPutStrLn stderr (show e) >> exitWith (ExitFailure 1)
    Right Nothing -> hPutStrLn stderr "routing-recalibrate: calibrate timed out" >> exitWith (ExitFailure 1)
    Right (Just (ExitFailure n, out, err)) -> do
      hPutStrLn stderr (if null (err ++ out) then "calibrate failed" else if null err then out else err)
      exitWith (ExitFailure (if n == 0 then 1 else n))
    Right (Just (ExitSuccess, out, _)) -> case parseJson out of
      Left e -> hPutStrLn stderr ("routing-recalibrate: calibrate output is not JSON: " ++ e) >> exitWith (ExitFailure 1)
      Right v -> pure v

arrOf :: Maybe Json -> [Json]
arrOf (Just (JArr xs)) = xs
arrOf _ = []

-- | Python's str() for a scalar, and json-ish text for anything else.
pyStr :: Json -> String
pyStr (JStr s) = s
pyStr (JNum n) = n
pyStr (JBool True) = "True"
pyStr (JBool False) = "False"
pyStr JNull = "None"
pyStr other = renderJson other

field :: String -> Json -> String
field k o = maybe "None" pyStr (objLookup k o)

-- | json.dumps(report, indent=2, sort_keys=True), recursively.
renderSorted :: Json -> String
renderSorted = renderJson . sortKeys
  where
    sortKeys (JObj kvs) = JObj (sortOn fst [(k, sortKeys v) | (k, v) <- kvs])
    sortKeys (JArr xs) = JArr (map sortKeys xs)
    sortKeys other = other

-- | The brief text, line for line as the Python original builds it.
buildBrief :: Json -> [Json] -> String -> String
buildBrief report suggestions date = unlines $
  [ "# Routing recalibrate " ++ date
  , ""
  , "You are re-ranking `good_at` in `config/routing.toml` from the calibrate"
  , "report below. Edit **only** the suggested service × kind ranks."
  , ""
  , "## Rules"
  , ""
  , "1. Change `good_at` ranks for the suggested groups only, by the listed delta"
  , "   (`+N` means worse / higher number; negative means better / lower number)."
  , "2. One commit; message lists each change with its before/after numbers and"
  , "   the done_rate vs peer median that justified it."
  , "3. Never change kinds eligibility, gates, reserve floors, frontier rows,"
  , "   burn_first flags, pace thresholds, or `[calibrate]` / `[discovery]` /"
  , "   `[dispatch]` / `[hermes]`."
  , "4. Never touch any group under the calibrate minimum (`min_n` in the JSON)."
  , "5. Run `tests/test_route_agent.py` (and pace/calibrate siblings) via"
  , "   `/Users/djbclark/ops/site-private/bin/bg uv run --with pytest python -m pytest -q ...`."
  , "6. Push the branch (or master, if that is where you work) when green."
  , ""
  , "## Suggestions"
  , ""
  ] ++ suggestionLines ++
  [ ""
  , "## Calibrate JSON"
  , ""
  , "```json"
  , renderSorted report
  , "```"
  , ""
  ]
  where
    suggestionLines
      | null suggestions = ["(none)"]
      | otherwise = map line suggestions
    line s =
      let delta = field "suggest_rank_delta" s
          sign = if isPositive delta then "+" else ""
      in "- `" ++ field "service" s ++ "` × `" ++ field "kind" s ++ "`: rank " ++ sign ++ delta
         ++ " (done " ++ field "done_rate" s ++ "% vs peer median " ++ field "peer_median_done_rate" s
         ++ "%, n=" ++ field "n" s ++ ") — " ++ field "reason" s
    isPositive ('-' : _) = False
    isPositive ('0' : _) = False
    isPositive _ = True

dispatchCmd :: FilePath -> FilePath -> String -> FilePath -> [String]
dispatchCmd acp repo date brief =
  [ acp, "claude", "--model", "opus", "--effort", "high", "--kind", "judgment"
  , "--name", "recalibrate-" ++ date, "--task", "routing-recalibrate"
  , "-C", repo, "-f", brief, "--detach", "--no-wait" ]

today :: IO String
today = do
  now <- getZonedTime
  pure (formatTime defaultTimeLocale "%Y-%m-%d" now)

hermesPing :: FilePath -> String -> IO ()
hermesPing path msg = do
  ok <- doesFileExist path
  if ok
    then () <$ rawSystem path [msg]
    else putStrLn msg
