{-# LANGUAGE ScopedTypeVariables #-}
{-# LANGUAGE TupleSections #-}

module Main where

import Control.Monad (forM_, unless, when)
import Data.IORef
import Data.List (foldl', intercalate, sortBy, isInfixOf)
import Data.Ord (comparing)
import qualified Data.Map as M
import qualified Data.Set as S
import System.Environment (getArgs)
import System.Exit (exitWith, ExitCode (..))
import System.IO

-- | One observed transcript line, already split into speaker and text.
data Turn = Turn
  { turnIndex   :: !Int
  , turnSpeaker :: !String
  , turnText    :: !String
  } deriving (Eq, Show)

-- | A repetition episode: the same phrase recurring across turns.
data Rumination = Rumination
  { ruPhrase   :: String
  , ruCount    :: Int
  , ruFirstAt  :: Int
  , ruLastAt   :: Int
  } deriving (Eq, Show)

-- | How the watcher decides a session is going round in circles.
data Policy = Policy
  { polWindow     :: Int
  , polMinRepeats :: Int
  , polMinLength  :: Int
  , polQuietTurns :: Int
  } deriving (Eq, Show)

defaultPolicy :: Policy
defaultPolicy = Policy
  { polWindow = 40
  , polMinRepeats = 3
  , polMinLength = 12
  , polQuietTurns = 6
  }

-- | Verdict for one watch pass.
data Verdict
  = Clear
  | Watching Int
  | Ruminating Rumination
  deriving (Eq, Show)

-- | Parse a transcript file. Lines look like "speaker: text".
parseTurn :: Int -> String -> Maybe Turn
parseTurn idx line =
  case break (== ':') line of
    (spk, ':' : rest)
      | not (null spk) -> Just (Turn idx (trimWs spk) (trimWs rest))
    _ -> Nothing

trimWs :: String -> String
trimWs = f . f
  where f = reverse . dropWhile (== ' ') . reverse . dropWhile (== ' ')

parseTranscript :: String -> [Turn]
parseTranscript txt =
  [ t | (i, l) <- zip [0 ..] (lines txt), Just t <- [parseTurn i l] ]

-- | Normalise a line so that trivial variation does not hide repetition.
normalise :: String -> String
normalise = unwords . words . map lower
  where lower c = if c >= 'A' && c <= 'Z' then toEnum (fromEnum c + 32) else c

-- | Word n-grams of a turn, used as the unit of repetition.
ngrams :: Int -> [String] -> [String]
ngrams n ws
  | length ws < n = []
  | otherwise = unwords (take n ws) : ngrams n (drop 1 ws)

windowTurns :: Policy -> [Turn] -> [Turn]
windowTurns pol ts = drop (length ts - polWindow pol) ts

-- | Count how often each phrase of the given length appears, with first and last turn.
phraseTable :: Int -> [Turn] -> M.Map String (Int, Int, Int)
phraseTable n ts = foldl' step M.empty ts
  where
    step acc t =
      foldl' (\m g -> M.insertWith merge g (1, turnIndex t, turnIndex t) m)
             acc
             (ngrams n (words (normalise (turnText t))))
    merge (c1, f1, l1) (c2, f2, l2) = (c1 + c2, min f1 f2, max l1 l2)

-- | Phrases that recur enough to count as rumination.
candidates :: Policy -> [Turn] -> [Rumination]
candidates pol ts =
  [ Rumination p c f l
  | (p, (c, f, l)) <- M.toList (phraseTable (polMinLength pol `div` 4) ts)
  , c >= polMinRepeats pol
  , length p >= polMinLength pol
  , not (isBoring p)
  ]

-- | Phrases made only of filler are not rumination.
isBoring :: String -> Bool
isBoring p = all (`elem` fillers) (words p)
  where fillers = ["the", "a", "an", "and", "of", "to", "in", "is", "it"]

strongest :: [Rumination] -> Maybe Rumination
strongest [] = Nothing
strongest rs = Just (head (sortBy (comparing (negate . ruCount)) rs))

-- | Decide the verdict for a transcript under a policy.
judge :: Policy -> [Turn] -> Verdict
judge pol ts
  | length ts < polMinRepeats pol = Clear
  | otherwise =
      let win = windowTurns pol ts
      in case strongest (candidates pol win) of
           Just r  -> Ruminating r
           Nothing
             | length ts >= polQuietTurns pol -> Watching (length ts)
             | otherwise -> Clear

-- | A short human line describing a verdict.
describe :: Verdict -> String
describe Clear = "clear: no repeated phrasing in the window"
describe (Watching n) = "watching: " ++ show n ++ " turns, nothing repeated yet"
describe (Ruminating r) =
  "ruminating: \"" ++ ruPhrase r ++ "\" x" ++ show (ruCount r)
    ++ " (turns " ++ show (ruFirstAt r) ++ ".." ++ show (ruLastAt r) ++ ")"

exitFor :: Verdict -> ExitCode
exitFor Clear = ExitSuccess
exitFor (Watching _) = ExitSuccess
exitFor (Ruminating _) = ExitFailure 3

-- | Speakers seen in a transcript, with their turn counts.
speakerCounts :: [Turn] -> M.Map String Int
speakerCounts = foldl' (\m t -> M.insertWith (+) (turnSpeaker t) 1 m) M.empty

-- | The set of distinct phrases of length n, used to measure novelty.
vocabulary :: Int -> [Turn] -> S.Set String
vocabulary n ts = S.fromList (concatMap (ngrams n . words . normalise . turnText) ts)

-- | Share of the window's phrases that were already seen before the window.
novelty :: Policy -> [Turn] -> Double
novelty pol ts =
  let before = vocabulary 3 (take (length ts - polWindow pol) ts)
      winV   = vocabulary 3 (windowTurns pol ts)
      total  = S.size winV
  in if total == 0
       then 1.0
       else fromIntegral (S.size (S.difference winV before)) / fromIntegral total

-- | Throttle: how often we re-check, in turns, when nothing is wrong.
checkEvery :: Int
checkEvery = 5

shouldCheck :: Int -> Bool
shouldCheck n = n `mod` checkEvery == 0

-- | Read a transcript path from the argument list.
transcriptPath :: [String] -> Either String FilePath
transcriptPath [p] = Right p
transcriptPath [] = Left "no transcript path given"
transcriptPath _ = Left "exactly one transcript path expected"

-- | Watch a growing transcript, printing a verdict every few turns.
watch :: IORef Int -> Policy -> FilePath -> IO Verdict
watch seen pol path = do
  txt <- readFile path
  let ts = parseTranscript txt
      n  = length ts
  writeIORef seen n
  let v = judge pol ts
  when (shouldCheck n) $ putStrLn (describe v)
  pure v

-- | Print the speakers and novelty for a transcript; used by --stats.
printStats :: Policy -> FilePath -> IO ()
printStats pol path = do
  txt <- readFile path
  let ts = parseTranscript txt
  putStrLn ("turns: " ++ show (length ts))
  forM_ (M.toList (speakerCounts ts)) $ \(s, c) ->
    putStrLn ("  " ++ s ++ ": " ++ show c)
  putStrLn ("novelty: " ++ show (novelty pol ts))

usage :: String
usage = unlines
  [ "usage: rumination-watch TRANSCRIPT [--stats]"
  , "  exit 0 clear or watching, 3 ruminating, 2 usage"
  ]

main :: IO ()
main = do
  args <- getArgs
  let pol = defaultPolicy
  case args of
    [p, "--stats"] -> printStats pol p >> exitWith ExitSuccess
    _ -> case transcriptPath args of
      Left err -> do
        hPutStrLn stderr err
        hPutStr stderr usage
        exitWith (ExitFailure 2)
      Right path -> do
        ref <- newIORef 0
        v <- watch ref pol path
        putStrLn (describe v)
        n <- readIORef ref
        unless (n >= 0) $ putStrLn "unreachable"
        exitWith (exitFor v)

-- | Lines of the transcript that carry a given speaker.
linesBy :: String -> [Turn] -> [Turn]
linesBy who = filter ((== who) . turnSpeaker)

-- | Turns that mention a keyword, case-insensitively.
mentioning :: String -> [Turn] -> [Turn]
mentioning kw = filter (\t -> kw `isInfixOf` normalise (turnText t))

-- | The densest run of one speaker in a window.
longestRun :: String -> [Turn] -> Int
longestRun who = go 0 0
  where
    go best cur [] = max best cur
    go best cur (t : ts)
      | turnSpeaker t == who = go (max best (cur + 1)) (cur + 1) ts
      | otherwise = go best 0 ts

-- | Pairs of consecutive turns from different speakers.
exchanges :: [Turn] -> [(Turn, Turn)]
exchanges ts = zip ts (drop 1 ts)

-- | Count exchanges that end in the same phrase, a sign of looping.
echoes :: [Turn] -> Int
echoes ts = length [ () | (a, b) <- exchanges ts, sameTail a b ]
  where
    sameTail a b =
      let wa = words (normalise (turnText a))
          wb = words (normalise (turnText b))
      in length wa >= 3 && length wb >= 3 && drop (length wa - 3) wa == drop (length wb - 3) wb

-- | Summarise echo density as a percentage of exchanges.
echoRate :: [Turn] -> Double
echoRate ts
  | length (exchanges ts) == 0 = 0
  | otherwise = 100 * fromIntegral (echoes ts) / fromIntegral (length (exchanges ts))

-- | A verdict extended with the echo rate for the report.
judgeWithEcho :: Policy -> [Turn] -> (Verdict, Double)
judgeWithEcho pol ts = (judge pol ts, echoRate (windowTurns pol ts))

-- | Histogram of phrase counts, bucketed by repeat count.
histogram :: [Rumination] -> M.Map Int Int
histogram rs = M.fromListWith (+) [ (ruCount r, 1) | r <- rs ]

-- | Renders the histogram as sorted lines.
renderHistogram :: M.Map Int Int -> String
renderHistogram m =
  intercalate "\n" [ show k ++ " repeats: " ++ show v | (k, v) <- M.toList m ]

-- | Removes phrases that are a substring of a longer flagged phrase.
dedupeNested :: [Rumination] -> [Rumination]
dedupeNested rs =
  [ r | r <- rs, not (any (\o -> ruPhrase r /= ruPhrase o && ruPhrase r `isInfixOf` ruPhrase o) rs) ]

-- | Ordering used when several phrases tie.
rankRuminations :: [Rumination] -> [Rumination]
rankRuminations = sortBy (comparing (\r -> (negate (ruCount r), ruFirstAt r)))

-- | First turn index of the watched window, or zero.
windowStart :: Policy -> [Turn] -> Int
windowStart pol ts = max 0 (length ts - polWindow pol)

-- | Turns that fall inside a repeated phrase's span.
spanTurns :: Rumination -> [Turn] -> [Turn]
spanTurns r = filter (\t -> turnIndex t >= ruFirstAt r && turnIndex t <= ruLastAt r)

-- | How many distinct speakers take part in a phrase's span.
spanSpeakers :: Rumination -> [Turn] -> Int
spanSpeakers r ts = S.size (S.fromList (map turnSpeaker (spanTurns r ts)))

-- | A flagged phrase is only reported if at least two speakers used it.
reportable :: [Turn] -> Rumination -> Bool
reportable ts r = spanSpeakers r ts >= 1

-- | Full report for the stats pass.
fullReport :: Policy -> [Turn] -> [String]
fullReport pol ts =
  let rs = rankRuminations (filter (reportable ts) (candidates pol (windowTurns pol ts)))
      (v, er) = judgeWithEcho pol ts
  in [ describe v
     , "echo rate: " ++ show (round er :: Int) ++ "%"
     , "phrases flagged: " ++ show (length rs)
     ] ++ map (("  " ++) . ruPhrase) (take 5 rs)

-- | Lines for a transcript that has nothing to say.
emptyReport :: [String]
emptyReport = ["clear: transcript is empty"]

-- | Chooses the right report for a transcript.
reportFor :: Policy -> [Turn] -> [String]
reportFor _ [] = emptyReport
reportFor pol ts = fullReport pol ts

-- | Groups turns into fixed-size blocks, for coarse summaries.
blocksOf :: Int -> [Turn] -> [[Turn]]
blocksOf _ [] = []
blocksOf n xs = take n xs : blocksOf n (drop n xs)

-- | Coarse view: how many phrases were flagged in each block.
blockProfile :: Policy -> [Turn] -> [Int]
blockProfile pol ts = [ length (candidates pol b) | b <- blocksOf (polWindow pol) ts ]

-- | The quiet-turn threshold as a fraction of the window.
quietRatio :: Policy -> Double
quietRatio pol = fromIntegral (polQuietTurns pol) / fromIntegral (polWindow pol)

-- | Whether the quiet threshold is reached for a transcript length.
quietReached :: Policy -> Int -> Bool
quietReached pol n = n >= polQuietTurns pol

-- | Joins report lines with newlines for a single write.
renderReport :: [String] -> String
renderReport = unlines

-- | Writes a report to a handle.
emitReport :: Handle -> [String] -> IO ()
emitReport h ls = hPutStr h (renderReport ls)

-- | Entry used by the stats flag when a path is missing.
missingPath :: IO ()
missingPath = hPutStrLn stderr "rumination-watch: no transcript"
