-- | app-tamer-ab: A/B log for "does App Tamer cost more than it saves" (djbclark, 2026-10-23).
--
--   app-tamer-ab run               sample every 60 s into the CSV until killed (run it with nohup)
--   app-tamer-ab phase LABEL       set the phase label stamped on each row (e.g. with-trimmed, without, with-full)
--   app-tamer-ab summary [HOURS]   per-phase mean/p90 of load per core, swap and compressor churn
--
-- CSV: ~/.local/state/load-watch/app-tamer-ab/samples.csv
--   utc,phase,load1,per_core,churn_pages_s,swap_used_mb,at_running,at_cpu_s
-- at_cpu_s is cumulative CPU seconds of App Tamer plus its helper (0 when not running); its delta is the cost.
-- Read-only on the system: it signals and kills nothing. Phase changes are explicit commands, never automatic.
--
-- Port of bin/app-tamer-ab (HEAD). The awk/python stages are done in Haskell: `ps` and `sysctl`
-- are still called as argv, the admit JSON is read by a small JSON reader, and the summary is
-- computed over the CSV directly. Numbers from the admit JSON are copied as the literal text, which
-- matches Python's str() for the values load-watch emits.
module Main (main) where

import Control.Exception (IOException, try)
import Control.Monad (forM_, unless, when)
import Data.Char (isDigit, isSpace)
import Data.List (foldl', intercalate, isInfixOf, sort)
import Data.Maybe (fromMaybe, mapMaybe)
import Data.Time.Clock (NominalDiffTime, UTCTime, addUTCTime, getCurrentTime)
import Data.Time.Format (defaultTimeLocale, formatTime)
import Data.Time.Format.ISO8601 (iso8601ParseM)
import System.Directory (createDirectoryIfMissing, doesFileExist)
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath ((</>))
import System.IO (hPutStrLn, stderr)
import System.Process (readProcessWithExitCode)
import Control.Concurrent (threadDelay)

-- | Run argv; a missing binary is status 127, and stdout/stderr are returned.
capture :: String -> [String] -> IO (ExitCode, String, String)
capture cmd args = do
  r <- try (readProcessWithExitCode cmd args "") :: IO (Either IOException (ExitCode, String, String))
  pure $ case r of
    Left e -> (ExitFailure 127, "", show e)
    Right t -> t

envOr :: String -> IO (Maybe String)
envOr k = do
  m <- lookupEnv k
  pure $ case m of
    Just v | not (null v) -> Just v
    _ -> Nothing

-- | Split on any of the given separator characters.
splitOnAny :: String -> String -> [String]
splitOnAny seps s = case break (`elem` seps) s of
  (a, []) -> [a]
  (a, _ : rest) -> a : splitOnAny seps rest

-- | Cumulative CPU seconds of the processes whose `ps` line contains NAME; 0 when absent.
-- Mirrors the gawk stage: the first field is split on ':' and '.', and s += t1*60 + t2 + t3/100.
cpuSeconds :: String -> IO Double
cpuSeconds name = do
  (_, out, _) <- capture "ps" ["-axo", "time=,comm="]
  let contributions =
        [ t1 * 60 + t2 + t3 / 100
        | line <- lines out
        , name `isInfixOf` line
        , let firstField = takeWhile (not . isSpace) (dropWhile isSpace line)
        , let parts = map readNum (splitOnAny ":." firstField)
        , let t1 = part parts 0
        , let t2 = part parts 1
        , let t3 = part parts 2
        ]
  pure (sum contributions)
  where
    part ps i = if i < length ps then ps !! i else 0
    readNum w = case reads (fixNum w) :: [(Double, String)] of
      [(v, _)] -> v
      _ -> 0
    fixNum w = if null w then "0" else w

-- | Two-decimal fixed format with nan as Python prints it.
fmtFixed :: Int -> Double -> String
fmtFixed d x
  | isNaN x = "nan"
  | otherwise = showFixed d x

showFixed :: Int -> Double -> String
showFixed d x =
  let scale = 10 ^ d :: Integer
      n = round (abs x * fromIntegral scale) :: Integer
      (ip, fp) = n `divMod` scale
      sign = if x < 0 && n /= 0 then "-" else ""
      fracStr = if d == 0 then "" else "." ++ pad (show fp)
      pad s = replicate (d - length s) '0' ++ s
   in sign ++ show ip ++ fracStr

padL :: Int -> String -> String
padL w s = replicate (w - length s) ' ' ++ s

padR :: Int -> String -> String
padR w s = s ++ replicate (w - length s) ' '

-- | Minimal JSON reader: enough to look up top-level scalar keys of the admit object.
data JVal = JNum String | JStr String | JBool Bool | JNull | JOther
  deriving (Eq, Show)

parseJsonObject :: String -> Maybe [(String, JVal)]
parseJsonObject s = case skipWs s of
  '{' : rest -> members (skipWs rest)
  _ -> Nothing
  where
    members ('}' : _) = Just []
    members str = do
      (k, r1) <- parseString (skipWs str)
      r2 <- case skipWs r1 of
        ':' : r -> Just r
        _ -> Nothing
      (v, r3) <- parseValue (skipWs r2)
      case skipWs r3 of
        ',' : r -> ((k, v) :) <$> members (skipWs r)
        '}' : _ -> Just [(k, v)]
        _ -> Nothing

skipWs :: String -> String
skipWs = dropWhile isSpace

parseString :: String -> Maybe (String, String)
parseString ('"' : rest) = go rest ""
  where
    go ('"' : r) acc = Just (reverse acc, r)
    go ('\\' : c : r) acc = go r (esc c : acc)
    go (c : r) acc = go r (c : acc)
    go [] _ = Nothing
    esc 'n' = '\n'
    esc 't' = '\t'
    esc c = c
parseString _ = Nothing

parseValue :: String -> Maybe (JVal, String)
parseValue ('"' : r) = (\(s, r') -> (JStr s, r')) <$> parseString ('"' : r)
parseValue s@(c : _)
  | c == '-' || isDigit c =
      let (num, r) = span (\x -> isDigit x || x `elem` "-+.eE") s
       in Just (JNum num, r)
parseValue ('t' : 'r' : 'u' : 'e' : r) = Just (JBool True, r)
parseValue ('f' : 'a' : 'l' : 's' : 'e' : r) = Just (JBool False, r)
parseValue ('n' : 'u' : 'l' : 'l' : r) = Just (JNull, r)
parseValue (open : r) | open `elem` "[{" = skipNested (open : r)
parseValue _ = Nothing

-- | Skip an array or object we do not need, honouring nested brackets and strings.
skipNested :: String -> Maybe (JVal, String)
skipNested = go (0 :: Int) False
  where
    go _ _ [] = Nothing
    go depth inStr (c : cs)
      | inStr = case c of
          '\\' -> go depth True (drop 1 cs)
          '"' -> go depth False cs
          _ -> go depth True cs
      | c == '"' = go depth True cs
      | c `elem` "[{" = go (depth + 1) False cs
      | c `elem` "]}" = if depth == 1 then Just (JOther, cs) else go (depth - 1) False cs
      | otherwise = go depth False cs

-- | Python's str() of a decoded value, as the CSV row writes it.
pyStr :: Maybe JVal -> String
pyStr Nothing = ""
pyStr (Just v) = case v of
  JNum t -> t
  JStr s -> s
  JBool True -> "True"
  JBool False -> "False"
  JNull -> "None"
  JOther -> "{...}"

formatUtc :: UTCTime -> String
formatUtc = formatTime defaultTimeLocale "%Y-%m-%dT%H:%M:%SZ"

-- | One CSV sample: the same fields, in the same order, as the python one-liner wrote them.
sample :: FilePath -> FilePath -> FilePath -> IO ()
sample dir csv lw = do
  phaseFile <- try (readFile (dir </> "phase.txt")) :: IO (Either IOException String)
  let phase = case phaseFile of
        Right s -> takeWhile (/= '\n') s
        Left _ -> "unlabelled"
  (_, admOut, _) <- capture lw ["admit", "--json"]
  let adm = if all isSpace admOut then "{}" else admOut
  (_, vmOut, _) <- capture "sysctl" ["-n", "vm.swapusage"]
  let swap = case words vmOut of
        ws | length ws >= 6 -> filter (/= 'M') (ws !! 5)
        _ -> ""
  (pg, _, _) <- capture "pgrep" ["-x", "App Tamer"]
  let running = if pg == ExitSuccess then "1" else "0" :: String
  a <- cpuSeconds "App Tamer"
  b <- cpuSeconds "com.stclairsoft.AppTamer.Helper"
  let cpu = showFixed 2 (a + b)
  headerNeeded <- csvNeedsHeader csv
  when headerNeeded $ appendFile csv "utc,phase,load1,per_core,churn_pages_s,swap_used_mb,at_running,at_cpu_s\n"
  now <- getCurrentTime
  case parseJsonObject adm of
    Nothing -> hPutStrLn stderr "app-tamer-ab: admit JSON not an object; row skipped"
    Just obj -> do
      let get k = pyStr (lookup k obj)
          row = [formatUtc now, phase, get "load1", get "per_core", get "mem_churn_pages_s", swap, running, cpu]
      appendFile csv (intercalate "," row ++ "\n")

csvNeedsHeader :: FilePath -> IO Bool
csvNeedsHeader csv = do
  exists <- doesFileExist csv
  if not exists
    then pure True
    else do
      s <- readFile csv
      length s `seq` pure (null s)

-- | Summary rows: (utc, phase, columns by name).
type CsvRow = [(String, String)]

readCsv :: FilePath -> IO [CsvRow]
readCsv path = do
  text <- readFile path
  case lines text of
    [] -> pure []
    (hdr : rows) ->
      let names = splitOnAny "," hdr
       in pure [zip names (splitOnAny "," r) | r <- rows, not (null r)]

summary :: FilePath -> Double -> IO ()
summary csv hours = do
  rows <- readCsv csv
  now <- getCurrentTime
  let cut = addUTCTime (negate (realToFrac (hours * 3600) :: NominalDiffTime)) now
      keep = [r | r <- rows, Just t <- [utcOf r], t >= cut]
      phases = foldl' addPhase [] keep
      addPhase acc r =
        let ph = field "phase" r
         in if ph `elem` map fst acc
              then [(p, if p == ph then rs ++ [r] else rs) | (p, rs) <- acc]
              else acc ++ [(ph, [r])]
  putStrLn (padR 16 "phase" ++ padL 5 "n" ++ padL 11 "load/core" ++ padL 7 "p90" ++ padL 9 "swapMB" ++ padL 9 "churn" ++ padL 8 "p90" ++ padL 10 "AT cores")
  forM_ phases $ \(ph, rs) -> do
    let lc = col rs "per_core"
        ch = col rs "churn_pages_s"
        sw = col rs "swap_used_mb"
        cpu = col rs "at_cpu_s"
        cores
          | length cpu > 1 && last cpu >= head cpu =
              (last cpu - head cpu) / (fromIntegral (length rs) * 60)
          | otherwise = 0 / 0
    putStrLn $
      padR 16 ph
        ++ padL 5 (show (length rs))
        ++ padL 11 (fmtFixed 2 (mean lc))
        ++ padL 7 (fmtFixed 2 (p90 lc))
        ++ padL 9 (fmtFixed 0 (mean sw))
        ++ padL 9 (fmtFixed 0 (mean ch))
        ++ padL 8 (fmtFixed 0 (p90 ch))
        ++ padL 10 (fmtFixed 3 cores)
  where
    field k r = fromMaybe "" (lookup k r)
    utcOf r = iso8601ParseM (replaceZ (field "utc" r)) :: Maybe UTCTime
    replaceZ s = if not (null s) && last s == 'Z' then init s ++ "+00:00" else s
    col rs k = [v | r <- rs, let f = field k r, not (null f), Just v <- [readD f]]
    readD f = case reads (fixNum f) :: [(Double, String)] of
      [(v, _)] -> Just v
      _ -> Nothing
    fixNum f = if take 1 f == "." then '0' : f else f
    mean [] = 0 / 0
    mean xs = sum xs / fromIntegral (length xs)
    p90 [] = 0 / 0
    p90 xs =
      let v = sort xs
          i = floor (0.9 * fromIntegral (length v - 1) :: Double)
       in v !! i

usage :: IO a
usage = do
  hPutStrLn stderr "usage: app-tamer-ab run | phase LABEL | summary [HOURS]"
  exitWith (ExitFailure 2)

main :: IO ()
main = do
  home <- lookupEnv "HOME"
  let homeDir = fromMaybe "" home
  abDir <- envOr "AB_DIR"
  let dir = fromMaybe (homeDir ++ "/.local/state/load-watch/app-tamer-ab") abDir
      csv = dir </> "samples.csv"
  createDirectoryIfMissing True dir
  lwEnv <- envOr "LOAD_WATCH"
  let lw = fromMaybe (homeDir ++ "/src/djbclark-ade/bin/load-watch") lwEnv
  args <- getArgs
  case args of
    ["run"] -> forever' (sample dir csv lw >> threadDelay 60000000)
    ["phase", label] | not (null label) -> do
      writeFile (dir </> "phase.txt") (label ++ "\n")
      now <- getCurrentTime
      appendFile (dir </> "phases.log") (formatUtc now ++ " phase=" ++ label ++ "\n")
    ("phase" : _) -> do
      hPutStrLn stderr "usage: app-tamer-ab phase LABEL"
      exitWith (ExitFailure 2)
    ["summary"] -> summaryOrDie csv "24"
    ["summary", h] -> summaryOrDie csv h
    _ -> usage
  where
    forever' act = act >> forever' act
    summaryOrDie csv h = case reads (fixNum h) :: [(Double, String)] of
      [(hours, "")] -> do
        present <- doesFileExist csv
        unless present $ do
          hPutStrLn stderr ("app-tamer-ab: cannot read " ++ csv)
          exitWith (ExitFailure 1)
        summary csv hours
      _ -> hPutStrLn stderr ("app-tamer-ab: invalid HOURS " ++ show h) >> exitWith (ExitFailure 1)
    fixNum f = if take 1 f == "." then '0' : f else f
