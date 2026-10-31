-- | claude-quota-guard: turn the Claude quota reading into a level that sessions act on.
--
--   claude-quota-guard [check]           probe aiuse, print the level, exit with it
--   claude-quota-guard status [--json]   print the state file, no probing
--   claude-quota-guard --install         launchd job: not ported (see below)
--
-- Levels and exit codes: 0 ok, 1 watch, 2 tight, 3 critical, 10 aiuse could not be read or the
-- data needs a path this port does not have, 64 bad CLAUDE_QUOTA_GUARD_THRESHOLDS, 69 `--install`
-- off macOS.
--
-- Levels (from the live `aiuse --available --json` rows only):
--   watch    weekly left < 40, Fable sublimit left < 15
--   tight    weekly left < 30
--   critical weekly left < 15, 5-hour left < 10, a Claude row with usable_now false, an exhausted
--            weekly or 5-hour window, or aiuse exit 3
--
-- Port scope, fail closed. Ported: the command line, the level rules above over live rows, the
-- exit codes, and `status`. NOT ported, and each one exits 10 without writing anything so a caller
-- cannot read a level it should not: the snapshot fallback (Claude absent from `available`), the
-- `conserve` alerts, CLAUDE_QUOTA_GUARD_THRESHOLDS overrides, the state file writes, the hermes-ping
-- rules, the stale-data rules and the lock. `check` never writes the state file in this build.
module Main (main) where

import Ade.JsonLite (Json (..), objLookup, parseJson)
import Control.Exception (IOException, try)
import Data.Char (toLower)
import Data.List (isInfixOf)
import System.Directory (doesFileExist, getHomeDirectory)
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath ((</>))
import System.Info (os)
import System.IO (hPutStrLn, stderr)
import System.Process (readCreateProcessWithExitCode, proc)
import System.Timeout (timeout)

data Level = Ok | Watch | Tight | Critical deriving (Eq, Ord, Show)

levelName :: Level -> String
levelName l = case l of
  Ok -> "ok"
  Watch -> "watch"
  Tight -> "tight"
  Critical -> "critical"

levelExit :: Level -> Int
levelExit l = case l of
  Ok -> 0
  Watch -> 1
  Tight -> 2
  Critical -> 3

-- | A window of a Claude row: its kind and the percentage left.
data Win = Win { wKind :: String, wLeft :: Double, wExhausted :: Bool }

main :: IO ()
main = do
  args <- getArgs
  case args of
    [] -> check
    ["check"] -> check
    ["status"] -> status False
    ["status", "--json"] -> status True
    ["--install"] -> install
    _ -> failWith 2 ("usage: claude-quota-guard [check] | status [--json] | --install\nunrecognized: " ++ unwords args)

failWith :: Int -> String -> IO a
failWith c msg = hPutStrLn stderr msg >> exitWith (ExitFailure c)

-- | Fail closed: report why this build will not judge the reading, and exit 10.
unreadable :: String -> IO a
unreadable why = failWith 10 ("claude-quota-guard: cannot judge the quota reading (" ++ why ++ "); no level written")

statePath :: IO FilePath
statePath = do
  home <- getHomeDirectory
  maybe (home </> ".local" </> "state" </> "ade" </> "quota-guard.json") id <$> lookupEnv "CLAUDE_QUOTA_GUARD_STATE"

status :: Bool -> IO ()
status asJson = do
  p <- statePath
  ok <- doesFileExist p
  if not ok
    then failWith 1 ("claude-quota-guard: no state file at " ++ p)
    else do
      r <- try (readFile p) :: IO (Either IOException String)
      case r of
        Left e -> failWith 1 ("claude-quota-guard: cannot read " ++ p ++ ": " ++ show e)
        Right text
          | asJson -> putStr text >> exitWith ExitSuccess
          | otherwise -> case parseJson text of
              Right (JObj kvs) -> do
                let lvl = maybe "?" pyStr (lookup "level" kvs)
                putStrLn ("claude-quota-guard: " ++ lvl)
                exitWith ExitSuccess
              _ -> failWith 1 ("claude-quota-guard: state file is not an object: " ++ p)

check :: IO ()
check = do
  overrides <- lookupEnv "CLAUDE_QUOTA_GUARD_THRESHOLDS"
  case overrides of
    Just _ -> unreadable "CLAUDE_QUOTA_GUARD_THRESHOLDS overrides are not ported"
    Nothing -> pure ()
  home <- getHomeDirectory
  exe <- maybe (home </> ".local" </> "bin" </> "aiuse") id <$> lookupEnv "CLAUDE_QUOTA_GUARD_AIUSE"
  r <- try (timeout (90 * 1000000) (readCreateProcessWithExitCode (proc exe ["--available", "--json"]) ""))
         :: IO (Either IOException (Maybe (ExitCode, String, String)))
  case r of
    Left e -> unreadable ("could not run " ++ exe ++ ": " ++ show e)
    Right Nothing -> unreadable (exe ++ " timed out")
    Right (Just (code, out, err)) -> do
      let rc = case code of
            ExitSuccess -> 0
            ExitFailure n -> n
      if rc /= 0 && rc /= 3
        then unreadable (exe ++ " exited " ++ show rc ++ ": " ++ take 300 (if null err then out else err))
        else judge rc out

judge :: Int -> String -> IO ()
judge rc out = do
  data' <- case parseJson (if null (words out) then "{}" else out) of
    Right (JObj kvs) -> pure (JObj kvs)
    _ | rc == 3 -> pure (JObj [])
      | otherwise -> unreadable "aiuse printed JSON that is not an object"
  case objLookup "alerts" data' of
    Just (JArr as) | any (isClaude) as -> unreadable "conserve alerts are not ported"
    _ -> pure ()
  rows <- case objLookup "available" data' of
    Nothing -> pure []
    Just (JArr items) | all isObj items -> pure [r | r <- items, isClaude r]
    Just _ -> unreadable "malformed `available` in the aiuse payload"
  let wins = concatMap windowsOf rows
      live = not (null wins)
      weekly = lowest "weekly" wins
      five = lowest "five_hour" wins
      fable = lowest "fable" wins
      blocked = any (\r -> objLookup "usable_now" r == Just (JBool False)) rows
                || any wExhausted [w | w <- wins, wKind w `elem` ["weekly", "five_hour"]]
  if not live && rc /= 3
    then unreadable "no Claude window in `available`; the snapshot fallback is not ported"
    else do
      let level
            | rc == 3 || blocked = Critical
            | maybe False ((< 15) . wLeft) weekly || maybe False ((< 10) . wLeft) five = Critical
            | maybe False ((< 30) . wLeft) weekly = Tight
            | maybe False ((< 40) . wLeft) weekly || maybe False ((< 15) . wLeft) fable = Watch
            | otherwise = Ok
      putStrLn ("claude-quota-guard: " ++ levelName level ++ " (" ++ summary [("weekly", weekly), ("5-hour", five), ("Fable", fable)] ++ ")")
      exitWith (if levelExit level == 0 then ExitSuccess else ExitFailure (levelExit level))
  where
    summary xs = unwords [n ++ " " ++ maybe "-" (\w -> show (round (wLeft w) :: Int) ++ "% left") v ++ ";" | (n, v) <- xs]

lowest :: String -> [Win] -> Maybe Win
lowest k ws = case [w | w <- ws, wKind w == k] of
  [] -> Nothing
  xs -> Just (foldr1 (\a b -> if wLeft a <= wLeft b then a else b) xs)

isObj :: Json -> Bool
isObj (JObj _) = True
isObj _ = False

isClaude :: Json -> Bool
isClaude r = objLookup "provider" r == Just (JStr "claude")

-- | Claude windows of one row, tagged weekly / five_hour / fable (labels and window_minutes as the Python does).
windowsOf :: Json -> [Win]
windowsOf row = case objLookup "windows" row of
  Just (JArr ws) -> [w | Just w <- map winOf ws]
  _ -> []
  where
    winOf w@(JObj _) = do
      label <- strOf "label" w `orElse` strOf "window_label" w
      let low = map toLower label
      left <- numOf "remaining_percent" w `orMaybe` (fmap (100 -) (numOf "used_percent" w))
      let fable = "fable" `isInfixOf` low || objLookup "pool_family" w == Just (JStr "fable")
                    || objLookup "quota_scope" w == Just (JStr "model_sublimit")
          minutes = numOf "window_minutes" w
          kind | fable = Just "fable"
               | "5-hour" `isInfixOf` low || "5 hour" `isInfixOf` low || minutes == Just 300 = Just "five_hour"
               | "weekly" `isInfixOf` low || minutes == Just 10080 = Just "weekly"
               | otherwise = Nothing
          exhausted = objLookup "state" w == Just (JStr "exhausted")
      k <- kind
      pure (Win k (if k == "fable" && exhausted then 0 else left) exhausted)
    winOf _ = Nothing
    orElse Nothing b = b
    orElse a _ = a
    orMaybe Nothing b = b
    orMaybe a _ = a
    strOf k o = case objLookup k o of
      Just (JStr s) -> Just s
      _ -> Nothing
    numOf k o = case objLookup k o of
      Just (JNum n) -> readNum n
      _ -> Nothing
    readNum n = case reads (fixNum n) :: [(Double, String)] of
      [(v, "")] -> Just v
      _ -> Nothing
    fixNum n = if take 1 n == "." then '0' : n else n

pyStr :: Json -> String
pyStr (JStr s) = s
pyStr (JNum n) = n
pyStr (JBool True) = "True"
pyStr (JBool False) = "False"
pyStr JNull = "None"
pyStr _ = "?"

install :: IO ()
install
  | os /= "darwin" = failWith 69 "claude-quota-guard: --install writes a launchd job and is macOS only; run `check` every 15 min from a systemd user timer or cron instead"
  | otherwise = failWith 1 "claude-quota-guard: --install is not ported in this build; use the Python tool"
