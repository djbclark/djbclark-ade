-- | session-load-watch: ask a busy agent session to offload work; never kill it. No model calls.
--
--   session-load-watch <PID> <relay-target> [--threshold PCT] [--window N] [--interval S]
--                      [--cooldown S] [--once] [--dry-run]
--
--   PID           the agent TUI's process id; its whole child tree is summed (ps %cpu, 100 = one core).
--   relay-target  what relay.py takes: a session id, name, or herdr pane (w34:p4).
--   Trigger       every one of the last --window samples (spaced --interval s) is >= --threshold.
--   Action        one relay.py line asking the session to hand the slice to acp-dispatch or defer it,
--                 then quiet for --cooldown s. The session is never signalled.
--   Exit          --once: 0 quiet, 2 would-trigger (asked, or dry-run), 3 target process gone.
module Main (main) where

import Control.Concurrent (threadDelay)
import Data.List (intercalate)
import qualified Data.Map.Strict as M
import qualified Data.Set as S
import Data.Time (defaultTimeLocale, formatTime, getZonedTime)
import Data.Time.Clock.POSIX (getPOSIXTime)
import System.Directory (getHomeDirectory)
import System.Environment (getArgs, getEnvironment)
import System.Exit (ExitCode (..), exitWith)
import System.IO (hFlush, hPutStrLn, stderr, stdout)
import System.Process (CreateProcess (..), createProcess, proc, readProcessWithExitCode, waitForProcess)
import Text.Printf (printf)
import Text.Read (readMaybe)

data Opts = Opts
  { oPid      :: Int
  , oTarget   :: String
  , oThresh   :: Double
  , oWindow   :: Int
  , oInterval :: Double
  , oCooldown :: Double
  , oOnce     :: Bool
  , oDryRun   :: Bool
  }

usage :: String
usage = "usage: session-load-watch [-h] [--threshold THRESHOLD] [--window WINDOW] [--interval INTERVAL]\n"
     ++ "                           [--cooldown COOLDOWN] [--once] [--dry-run]\n"
     ++ "                           pid target"

-- | argparse-style errors: usage and the message on stderr, exit 2.
argError :: String -> IO a
argError msg = do
  hPutStrLn stderr usage
  hPutStrLn stderr ("session-load-watch: error: " ++ msg)
  exitWith (ExitFailure 2)

defaults :: Opts
defaults = Opts 0 "" 150.0 6 10.0 1800.0 False False

-- | Parse argv: two positionals and the options, each option also as `--opt=value`.
parseArgs :: [String] -> IO Opts
parseArgs = go defaults []
  where
    go o pos [] = finish o (reverse pos)
    go o pos (a : as)
      | a `elem` ["-h", "--help"] = do
          putStrLn usage
          exitWith ExitSuccess
      | a == "--once" = go o { oOnce = True } pos as
      | a == "--dry-run" = go o { oDryRun = True } pos as
      | Just (name, val) <- splitOpt a = withValue name val as
      | a `elem` valueOpts = case as of
          (v : rest) -> withValue a v rest
          [] -> argError ("argument " ++ a ++ ": expected one argument")
      | otherwise = go o (a : pos) as
      where
        withValue name v rest = do
          o' <- setValue o name v
          go o' pos rest
    valueOpts = ["--threshold", "--window", "--interval", "--cooldown"]
    splitOpt s = case break (== '=') s of
      (name, '=' : v) | name `elem` valueOpts -> Just (name, v)
      _ -> Nothing
    setValue o name v = case name of
      "--threshold" -> maybe (bad name v) (\x -> pure o { oThresh = x }) (readMaybe v)
      "--window" -> maybe (bad name v) (\x -> pure o { oWindow = x }) (readMaybe v)
      "--interval" -> maybe (bad name v) (\x -> pure o { oInterval = x }) (readMaybe v)
      "--cooldown" -> maybe (bad name v) (\x -> pure o { oCooldown = x }) (readMaybe v)
      _ -> bad name v
    bad name v = argError ("argument " ++ name ++ ": invalid value: '" ++ v ++ "'")
    finish o [p, t] = case readMaybe p of
      Just pid -> pure o { oPid = pid, oTarget = t }
      Nothing -> argError ("argument pid: invalid int value: '" ++ p ++ "'")
    finish _ [] = argError "the following arguments are required: pid, target"
    finish _ [_] = argError "the following arguments are required: target"
    finish _ _ = argError "unrecognized arguments"

-- | Sum of %cpu over root and its descendants from one ps call; Nothing when root is gone.
treeCpu :: Int -> IO (Maybe Double)
treeCpu root = do
  (_, out, _) <- readProcessWithExitCode "/bin/ps" ["-axo", "pid=,ppid=,pcpu="] ""
  let rows = [ (pid, ppid, pct)
             | l <- lines out
             , [a, b, c] <- [words l]
             , Just pid <- [readMaybe a :: Maybe Int]
             , Just ppid <- [readMaybe b :: Maybe Int]
             , Just pct <- [readMaybe c :: Maybe Double]
             ]
      kids = M.fromListWith (++) [(ppid, [pid]) | (pid, ppid, _) <- rows]
      cpu = M.fromList [(pid, pct) | (pid, _, pct) <- rows]
  if not (M.member root cpu)
    then pure Nothing
    else pure (Just (walk kids cpu S.empty 0 [root]))
  where
    walk kids cpu seen total stack = case stack of
      [] -> total
      (pid : rest)
        | S.member pid seen -> walk kids cpu seen total rest
        | otherwise ->
            walk kids cpu (S.insert pid seen) (total + M.findWithDefault 0 pid cpu)
                 (M.findWithDefault [] pid kids ++ rest)

-- | Ask the session to offload, through relay.py; returns relay's exit status.
ask :: String -> Double -> Double -> Bool -> IO Int
ask target pct minutes dryRun = do
  let msg = "load watch: sustained ~" ++ printf "%.0f" pct ++ "% CPU for " ++ printf "%.0f" minutes
            ++ " min. Please offload or defer the heavy work instead of stopping this session: hand the slice"
            ++ " to acp-dispatch or park it with a note. Do not kill the session."
  if dryRun
    then do
      putStrLn ("DRY-RUN relay to " ++ target ++ ": " ++ msg)
      hFlush stdout
      pure 0
    else do
      home <- getHomeDirectory
      envNow <- getEnvironment
      let relay = home ++ "/src/djbclark-ade/skills/session-finder/relay.py"
          sender = case lookup "RELAY_SENDER_NAME" envNow of
            Just s | not (null s) -> s
            _ -> "session-load-watch"
          newEnv = ("RELAY_SENDER_NAME", sender) : filter ((/= "RELAY_SENDER_NAME") . fst) envNow
          -- --no-defer: a load-shedding ask is time-critical; queued until the busy session is idle, it
          -- would arrive after the load is gone.
          cp = (proc "python3" [relay, target, msg, "--no-defer", "--no-ack"]) { env = Just newEnv }
      (_, _, _, ph) <- createProcess cp
      rc <- waitForProcess ph
      pure $ case rc of
        ExitSuccess -> 0
        ExitFailure n -> n

say :: String -> IO ()
say s = putStrLn s >> hFlush stdout

fmtList :: [Double] -> String
fmtList xs = "[" ++ intercalate ", " [show (round x :: Int) | x <- xs] ++ "]"

main :: IO ()
main = do
  o <- getArgs >>= parseArgs
  let window = oWindow o
      interval = oInterval o
      minutes = fromIntegral window * interval / 60
      loop samples lastAsk = do
        mpct <- treeCpu (oPid o)
        case mpct of
          Nothing -> do
            say ("pid " ++ show (oPid o) ++ " gone")
            exitWith (ExitFailure 3)
          Just pct -> do
            let samples' = if window <= 0 then samples else drop (length samples + 1 - window) (samples ++ [pct])
                hot = length samples' == window && not (null samples') && minimum samples' >= oThresh o
                avg = sum samples' / fromIntegral (length samples')
            if oOnce o
              then
                if length samples' < window
                  then threadDelay (usec interval) >> loop samples' lastAsk
                  else if hot
                    then do
                      say ("would trigger: samples=" ++ fmtList samples')
                      _ <- ask (oTarget o) avg minutes (oDryRun o)
                      exitWith (ExitFailure 2)
                    else do
                      say ("quiet: samples=" ++ fmtList samples')
                      exitWith ExitSuccess
              else do
                now <- getPOSIXTime
                lastAsk' <- if hot && maybe True (\t -> realToFrac now - t >= oCooldown o) lastAsk
                  then do
                    rc <- ask (oTarget o) avg minutes (oDryRun o)
                    stamp <- getZonedTime
                    say ("asked " ++ oTarget o ++ " rc=" ++ show rc ++ " at " ++ formatTime defaultTimeLocale "%H:%M:%S" stamp)
                    pure (Just (realToFrac now))
                  else pure lastAsk
                threadDelay (usec interval)
                loop samples' lastAsk'
  loop [] (Nothing :: Maybe Double)
  where
    usec s = round (s * 1000000)
