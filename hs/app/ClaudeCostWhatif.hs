-- | claude-cost-whatif: what-if analysis on the last N days of Claude Code transcripts.
--
-- A. Cache TTL: observed (1h, writes 2.0x) vs 5-minute TTL (writes 1.25x, but a request after a
--    5-60 min idle gap re-writes its whole cached prefix instead of reading it).
-- B. Compaction threshold T: when context crosses T, compact to floor F (measured 104k); the
--    compaction costs a summarisation call (read C at the model's read rate, ~6k output at 5x) plus
--    re-writing F at the write weight; later requests in that transcript shrink by (C - F) until the
--    next one.
--
-- Units: input-token equivalents. Approximations, not billing.
--
-- Usage: claude-cost-whatif [DAYS]     (DAYS defaults to 7; a fractional value is accepted)
--
-- Reads ~/.claude/projects/**/*.jsonl. A timestamp without an offset is read in the local zone, as
-- Python's datetime.fromisoformat does. Exit 0 with the report on stdout; exit 1 when the argument
-- is not a number or there is no observed cost to compare against.
module Main (main) where

import Ade.Json (Value (..), field, parseJson)
import Ade.Prelude (warn)
import Control.Exception (IOException, try)
import Control.Monad (forM, forM_, when)
import qualified Data.ByteString as B
import Data.Char (isDigit, isSpace)
import Data.List (isPrefixOf, isInfixOf)
import qualified Data.Text as T
import qualified Data.Text.Encoding as TE
import Data.Text.Encoding.Error (lenientDecode)
import Data.Time.Calendar (Day, fromGregorian)
import Data.Time.Clock (DiffTime, UTCTime (..), addUTCTime, secondsToDiffTime)
import Data.Time.Clock.POSIX (POSIXTime, getPOSIXTime, utcTimeToPOSIXSeconds)
import Data.Time.LocalTime (LocalTime (..), TimeOfDay (..), getCurrentTimeZone, localTimeToUTC)
import Numeric (showFFloat)
import System.Directory (doesDirectoryExist, getHomeDirectory, getModificationTime, listDirectory)
import System.Environment (getArgs)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath ((</>), takeExtension)
import Text.Printf (printf)

-- | One assistant request.
data Req = Req
  { rT   :: Maybe POSIXTime  -- ^ timestamp, when present and parseable
  , rB   :: Double           -- ^ input price per token (model price / 1e6)
  , rR   :: Double           -- ^ cache-read multiplier of the model
  , rSub :: Bool             -- ^ from a sub-agent transcript
  , rIn  :: Double
  , rCW  :: Double           -- ^ cache creation (write) tokens
  , rCR  :: Double           -- ^ cache read tokens
  , rOut :: Double
  }

w1h, w5m, outMult, fTarget, summaryOut :: Double
w1h = 2.0
w5m = 1.25
outMult = 5.0
fTarget = 104000
summaryOut = 6000

-- | Per-million-token price table: (input price, cache-read multiplier); the first prefix wins.
prices :: [(String, (Double, Double))]
prices =
  [ ("claude-opus-5-5", (4.0, 0.05))
  , ("claude-sonnet-5-5", (2.0, 0.05))
  , ("claude-fable-5-1", (10.0, 0.025))
  ]

priceOf :: Maybe String -> (Double, Double)
priceOf model =
  let m = maybe "" id model
  in case [v | (k, v) <- prices, k `isPrefixOf` m] of
       (v : _) -> v
       [] -> (1.0, 0.1)

-- | One JSON document from a transcript line; a line that does not parse is a Left.
parseValue :: String -> Either String Value
parseValue s = maybe (Left "not JSON") Right (parseJson s)

-- | A JSON number as a Double; anything absent or non-numeric counts as 0, as `.get(k, 0)` would
-- give for a missing key.
numOf :: Maybe Value -> Double
numOf (Just (VNum s)) = readNum s
numOf _ = 0

-- | Read a JSON number literal (integer, fraction and exponent) as a Double.
readNum :: String -> Double
readNum s0 =
  let (sign, s1) = case s0 of
        '-' : r -> (-1, r)
        _ -> (1, s0)
      (ip, s2) = span isDigit s1
      (fp, s3) = case s2 of
        '.' : r -> span isDigit r
        _ -> ("", s2)
      ex = case s3 of
        e : r | e == 'e' || e == 'E' -> case r of
          '-' : d -> negate (digitsVal d)
          '+' : d -> digitsVal d
          d -> digitsVal d
        _ -> 0
      digitsVal d = foldl (\a c -> a * 10 + fromEnum c - 48) (0 :: Int) (takeWhile isDigit d)
      mant = foldl (\a c -> a * 10 + fromIntegral (fromEnum c - 48)) 0 (ip ++ fp) :: Double
  in sign * mant * 10 ^^ (ex - length fp)

strOf :: Maybe Value -> Maybe String
strOf (Just (VStr s)) = Just s
strOf _ = Nothing

-- | An ISO-8601 timestamp as POSIX seconds, or Nothing when it does not parse.
parseTs :: String -> IO (Maybe POSIXTime)
parseTs raw = case parseIso raw of
  Nothing -> pure Nothing
  Just (day, tod, Just offMin) ->
    pure (Just (utcTimeToPOSIXSeconds (addUTCTime (negate (fromIntegral (offMin * 60))) (utcOf day tod))))
  Just (day, tod, Nothing) -> do
    tz <- getCurrentTimeZone
    pure (Just (utcTimeToPOSIXSeconds (localTimeToUTC tz (LocalTime day tod))))
  where
    utcOf day tod = UTCTime day (diffOf tod)

diffOf :: TimeOfDay -> DiffTime
diffOf (TimeOfDay h m sec) = secondsToDiffTime (fromIntegral (h * 3600 + m * 60)) + realToFrac sec

-- | YYYY-MM-DD, then 'T' or a space, HH:MM, optional :SS with fraction, optional Z or +-HH:MM.
-- The offset is in minutes; Nothing means no offset was written.
parseIso :: String -> Maybe (Day, TimeOfDay, Maybe Int)
parseIso s0 = do
  (y, r1) <- digitsN 4 s0
  r2 <- eat '-' r1
  (mo, r3) <- digitsN 2 r2
  r4 <- eat '-' r3
  (d, r5) <- digitsN 2 r4
  r6 <- case r5 of
    c : r | c == 'T' || c == 't' || c == ' ' -> Just r
    _ -> Nothing
  (hh, r7) <- digitsN 2 r6
  r8 <- eat ':' r7
  (mi, r9) <- digitsN 2 r8
  let (sec, r10) = case r9 of
        ':' : r -> case digitsN 2 r of
          Just (ss, r') -> case r' of
            '.' : r'' -> let (ds, rest) = span isDigit r''
                         in (fromIntegral ss + fracOf ds, rest)
            _ -> (fromIntegral ss, r')
          Nothing -> (0, r9)
        _ -> (0, r9)
  off <- case r10 of
    [] -> Just Nothing
    c : r | c == 'Z' || c == 'z' -> if null r then Just (Just 0) else Nothing
    c : r | c == '+' || c == '-' -> do
      (oh, q1) <- digitsN 2 r
      q2 <- case q1 of
        ':' : q -> Just q
        _ -> Nothing
      (om, rest) <- digitsN 2 q2
      if null rest then Just () else Nothing
      let mins = oh * 60 + om
      Just (Just (if c == '-' then negate mins else mins))
    _ -> Nothing
  if mo < 1 || mo > 12 || d < 1 || d > 31 || hh > 23 || mi > 59
    then Nothing
    else Just (fromGregorian (toInteger y) mo d, TimeOfDay hh mi (realToFrac sec), off)
  where
    eat c (x : r) | x == c = Just r
    eat _ _ = Nothing
    fracOf :: String -> Double
    fracOf ds = if null ds then 0 else read ("0." ++ ds)

digitsN :: Int -> String -> Maybe (Int, String)
digitsN n s =
  let (ds, rest) = splitAt n s
  in if length ds == n && all isDigit ds then Just (read ds, rest) else Nothing

-- | Assistant requests of one transcript in file order; a repeated message id is counted once.
transcriptSeq :: FilePath -> T.Text -> IO [Req]
transcriptSeq path txt = go [] (T.lines txt)
  where
    isSub = "/subagents/" `isInfixOf` path
    go _ [] = pure []
    go seen (l : ls) = case parseValue (T.unpack l) of
      Left _ -> go seen ls
      Right d
        | field "type" d /= Just (VStr "assistant") -> go seen ls
        | otherwise -> do
            let m = maybe (VObj []) id (field "message" d)
                mid = strOf (field "id" m)
            case (field "usage" m, mid) of
              (Just uv, Just k) | k `notElem` seen -> do
                let (b, r) = priceOf (strOf (field "model" m))
                    tsStr = maybe "" id (strOf (field "timestamp" d))
                t <- parseTs tsStr
                let req = Req
                      { rT = t
                      , rB = b / 1e6
                      , rR = r
                      , rSub = isSub
                      , rIn = numOf (field "input_tokens" uv)
                      , rCW = numOf (field "cache_creation_input_tokens" uv)
                      , rCR = numOf (field "cache_read_input_tokens" uv)
                      , rOut = numOf (field "output_tokens" uv)
                      }
                rest <- go (k : seen) ls
                pure (req : rest)
              _ -> go seen ls

-- | Every *.jsonl under a directory, recursively; dot-entries are skipped, as glob does.
jsonlFiles :: FilePath -> IO [FilePath]
jsonlFiles dir = do
  ok <- doesDirectoryExist dir
  if not ok
    then pure []
    else do
      names <- listDirectory dir
      fmap concat $ forM (filter (not . ("." `isPrefixOf`)) names) $ \n -> do
        let p = dir </> n
        isDir <- doesDirectoryExist p
        if isDir then jsonlFiles p else pure [p | takeExtension p == ".jsonl"]

-- | Thousands separators on a whole number's digits.
commas :: String -> String
commas = reverse . go . reverse
  where
    go (a : b : c : d : rest@(_ : _)) = a : b : c : ',' : go (d : rest)
    go xs = xs

-- | `{x:,.0f}`.
money :: Double -> String
money x =
  let r = round x :: Integer
  in (if r < 0 then "-" else "") ++ commas (show (abs r))

-- | `{x:+.1%}` for a ratio.
signedPct :: Double -> String
signedPct r =
  let p = r * 100
  in (if p < 0 then "-" else "+") ++ showFFloat (Just 1) (abs p) "" ++ "%"

-- | Per request under the TTL comparison: (observed cost, 5-minute cost, sub-agent, idle-gap).
ttlSeq :: [Req] -> [(Double, Double, Bool, Bool)]
ttlSeq = go Nothing
  where
    go _ [] = []
    go prev (q : qs) =
      let gap = case (prev, rT q) of
            (Just p, Just t) -> let dt = realToFrac (t - p) :: Double in dt > 300 && dt <= 3600
            _ -> False
          here = rB q * (rIn q + rCW q * w1h + rCR q * rR q + rOut q * outMult)
          alt
            | gap = rB q * (rIn q + (rCW q + rCR q) * w5m + rOut q * outMult)
            | otherwise = rB q * (rIn q + rCW q * w5m + rCR q * rR q + rOut q * outMult)
          prev' = maybe prev Just (rT q)
      in (here, alt, rSub q, gap) : go prev' qs

-- | Simulate one transcript under threshold T (Nothing = observed history): (total, compactions).
simulate :: Maybe Double -> [Req] -> (Double, Int)
simulate mt = go 0 0 0 0
  where
    go :: Double -> Double -> Double -> Int -> [Req] -> (Double, Int)
    go _ _ tot nc [] = (tot, nc)
    go drop0 prevCtx tot nc (q : qs) =
      let ctx = rIn q + rCW q + rCR q
          drop1 = if prevCtx /= 0 && ctx < 0.6 * prevCtx then 0 else drop0
          eff = max (ctx - drop1) 0
          compact = case mt of
            Just t | eff > t -> True
            _ -> False
          (drop2, nc', tot1)
            | compact =
                ( drop1 + eff - fTarget
                , nc + 1
                , tot + rB q * (eff * rR q + summaryOut * outMult + fTarget * w1h) )
            | otherwise = (drop1, nc, tot)
          crEff = max (rCR q - drop2) 0
          tot2 = tot1 + rB q * (rIn q + rCW q * w1h + crEff * rR q + rOut q * outMult)
      in go drop2 ctx tot2 nc' qs

main :: IO ()
main = do
  args <- getArgs
  days <- case args of
    [] -> pure (7 :: Double)
    a : _ -> case reads (fixLead a) of
      [(v, rest)] | all isSpace rest -> pure v
      _ -> warn ("claude-cost-whatif: could not convert string to float: " ++ show a) >> exitWith (ExitFailure 1)
  now <- getPOSIXTime
  home <- getHomeDirectory
  let cut = now - realToFrac (days * 86400)
  files <- jsonlFiles (home </> ".claude" </> "projects")
  seqs <- fmap concat $ forM files $ \f -> do
    mt <- try (getModificationTime f) :: IO (Either IOException UTCTime)
    case mt of
      Right m | utcTimeToPOSIXSeconds m >= cut -> do
        r <- try (B.readFile f) :: IO (Either IOException B.ByteString)
        case r of
          Right bs -> do
            sq <- transcriptSeq f (TE.decodeUtf8With lenientDecode bs)
            pure [sq | not (null sq)]
          Left _ -> pure []
      _ -> pure []
  let nReq = sum (map length seqs)
      costs = concatMap ttlSeq seqs
      obs = sum [h | (h, _, _, _) <- costs]
      five = sum [a | (_, a, _, _) <- costs]
      sub5 = sum [if s then a else h | (h, a, s, _) <- costs]
      gapRows = [(q, g) | sq <- seqs, ((_, _, _, g), q) <- zip (ttlSeq sq) sq]
      gapN = length [() | (_, True) <- gapRows]
      gapTok = sum [rCR q | (q, True) <- gapRows]
  when (obs == 0) $ warn "claude-cost-whatif: no observed cost to compare against" >> exitWith (ExitFailure 1)
  printf "A. TTL  transcripts %d, requests %s\n" (length seqs) (commas (show nReq))
  putStrLn $ "   observed 1h TTL everywhere: $" ++ money obs ++ "   5-minute everywhere: $" ++ money five
    ++ " (" ++ signedPct ((five - obs) / obs) ++ ")   main 1h + sub-agents 5m: $" ++ money sub5
    ++ " (" ++ signedPct ((sub5 - obs) / obs) ++ ")"
  putStrLn $ "   requests after a 5-60 min idle gap: " ++ commas (show gapN) ++ " ("
    ++ showFFloat (Just 1) (100 * fromIntegral gapN / fromIntegral nReq :: Double) "%), cached tokens they would re-write: "
    ++ showFFloat (Just 1) (gapTok / 1e6 :: Double) "M"
  putStrLn "B. compaction threshold (simulated on top of observed history)"
  forM_ [Nothing, Just 500000, Just 400000, Just 300000, Just 250000, Just 200000, Just 150000] $ \mt -> do
    let (total, nComp) = foldl (\(tot, nc) sq -> let (t', n') = simulate mt sq in (tot + t', nc + n')) (0, 0) seqs
        label = maybe "none (observed)" (\t -> show (round t `div` (1000 :: Integer)) ++ "k") mt
    putStrLn $ "   T=" ++ label ++ replicate (16 - length label) ' '
      ++ " total $" ++ money total ++ "  (" ++ signedPct ((total - obs) / obs) ++ ")  extra compactions " ++ commas (show nComp)
  where
    -- Python's float() accepts ".5"; Haskell's reads does not.
    fixLead s = case s of
      '.' : _ -> '0' : s
      '-' : '.' : r -> "-0." ++ r
      _ -> s
