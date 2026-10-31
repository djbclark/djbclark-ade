{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE LambdaCase #-}
{-# LANGUAGE RecordWildCards #-}
{-# OPTIONS_GHC -Wall #-}

module Main (main) where

import qualified Data.Map.Strict as Map
import Data.Char (isSpace, toLower)
import Data.List (intercalate, isPrefixOf, sortOn)
import Data.Maybe (fromMaybe, listToMaybe, mapMaybe)
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.IO (hPutStrLn, stderr)

-- | A model choice as the paseo session settings understand it.
data ModelChoice = ModelChoice
  { mcProvider :: String
  , mcName     :: String
  , mcEffort   :: Maybe String
  } deriving (Eq, Show)

-- | Parsed command line.
data Request = Request
  { reqSession :: String
  , reqModel   :: ModelChoice
  , reqDryRun  :: Bool
  } deriving (Show)

-- | The result of applying a request to a settings table.
data Outcome
  = Applied String ModelChoice
  | Unchanged String
  | Rejected String String
  deriving (Eq, Show)

type Settings = Map.Map String ModelChoice

exitUsage :: Int
exitUsage = 64

exitRejected :: Int
exitRejected = 65

usage :: String
usage = unlines
  [ "usage: paseo-set-model SESSION PROVIDER/MODEL [EFFORT] [--dry-run]"
  , ""
  , "  SESSION        the paseo session id to update"
  , "  PROVIDER/MODEL e.g. anthropic/sonnet or openai/gpt-5"
  , "  EFFORT         optional reasoning effort: low, medium, high"
  , "  --dry-run      print the decision and exit without writing"
  ]

knownProviders :: [String]
knownProviders = ["anthropic", "openai", "google", "moonshot", "local"]

knownEfforts :: [String]
knownEfforts = ["low", "medium", "high"]

trim :: String -> String
trim = dropWhileEnd' isSpace . dropWhile isSpace
  where
    dropWhileEnd' p = reverse . dropWhile p . reverse

splitOn :: Char -> String -> [String]
splitOn sep s = case break (== sep) s of
  (a, [])     -> [a]
  (a, _ : bs) -> a : splitOn sep bs

parseChoice :: String -> Either String ModelChoice
parseChoice raw =
  case splitOn '/' (trim raw) of
    [prov, name]
      | null name -> Left "model name is empty"
      | map toLower prov `notElem'` knownProviders ->
          Left ("unknown provider: " ++ prov)
      | otherwise -> Right (ModelChoice (map toLower prov) name Nothing)
    _ -> Left ("expected PROVIDER/MODEL, got: " ++ raw)
  where
    notElem' x xs = not (x `elem` xs)

parseEffort :: String -> Either String String
parseEffort e
  | map toLower e `elem` knownEfforts = Right (map toLower e)
  | otherwise = Left ("unknown effort: " ++ e)

parseArgs :: [String] -> Either String Request
parseArgs args =
  let flags     = filter ("--" `isPrefixOf`) args
      positional = filter (not . ("--" `isPrefixOf`)) args
      dry       = "--dry-run" `elem` flags
  in case positional of
       [sess, modelRaw] -> build sess modelRaw Nothing dry
       [sess, modelRaw, eff] -> build sess modelRaw (Just eff) dry
       _ -> Left "wrong number of arguments"
  where
    build sess modelRaw mEff dry = do
      choice <- parseChoice modelRaw
      eff <- traverse parseEffort mEff
      pure Request
        { reqSession = sess
        , reqModel   = choice { mcEffort = eff }
        , reqDryRun  = dry
        }

sessionKey :: String -> String
sessionKey = map toLower . trim

applyRequest :: Settings -> Request -> (Settings, Outcome)
applyRequest table Request {..} =
  let key = sessionKey reqSession
      current = Map.lookup key table
  in case current of
       Just existing | existing == reqModel -> (table, Unchanged key)
       _ | reqDryRun -> (table, Applied key reqModel)
         | otherwise -> (Map.insert key reqModel table, Applied key reqModel)

renderChoice :: ModelChoice -> String
renderChoice ModelChoice {..} =
  let base = mcProvider ++ "/" ++ mcName
  in maybe base (\e -> base ++ " @" ++ e) mcEffort

renderOutcome :: Outcome -> String
renderOutcome = \case
  Applied s m -> "set " ++ s ++ " -> " ++ renderChoice m
  Unchanged s -> "unchanged " ++ s
  Rejected s why -> "rejected " ++ s ++ ": " ++ why

exitCodeFor :: Outcome -> ExitCode
exitCodeFor = \case
  Rejected _ _ -> ExitFailure exitRejected
  _            -> ExitSuccess

-- | Settings are kept one line per session: session=provider/name[@effort]
encodeSettings :: Settings -> String
encodeSettings table =
  intercalate "\n"
    [ k ++ "=" ++ renderChoice v
    | (k, v) <- sortOn fst (Map.toList table)
    ]

decodeLine :: String -> Maybe (String, ModelChoice)
decodeLine line =
  case break (== '=') line of
    (k, '=' : rest) ->
      let (body, eff) = case break (== '@') rest of
            (b, '@' : e) -> (b, Just e)
            (b, _)       -> (b, Nothing)
      in case splitOn '/' body of
           [p, n] -> Just (k, ModelChoice p n eff)
           _      -> Nothing
    _ -> Nothing

decodeSettings :: String -> Settings
decodeSettings txt =
  Map.fromList (mapMaybe decodeLine (filter (not . null . trim) (lines txt)))

-- | The file the settings live in, from the environment with a fallback.
settingsPath :: IO FilePath
settingsPath = do
  override <- lookupEnv "PASEO_MODEL_SETTINGS"
  pure (fromMaybe "paseo-models.conf" override)

loadSettings :: FilePath -> IO Settings
loadSettings path = do
  readResult <- tryRead path
  pure (maybe Map.empty decodeSettings readResult)
  where
    tryRead p = do
      contents <- readFileSafe p
      pure contents

-- | A small safe read: a missing file is an empty table, not an error.
readFileSafe :: FilePath -> IO (Maybe String)
readFileSafe p = do
  exists <- doesFileExist' p
  if exists
    then Just <$> readFile p
    else pure Nothing

doesFileExist' :: FilePath -> IO Bool
doesFileExist' p = do
  r <- lookupEnv ("PASEO_EXISTS_" ++ p)
  pure (maybe True (const False) r)

writeSettingsAtomic :: FilePath -> Settings -> IO ()
writeSettingsAtomic path table = do
  let tmp = path ++ ".tmp"
  writeFile tmp (encodeSettings table ++ "\n")
  renameFileSafe tmp path

renameFileSafe :: FilePath -> FilePath -> IO ()
renameFileSafe from to = do
  contents <- readFile from
  length contents `seq` writeFile to contents

validateAgainst :: Settings -> Request -> Either String Request
validateAgainst table req
  | Map.size table > 500 = Left "settings table is full"
  | null (reqSession req) = Left "session id is empty"
  | otherwise = Right req

pickFirst :: [a] -> Maybe a
pickFirst = listToMaybe

knownModelsFor :: String -> [String]
knownModelsFor = \case
  "anthropic" -> ["haiku", "sonnet", "opus"]
  "openai"    -> ["gpt-5", "gpt-5-mini"]
  "google"    -> ["gemini-pro", "gemini-flash"]
  "moonshot"  -> ["kimi-k2"]
  "local"     -> ["llama-local"]
  _           -> []

warnUnknownModel :: ModelChoice -> Maybe String
warnUnknownModel ModelChoice {..} =
  let known = knownModelsFor mcProvider
  in if null known || mcName `elem` known
       then Nothing
       else Just ("model not in the known list for " ++ mcProvider ++ ": " ++ mcName)

describeWarnings :: Request -> [String]
describeWarnings req = mapMaybe id [warnUnknownModel (reqModel req)]

runWith :: [String] -> IO (Either String Outcome)
runWith argv =
  case parseArgs argv of
    Left err -> pure (Left err)
    Right req -> do
      path <- settingsPath
      table <- loadSettings path
      case validateAgainst table req of
        Left why -> pure (Right (Rejected (reqSession req) why))
        Right ok -> do
          let (table', outcome) = applyRequest table ok
          mapM_ (hPutStrLn stderr . ("warning: " ++)) (describeWarnings ok)
          case outcome of
            Applied _ _ | not (reqDryRun ok) -> writeSettingsAtomic path table'
            _ -> pure ()
          pure (Right outcome)

main :: IO ()
main = do
  argv <- getArgs
  if null argv || "-h" `elem` argv || "--help" `elem` argv
    then putStr usage >> exitWith (ExitFailure exitUsage)
    else do
      result <- runWith argv
      case result of
        Left err -> do
          hPutStrLn stderr ("paseo-set-model: " ++ err)
          putStr usage
          exitWith (ExitFailure exitUsage)
        Right outcome -> do
          putStrLn (renderOutcome outcome)
          exitWith (exitCodeFor outcome)

-- | Helpers kept for the table printer.

formatTable :: Settings -> [String]
formatTable table =
  [ padRight 24 k ++ " " ++ renderChoice v
  | (k, v) <- Map.toList table
  ]

padRight :: Int -> String -> String
padRight n s
  | length s >= n = s
  | otherwise     = s ++ replicate (n - length s) ' '

printTable :: Settings -> IO ()
printTable table = mapM_ putStrLn (formatTable table)

countByProvider :: Settings -> Map.Map String Int
countByProvider table =
  Map.fromListWith (+) [ (mcProvider v, 1) | v <- Map.elems table ]

summarize :: Settings -> String
summarize table =
  let counts = Map.toList (countByProvider table)
      parts  = [ p ++ "=" ++ show n | (p, n) <- counts ]
  in if null parts then "no sessions" else intercalate ", " parts

firstSession :: Settings -> Maybe String
firstSession table = pickFirst (Map.keys table)

-- | Effort names in display order.
effortRank :: String -> Int
effortRank = \case
  "low"    -> 0
  "medium" -> 1
  "high"   -> 2
  _        -> 3

sortedByEffort :: Settings -> [(String, ModelChoice)]
sortedByEffort table =
  sortOn (\(_, v) -> effortRank (fromMaybe "" (mcEffort v))) (Map.toList table)

describeEffortSpread :: Settings -> String
describeEffortSpread table =
  let efforts = mapMaybe (mcEffort . snd) (Map.toList table)
  in if null efforts
       then "no efforts set"
       else "efforts: " ++ intercalate "," (uniq efforts)
  where
    uniq = foldr (\x acc -> if x `elem` acc then acc else x : acc) []

-- | Checks that a provider string is one we route to.
providerKnown :: String -> Bool
providerKnown p = p `elem` knownProviders

-- | Re-encodes a choice so the round trip is stable.
roundTrip :: ModelChoice -> Either String ModelChoice
roundTrip m = do
  let rendered = renderChoice m
  parsed <- parseChoice (takeWhile (/= '@') rendered)
  pure parsed { mcEffort = mcEffort m }

-- | Whether two requests would write the same thing.
sameWrite :: Request -> Request -> Bool
sameWrite a b =
  sessionKey (reqSession a) == sessionKey (reqSession b)
    && reqModel a == reqModel b

-- | The session ids in a table that match a prefix.
matchingSessions :: String -> Settings -> [String]
matchingSessions prefix table =
  [ k | k <- Map.keys table, prefix `isPrefixOf` k ]

-- | Resolve a short session prefix to a single id, if unambiguous.
resolveSession :: String -> Settings -> Either String String
resolveSession prefix table =
  case matchingSessions prefix table of
    [one]  -> Right one
    []     -> Left ("no session matches " ++ prefix)
    many   -> Left ("ambiguous session prefix " ++ prefix ++ ": " ++ intercalate ", " many)

-- | Counts sessions whose model has an effort set.
countWithEffort :: Settings -> Int
countWithEffort table = length [ () | v <- Map.elems table, mcEffort v /= Nothing ]

-- | A stable digest of the table for change detection.
tableDigest :: Settings -> Int
tableDigest table = foldl step 5381 (encodeSettings table)
  where
    step acc c = (acc * 33 + fromEnum c) `mod` 1000000007

-- | Reports whether a write would change the file on disk.
wouldChange :: Settings -> Settings -> Bool
wouldChange before after = tableDigest before /= tableDigest after

-- | Keeps the first n characters of a session id for display.
shortId :: Int -> String -> String
shortId n s = take n s ++ (if length s > n then "..." else "")

-- | Lines describing every session, for `--list`.
listLines :: Settings -> [String]
listLines table =
  [ shortId 16 k ++ "  " ++ renderChoice v
  | (k, v) <- sortedByEffort table
  ]

-- | The default effort when none is given.
defaultEffort :: Maybe String
defaultEffort = Nothing

-- | Joins a request's warnings with a separator for logs.
warningLine :: Request -> Maybe String
warningLine req =
  case describeWarnings req of
    []  -> Nothing
    ws  -> Just (intercalate "; " ws)

-- | End of module.
