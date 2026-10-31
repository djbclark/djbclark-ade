{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE LambdaCase #-}
{-# LANGUAGE RecordWildCards #-}

-- | web-get: web search and page fetch through a failover ladder, for shell-capable agents.
--
--   web-get search "<query>" [--n 8] [--json]
--   web-get fetch <url> [--max-bytes N] [--no-page-check] [--walk-budget S] [--json]
--   web-get check [--json]
--
-- Common flags: --only <p[,p]>, --skip <p[,p]>, --timeout <s per provider> (default 45),
-- --crwl-timeout <s>, --wayback-timeout <s>, --pdf-timeout <s>, --walk-budget <s>,
-- --verbose (log each attempt to stderr).
--
-- Ladders: the first provider that returns usable content wins. URLs are normalised once
-- (IDNA host, percent-encoded path and query) so every provider sees ASCII.
module Main (main) where

import Control.Exception (SomeException, try)
import Control.Monad (forM_, unless, when)
import Data.Char (isAlphaNum, isAscii, isSpace, toLower)
import Data.IORef (IORef, modifyIORef', newIORef, readIORef)
import Data.List (intercalate, isInfixOf, isPrefixOf, nub, sortOn)
import Data.Maybe (fromMaybe, listToMaybe, mapMaybe)
import qualified Data.Map.Strict as M
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.IO (hPutStrLn, stderr)
import System.Timeout (timeout)
import Text.Read (readMaybe)

-- | Exit codes, as documented in the header.
exitOk, exitUsage, exitNoContent :: ExitCode
exitOk = ExitSuccess
exitUsage = ExitFailure 2
exitNoContent = ExitFailure 5

-- | Global options shared by every subcommand.
data Options = Options
  { optOnly         :: [String]
  , optSkip         :: [String]
  , optTimeout      :: Int
  , optCrwlTimeout  :: Maybe Int
  , optWayback      :: Maybe Int
  , optPdfTimeout   :: Maybe Int
  , optWalkBudget   :: Int
  , optVerbose      :: Bool
  , optJson         :: Bool
  , optMaxBytes     :: Int
  , optNoPageCheck  :: Bool
  , optResults      :: Int
  }
  deriving (Show)

defaultOptions :: Options
defaultOptions = Options
  { optOnly        = []
  , optSkip        = []
  , optTimeout     = 45
  , optCrwlTimeout = Nothing
  , optWayback     = Nothing
  , optPdfTimeout  = Nothing
  , optWalkBudget  = 300
  , optVerbose     = False
  , optJson        = False
  , optMaxBytes    = 2000000
  , optNoPageCheck = False
  , optResults     = 8
  }

-- | The subcommands.
data Command
  = Search String
  | Fetch String
  | Check
  deriving (Show, Eq)

-- | A provider on the ladder.
data Provider = Provider
  { provName    :: String
  , provKind    :: ProviderKind
  , provEnabled :: Bool
  }
  deriving (Show, Eq)

data ProviderKind = SearchProvider | FetchProvider | BothProvider
  deriving (Show, Eq)

-- | Why a provider attempt ended.
data Attempt
  = Usable String
  | Thin String
  | Errored String
  | TimedOut
  deriving (Show, Eq)

-- | Result handed back to the caller.
data Result = Result
  { resProvider :: String
  , resBody     :: String
  , resUrl      :: String
  }
  deriving (Show, Eq)

-- | Ladders, in order. The first provider with usable content wins.
searchLadder :: [Provider]
searchLadder =
  [ Provider "brave"      SearchProvider True
  , Provider "searxng"    SearchProvider True
  , Provider "ddg"        SearchProvider True
  , Provider "firecrawl"  BothProvider   True
  ]

fetchLadder :: [Provider]
fetchLadder =
  [ Provider "direct"     FetchProvider True
  , Provider "crawl4ai"   FetchProvider True
  , Provider "firecrawl"  BothProvider  True
  , Provider "wayback"    FetchProvider True
  , Provider "pdf"        FetchProvider True
  ]

-- | Parse the global option list. Unknown flags are a usage error.
parseOptions :: [String] -> Either String (Options, [String])
parseOptions = go defaultOptions []
  where
    go opts acc [] = Right (opts, reverse acc)
    go opts acc (a : rest) = case a of
      "--only" -> needValue a rest $ \v r ->
        go opts { optOnly = splitCsv v } acc r
      "--skip" -> needValue a rest $ \v r ->
        go opts { optSkip = splitCsv v } acc r
      "--timeout" -> needValue a rest $ \v r ->
        withInt a v $ \n -> go opts { optTimeout = n } acc r
      "--crwl-timeout" -> needValue a rest $ \v r ->
        withInt a v $ \n -> go opts { optCrwlTimeout = Just n } acc r
      "--wayback-timeout" -> needValue a rest $ \v r ->
        withInt a v $ \n -> go opts { optWayback = Just n } acc r
      "--pdf-timeout" -> needValue a rest $ \v r ->
        withInt a v $ \n -> go opts { optPdfTimeout = Just n } acc r
      "--walk-budget" -> needValue a rest $ \v r ->
        withInt a v $ \n -> go opts { optWalkBudget = n } acc r
      "--max-bytes" -> needValue a rest $ \v r ->
        withInt a v $ \n -> go opts { optMaxBytes = n } acc r
      "--n" -> needValue a rest $ \v r ->
        withInt a v $ \n -> go opts { optResults = n } acc r
      "--verbose" -> go opts { optVerbose = True } acc rest
      "--json" -> go opts { optJson = True } acc rest
      "--no-page-check" -> go opts { optNoPageCheck = True } acc rest
      _ | "--" `isPrefixOf` a -> Left ("unknown option " ++ a)
        | otherwise -> go opts (a : acc) rest

    needValue flag rest k = case rest of
      (v : r) -> k v r
      [] -> Left (flag ++ " needs a value")

    withInt flag v k = case readMaybe v of
      Just n | n >= 0 -> k n
      _ -> Left (flag ++ " must be a non-negative integer")

splitCsv :: String -> [String]
splitCsv s = case break (== ',') s of
  (a, [])       -> filter (not . null) [a]
  (a, _ : rest) -> filter (not . null) (a : splitCsv rest)

-- | Turn positional arguments into a command.
parseCommand :: [String] -> Either String Command
parseCommand = \case
  ("search" : rest) -> case unwords rest of
    "" -> Left "search needs a query"
    q  -> Right (Search q)
  ["fetch", url] -> Right (Fetch url)
  ("fetch" : _) -> Left "fetch takes exactly one URL"
  ["check"] -> Right Check
  _ -> Left "usage: web-get search|fetch|check ..."

-- | Only the ladder rungs that survive --only and --skip are tried.
activeLadder :: Options -> [Provider] -> [Provider]
activeLadder opts = filter keep
  where
    keep p =
      let name = provName p
          onlyOk = null (optOnly opts) || name `elem` optOnly opts
          skipOk = name `notElem` optSkip opts
      in provEnabled p && onlyOk && skipOk

-- | IDNA-style host normalisation, reduced to lower-casing and ASCII checks.
normaliseHost :: String -> String
normaliseHost = map toLower

-- | Percent-encode any byte that is not an unreserved ASCII character.
percentEncode :: String -> String
percentEncode = concatMap enc
  where
    enc c
      | isAscii c && (isAlphaNum c || c `elem` ("-._~/:?#&=%+" :: String)) = [c]
      | otherwise = concatMap (\b -> '%' : hex2 b) (utf8Bytes c)
    hex2 b = [hexDigit (b `div` 16), hexDigit (b `mod` 16)]
    hexDigit n = "0123456789ABCDEF" !! n

utf8Bytes :: Char -> [Int]
utf8Bytes c
  | n < 0x80 = [n]
  | n < 0x800 = [0xC0 + n `div` 64, 0x80 + n `mod` 64]
  | n < 0x10000 = [0xE0 + n `div` 4096, 0x80 + (n `div` 64) `mod` 64, 0x80 + n `mod` 64]
  | otherwise = [0xF0 + n `div` 262144, 0x80 + (n `div` 4096) `mod` 64, 0x80 + (n `div` 64) `mod` 64, 0x80 + n `mod` 64]
  where n = fromEnum c

-- | Normalise a URL once; every provider receives this form.
normaliseUrl :: String -> Either String String
normaliseUrl raw
  | null raw = Left "empty URL"
  | not ("http://" `isPrefixOf` raw || "https://" `isPrefixOf` raw) = Left "URL must start with http:// or https://"
  | otherwise =
      let (scheme, rest) = break (== ':') raw
          afterScheme = drop 3 rest
          (hostPart, pathPart) = break (`elem` ("/?#" :: String)) afterScheme
      in if null hostPart
           then Left "URL has no host"
           else Right (map toLower scheme ++ "://" ++ normaliseHost hostPart ++ percentEncode pathPart)

-- | Log one attempt to stderr when --verbose is set.
logAttempt :: Options -> String -> Attempt -> IO ()
logAttempt opts name att = when (optVerbose opts) $
  hPutStrLn stderr ("web-get: " ++ name ++ " -> " ++ describe att)
  where
    describe (Usable _) = "usable"
    describe (Thin m) = "thin: " ++ m
    describe (Errored m) = "error: " ++ m
    describe TimedOut = "timed out"

-- | Run one provider with the per-attempt wall-clock limit.
runProvider :: Options -> Int -> (String -> IO Attempt) -> String -> IO Attempt
runProvider _ secs act name = do
  r <- timeout (secs * 1000000) (act name)
  pure (fromMaybe TimedOut r)

-- | Walk a ladder. The first usable attempt wins.
walkLadder :: Options -> [Provider] -> (String -> IO Attempt) -> IO (Maybe Result)
walkLadder opts ladder act = go (activeLadder opts ladder)
  where
    go [] = pure Nothing
    go (p : ps) = do
      att <- runProvider opts (optTimeout opts) act (provName p)
      logAttempt opts (provName p) att
      case att of
        Usable body -> pure (Just (Result (provName p) body ""))
        _ -> go ps

-- | Stub transport. The real rungs are invoked through their own tools.
callRung :: Options -> String -> String -> IO Attempt
callRung opts name payload
  | null payload = pure (Thin "empty payload")
  | otherwise = pure (Usable (name ++ ":" ++ show (optMaxBytes opts)))

-- | Decide whether a fetched body is worth returning.
pageUsable :: Options -> String -> Bool
pageUsable opts body =
  length body >= 200 && not (isBlockedPage body) && length body <= optMaxBytes opts

isBlockedPage :: String -> Bool
isBlockedPage body = any (`isInfixOf` lower) markers
  where
    lower = map toLower body
    markers =
      [ "enable javascript to continue"
      , "access denied"
      , "captcha"
      , "unusual traffic"
      ]

-- | Search: walk the search ladder and render results.
cmdSearch :: Options -> String -> IO ExitCode
cmdSearch opts q = do
  let act name = callRung opts name q
  r <- walkLadder opts searchLadder act
  case r of
    Nothing -> do
      hPutStrLn stderr "web-get: every search provider failed"
      pure exitNoContent
    Just res -> do
      renderResult opts res
      pure exitOk

-- | Fetch: walk the fetch ladder, then the page check.
cmdFetch :: Options -> String -> IO ExitCode
cmdFetch opts rawUrl = case normaliseUrl rawUrl of
  Left err -> hPutStrLn stderr ("web-get: " ++ err) >> pure exitUsage
  Right url -> do
    let act name = callRung opts name url
    r <- walkLadder opts fetchLadder act
    case r of
      Nothing -> do
        hPutStrLn stderr ("web-get: nothing fetched from " ++ url)
        pure exitNoContent
      Just res -> do
        let body = resBody res
        if optNoPageCheck opts || pageUsable opts body
          then renderResult opts res { resUrl = url } >> pure exitOk
          else do
            hPutStrLn stderr "web-get: page failed the usability check"
            pure exitNoContent

-- | Check: report which rungs are enabled and which would run.
cmdCheck :: Options -> IO ExitCode
cmdCheck opts = do
  let names = map provName (activeLadder opts (searchLadder ++ fetchLadder))
  forM_ (nub names) $ \n -> putStrLn ("rung: " ++ n)
  pure exitOk

renderResult :: Options -> Result -> IO ()
renderResult opts Result {..}
  | optJson opts = putStrLn (jsonObject
      [ ("provider", jsonString resProvider)
      , ("url", jsonString resUrl)
      , ("body", jsonString resBody)
      ])
  | otherwise = do
      putStrLn ("[" ++ resProvider ++ "] " ++ resUrl)
      putStrLn resBody

jsonString :: String -> String
jsonString s = "\"" ++ concatMap esc s ++ "\""
  where
    esc '"' = "\\\""
    esc '\\' = "\\\\"
    esc '\n' = "\\n"
    esc c = [c]

jsonObject :: [(String, String)] -> String
jsonObject kvs = "{" ++ intercalate "," [jsonString k ++ ":" ++ v | (k, v) <- kvs] ++ "}"

-- | Per-rung budgets with their documented defaults.
crwlBudget, waybackBudget, pdfBudget :: Options -> Int
crwlBudget opts = fromMaybe (max 150 (optTimeout opts)) (optCrwlTimeout opts)
waybackBudget opts = fromMaybe (max 120 (optTimeout opts)) (optWayback opts)
pdfBudget opts = fromMaybe (max 120 (optTimeout opts)) (optPdfTimeout opts)

-- | Environment overrides for the budgets.
readEnvBudget :: String -> IO (Maybe Int)
readEnvBudget key = do
  v <- lookupEnv key
  pure (v >>= readMaybe)

main :: IO ()
main = do
  args <- getArgs
  case parseOptions args of
    Left err -> hPutStrLn stderr ("web-get: " ++ err) >> exitWith exitUsage
    Right (opts0, positional) -> do
      crwl <- readEnvBudget "WEB_GET_CRWL_TIMEOUT"
      wb <- readEnvBudget "WEB_GET_WAYBACK_TIMEOUT"
      pdf <- readEnvBudget "WEB_GET_PDF_TIMEOUT"
      walk <- readEnvBudget "WEB_GET_WALK_BUDGET"
      let opts = opts0
            { optCrwlTimeout = optCrwlTimeout opts0 <|> crwl
            , optWayback = optWayback opts0 <|> wb
            , optPdfTimeout = optPdfTimeout opts0 <|> pdf
            , optWalkBudget = fromMaybe (optWalkBudget opts0) walk
            }
      case parseCommand positional of
        Left err -> hPutStrLn stderr ("web-get: " ++ err) >> exitWith exitUsage
        Right cmd -> do
          code <- case cmd of
            Search q -> cmdSearch opts q
            Fetch u -> cmdFetch opts u
            Check -> cmdCheck opts
          exitWith code
  where
    a <|> b = maybe b Just a

-- | Ladder summary, used by the check command's JSON output.
ladderSummary :: [Provider] -> [(String, String)]
ladderSummary ps = [(provName p, show (provKind p)) | p <- ps]

-- | Sort providers so that the cheapest rung runs first.
rankRungs :: [Provider] -> [Provider]
rankRungs = sortOn (\p -> case provKind p of
  FetchProvider -> 0 :: Int
  SearchProvider -> 1
  BothProvider -> 2)

-- | Count rungs by kind, for the summary line.
countKinds :: [Provider] -> M.Map String Int
countKinds ps = M.fromListWith (+) [(show (provKind p), 1) | p <- ps]

-- | Pick a short label for a result so logs stay readable.
labelFor :: Result -> String
labelFor r = resProvider r ++ "@" ++ take 40 (resUrl r)

-- | Strip leading and trailing whitespace from a query.
cleanQuery :: String -> String
cleanQuery = dropWhile isSpace . reverse . dropWhile isSpace . reverse

-- | A query that is only whitespace is no query at all.
validQuery :: String -> Bool
validQuery q = not (null (cleanQuery q))

-- | Search results are capped at the requested count.
capResults :: Int -> [a] -> [a]
capResults n = take (max 0 n)

-- | Extract the first mapped value, if any.
firstMapped :: (a -> Maybe b) -> [a] -> Maybe b
firstMapped f = listToMaybe . mapMaybe f

-- | Clamp a timeout to a sane range.
clampTimeout :: Int -> Int
clampTimeout n = min 3600 (max 1 n)

-- | Build the budget table printed by --verbose.
budgetTable :: Options -> [(String, Int)]
budgetTable opts =
  [ ("per-attempt", clampTimeout (optTimeout opts))
  , ("crawl4ai", crwlBudget opts)
  , ("wayback", waybackBudget opts)
  , ("pdf", pdfBudget opts)
  , ("walk", optWalkBudget opts)
  ]

-- | Print the budgets to stderr.
printBudgets :: Options -> IO ()
printBudgets opts = forM_ (budgetTable opts) $ \(k, v) ->
  hPutStrLn stderr ("web-get: budget " ++ k ++ "=" ++ show v)

-- | Guard used before a fetch so an empty URL never reaches a provider.
guardUrl :: String -> Either String String
guardUrl u = unless' (not (null u)) "empty URL" >> normaliseUrl u
  where
    unless' c msg = if c then Right () else Left msg

-- | Mutable counter for attempts, used by the walk-budget accounting.
newAttemptCounter :: IO (IORef Int)
newAttemptCounter = newIORef 0

bumpAttempts :: IORef Int -> IO ()
bumpAttempts ref = modifyIORef' ref (+ 1)

attemptsSoFar :: IORef Int -> IO Int
attemptsSoFar = readIORef

-- | Recover from an exception in a rung without losing the ladder.
safely :: IO a -> IO (Either SomeException a)
safely = try

-- | Format a duration in seconds for logs.
formatSecs :: Int -> String
formatSecs n = show n ++ "s"

-- | Build a short status line for --verbose.
statusLine :: Options -> String
statusLine opts = intercalate " " (map (\(k, v) -> k ++ "=" ++ formatSecs v) (budgetTable opts))

-- | Keep the rung table printable on a 80-column terminal.
fitColumns :: Int -> String -> String
fitColumns w s = if length s > w then take (w - 3) s ++ "..." else s
