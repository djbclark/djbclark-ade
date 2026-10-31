-- | quota_nudge: tell a Claude session what the quota guard's level means for it (hs-thunk port).
--
-- Runs under UserPromptSubmit. Reads ONLY the state file that bin/claude-quota-guard writes (no
-- aiuse, no subprocess, no network) and prints that level's advice, prefixed "[quota-guard <level>]",
-- once per (session id, level). Also prints the unreadable episode line, the gate-profile line and
-- the frontier allowance line, as the Python original does. Always exits 0.
--
-- Port notes: the once-per-session memory is an ordered association list written atomically; the
-- lock is the same flock(2) as the Python hook (Ade.HsThunk.Lock). America/New_York comes from the
-- US DST rule in Ade.HsThunk.Time, not a zone database.
module Main (main) where

import Ade.HsThunk.Hook
import Ade.HsThunk.Lock (withFlock)
import Ade.HsThunk.Time (nyLocal, parseIso)
import Ade.JsonLite (Json (..), parseJson)
import Control.Monad (when)
import Data.Char (isDigit)
import Data.IORef (IORef, newIORef, readIORef, writeIORef)
import Data.Time (UTCTime, defaultTimeLocale, diffUTCTime, formatTime, getCurrentTime, utctDay)
import Data.Time.Calendar (toGregorian)
import System.Directory (createDirectoryIfMissing)
import System.Environment (lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (takeDirectory, (</>))
import System.IO (IOMode (..), hGetContents, hSetEncoding, utf8, withFile)
import Text.Read (readMaybe)

levels :: [String]
levels = ["ok", "watch", "tight", "critical"]

frontier1, judgment :: String
frontier1 = "Fable 5.1"
judgment = "Opus 5.5"

maxAgeSeconds, guardStateMaxAgeSeconds, maxSessions, lockRetries, lockWaitMicro :: Int
maxAgeSeconds = 2 * 3600
guardStateMaxAgeSeconds = 30 * 60
maxSessions = 200
lockRetries = 10
lockWaitMicro = 20000

-- | The once-per-session memory, in file order. Python dict semantics: a pop then a set moves a key
-- to the end, and the save keeps the last maxSessions entries.
type Nudges = [(String, Json)]

getN :: String -> Nudges -> Maybe Json
getN = lookup

setN :: String -> Json -> Nudges -> Nudges
setN k v kvs = filter ((/= k) . fst) kvs ++ [(k, v)]

nonEmpty :: Maybe String -> Maybe String
nonEmpty (Just s) | not (null s) = Just s
nonEmpty _ = Nothing

stateFile :: IO FilePath
stateFile = do
  override <- nonEmpty <$> lookupEnv "CLAUDE_QUOTA_GUARD_STATE"
  maybe (fmap (</> ".local/state/ade/quota-guard.json") homeDir) pure override

nudgeFile :: IO FilePath
nudgeFile = do
  override <- nonEmpty <$> lookupEnv "CLAUDE_QUOTA_NUDGE_STATE"
  maybe (fmap (</> ".claude/state/quota-nudges.json") homeDir) pure override

-- | _now(): CLAUDE_QUOTA_GUARD_NOW when it parses, else the clock.
nowUtc :: IO UTCTime
nowUtc = do
  raw <- lookupEnv "CLAUDE_QUOTA_GUARD_NOW"
  maybe getCurrentTime pure (raw >>= parseIso)

-- | A JSON value read as an ISO stamp (Python's _parse(str(text))): only strings parse.
parseJsonTime :: Json -> Maybe UTCTime
parseJsonTime (JStr s) = parseIso s
parseJsonTime _ = Nothing

-- | a - b in seconds (Python's (a - b).total_seconds()).
secondsBetween :: UTCTime -> UTCTime -> Double
secondsBetween a b = realToFrac (diffUTCTime a b)

readFileUtf8 :: FilePath -> IO String
readFileUtf8 p = withFile p ReadMode $ \h -> do
  hSetEncoding h utf8
  s <- hGetContents h
  length s `seq` pure s

-- | The file as JSON; Nothing when it is unreadable or not JSON.
loadJson :: FilePath -> IO (Maybe Json)
loadJson path = do
  r <- tryAny (readFileUtf8 path)
  pure $ case r of
    Right txt -> either (const Nothing) Just (parseJson txt)
    Left _ -> Nothing

-- | Python _fresh_guard_state: the state dict when checked_at parses and is at most 2 h old.
freshGuard :: UTCTime -> Maybe Json -> Maybe Json
freshGuard now (Just st@(JObj _)) = do
  checked <- parseJsonTime (field "checked_at" st)
  if secondsBetween now checked > fromIntegral maxAgeSeconds then Nothing else Just st
freshGuard _ _ = Nothing

loadNudges :: IO Nudges
loadNudges = do
  path <- nudgeFile
  m <- loadJson path
  pure $ case m of
    Just (JObj kvs) -> kvs
    _ -> []

-- | _unreadable_nudge: prints once per session per episode start. True when the memory changed.
unreadableNudge :: UTCTime -> Json -> String -> IORef Nudges -> IO Bool
unreadableNudge now raw sid ref
  | not (jTruthy (field "last_unreadable_pinged_at" raw)) = pure False
  | otherwise =
      case (parseJsonTime (field "unreadable_since" raw), parseJsonTime (field "last_unreadable_at" raw)) of
        (Just since, Just lastAt) | secondsBetween now lastAt <= fromIntegral maxAgeSeconds -> do
          let stamp = formatTime defaultTimeLocale "%Y-%m-%dT%H:%M:%SZ" since
              key = sid ++ "#unreadable"
          nudges <- readIORef ref
          if getN key nudges == Just (JStr stamp)
            then pure False
            else do
              putStrLn ("[quota-guard unreadable] aiuse unreadable since " ++ stamp
                        ++ ": check `aiuse --available --json`")
              writeIORef ref (setN key (JStr stamp) nudges)
              pure True
        _ -> pure False

-- | Python _frontier_text: the sentence, or Nothing unless the guard state says judged use is in
-- force now (checked_at within -60 s .. 30 min, judged true, an integer call cap).
frontierText :: UTCTime -> Json -> Maybe String
frontierText now st = do
  checked <- parseJsonTime (field "checked_at" st)
  let age = secondsBetween now checked
  if age < -60 || age > fromIntegral guardStateMaxAgeSeconds then Nothing else Just ()
  allow <- asObj (field "frontier_allowance" st)
  if field "judged" allow == JBool True then Just () else Nothing
  calls <- case field "agent_calls_per_day" allow of
    JNum n -> readMaybe n :: Maybe Int
    _ -> Nothing
  let cap | calls > 0 = "at most " ++ show calls ++ " Agent-tool calls today"
          | otherwise = "no Agent-tool call without asking"
  pure (frontier1 ++ " (frontier) is allowed where you judge it significantly better than " ++ judgment
        ++ "; give the reason in one line (acp-dispatch --kind frontier --frontier-reason \"...\"; "
        ++ "Agent tool: a \"frontier-reason: ...\" prompt line), " ++ cap)

asObj :: Json -> Maybe Json
asObj o@(JObj _) = Just o
asObj _ = Nothing

-- | The gate-profile line (one per session per New York day while an unexpired profile is set), or
-- the standing frontier allowance line when no profile speaks.
profileNudge :: UTCTime -> Json -> String -> IORef Nudges -> IO Bool
profileNudge now st sid ref = do
  let prof = field "profile" st
      nameOk = case field "name" prof of
        JStr _ -> True
        _ -> False
      untilM = if nameOk then parseJsonTime (field "until" prof) else Nothing
      (localNow, _) = nyLocal now
      today = formatTime defaultTimeLocale "%Y-%m-%d" localNow
      frontier = frontierText now st
  nudges <- readIORef ref
  case untilM of
    Just u | u > now -> do
      let (localUntil, zone) = nyLocal u
          key = sid ++ "#profile"
          rawUntil = case field "until" prof of
            JStr s -> s
            _ -> ""
          stamp = rawUntil ++ "|" ++ today
          name = case field "name" prof of
            JStr n | validName n -> n
            _ -> "gate"
          when' = formatTime defaultTimeLocale "%a %b" localUntil ++ " " ++ show (dayOf localUntil)
                  ++ " " ++ show (hour12 localUntil) ++ ":" ++ formatTime defaultTimeLocale "%M" localUntil
                  ++ " " ++ (if hourOf localUntil < 12 then "AM" else "PM") ++ " " ++ zone
      if getN key nudges == Just (JStr stamp)
        then pure False
        else do
          case frontier of
            Just f -> putStrLn ("[gates] " ++ name ++ " profile active until " ++ when' ++ ": " ++ f
                                ++ ". gate-profile clear restores normal routing.")
            Nothing -> putStrLn ("[gates] " ++ name ++ " profile active until " ++ when'
                                 ++ "; gate-profile clear restores normal routing")
          writeIORef ref (setN key (JStr stamp) nudges)
          pure True
    _ -> case frontier of
      Nothing -> pure False
      Just f -> do
        let key = sid ++ "#frontier"
        if getN key nudges == Just (JStr today)
          then pure False
          else do
            putStrLn ("[gates] frontier allowance: " ++ f ++ ".")
            writeIORef ref (setN key (JStr today) nudges)
            pure True
  where
    hourOf :: UTCTime -> Int
    hourOf t = read (formatTime defaultTimeLocale "%H" t)
    hour12 t = case hourOf t `mod` 12 of
      0 -> 12 :: Int
      h -> h
    dayOf t = let (_, _, d) = toGregorian (utctDay t) in d

-- | Profile names as ade_gates.NAME_RE: ASCII, a lowercase letter or digit first, up to 32 characters.
validName :: String -> Bool
validName n = case n of
  (c : cs) -> length n <= 32 && isLowerOrDigit c && all (\x -> isLowerOrDigit x || x `elem` "_-") cs
  [] -> False
  where
    isLowerOrDigit x = (x >= 'a' && x <= 'z') || isDigit x

-- | Python _level_nudge: prints the advice on a rise, and remembers every change of level.
levelNudge :: Json -> String -> IORef Nudges -> IO Bool
levelNudge st sid ref = case field "level" st of
  JStr level | level `elem` levels -> do
    nudges <- readIORef ref
    let shown = case getN sid nudges of
          Just (JStr s) | s `elem` levels -> s
          _ -> "ok"
        rank x = length (takeWhile (/= x) levels)
    when (level /= "ok" && rank level > rank shown) $
      case field "advice" st of
        JStr advice | not (null (strip advice)) ->
          putStrLn ("[quota-guard " ++ level ++ "] " ++ advice)
        _ -> pure ()
    if shown /= level
      then writeIORef ref (setN sid (JStr level) nudges) >> pure True
      else pure False
  _ -> pure False

-- | The session id as the original reads it: session_id, or "unknown" when falsy.
sessionIdOf :: Json -> String
sessionIdOf d = case field "session_id" d of
  JStr s | not (null s) -> s
  v | jTruthy v -> renderCompact v
  _ -> "unknown"

realMain :: IO ()
realMain = do
  raw <- readStdin
  let dataV = case parseJson raw of
        Right o@(JObj _) -> o
        _ -> JObj []
      sid = sessionIdOf dataV
  statePath <- stateFile
  guardState <- loadJson statePath
  case guardState of
    Just state@(JObj _) -> do
      nudgePath <- nudgeFile
      _ <- tryAny (createDirectoryIfMissing True (takeDirectory nudgePath))
      withFlock (nudgePath ++ ".lock") lockRetries lockWaitMicro $ \held ->
        when held $ do
          ref <- newIORef =<< loadNudges
          now <- nowUtc
          d1 <- unreadableNudge now state sid ref
          fresh <- freshGuard now <$> loadJson statePath
          (d2, d3) <- case fresh of
            Just st -> do
              a <- levelNudge st sid ref
              b <- profileNudge now st sid ref
              pure (a, b)
            Nothing -> pure (False, False)
          when (d1 || d2 || d3) $ do
            nudges <- readIORef ref
            let kept = drop (length nudges - maxSessions) nudges
            _ <- tryAny (writeAtomic nudgePath (renderCompact (JObj kept)))
            pure ()
    _ -> pure ()

main :: IO ()
main = do
  setUtf8
  _ <- tryAny realMain
  exitWith ExitSuccess
