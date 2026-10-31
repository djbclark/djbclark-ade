-- | context-watch: how full is each running Claude Code agent's context, against the REAL compaction ceiling.
--
--     context-watch [--json] [--min-pct N] [--source auto|paseo|recent] [--recent-minutes M]
--
-- One line per agent, fullest first:
--
--     <agent id8> <title> 214k/267k (80%) wall in 53k
--
-- `wall in` is the headroom left before Claude Code compacts by itself; past it the line says
-- `wall passed by 5k`. An agent whose size cannot be read prints `<id8> <title> ?` and one whose
-- newest record is a compaction (no request since) prints `compacted`. Read-only; exit 0 always
-- (2 only for bad usage). Nothing is written.
--
-- Port of bin/context-watch (HEAD). The Python version imports claude/hooks/context_size_nudge.py
-- and skills/session-finder/fleet.py; this port carries what those supply here: the usage scan
-- (newest non-sidechain assistant usage block, input + cache_read + cache_creation, read from a
-- 2 MB tail), the compaction boundary, the ceiling rules (window minus the 33k buffer, the settings
-- chain, the 200k Haiku and [1m] model windows), the paseo and recent sources, and the text and
-- --json output. The hook's incremental boundary search over appended bytes is not ported: the
-- newest-first line scan here gives the same answer for ordinary transcripts.
module Main (main) where

import Control.Exception (IOException, try)
import Control.Monad (filterM, forM)
import qualified Data.ByteString as B
import Data.Char (isControl, isDigit, isSpace, toLower)
import Data.List (isInfixOf, isPrefixOf, isSuffixOf, sortBy, tails)
import Data.Maybe (fromMaybe, isNothing)
import Data.Ord (comparing)
import qualified Data.Text as T
import qualified Data.Text.Encoding as TE
import qualified Data.Text.Encoding.Error as TEE
import Data.Time.Clock (UTCTime, getCurrentTime, diffUTCTime)
import System.Directory
  ( doesDirectoryExist
  , doesFileExist
  , getModificationTime
  , listDirectory
  )
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (dropExtension, takeDirectory, takeFileName, (</>))
import System.IO (IOMode (ReadMode), SeekMode (AbsoluteSeek), hFileSize, hPutStrLn, hSeek, stderr, withBinaryFile)
import System.Process (readProcessWithExitCode)
import Text.Read (readMaybe)
import Ade.Json

autoCompactBuffer, defaultModelWindow, longModelWindow, maxWindow, tailBytes :: Integer
autoCompactBuffer = 33000
defaultModelWindow = 200000
longModelWindow = 1000000
maxWindow = 10000000
tailBytes = 2000000

-- | One agent row. rStatus is "" until measured.
data Row = Row
  { rId :: String
  , rTitle :: String
  , rCwd :: Maybe String
  , rSession :: Maybe String
  , rSource :: String
  , rStatus :: String
  , rTranscript :: Maybe FilePath
  , rTokens :: Maybe Integer
  , rPct :: Maybe Double
  , rHeadroom :: Maybe Integer
  , rCeiling :: Maybe Integer
  }

data Source = Auto | PaseoOnly | RecentOnly deriving (Eq)

data Opts = Opts
  { oJson :: Bool
  , oMinPct :: Maybe Double
  , oSource :: Source
  , oRecent :: Double
  }

usageLine :: String
usageLine = "usage: context-watch [-h] [--json] [--min-pct MIN_PCT] [--source {auto,paseo,recent}] [--recent-minutes RECENT_MINUTES]"

argError :: String -> IO a
argError msg = do
  hPutStrLn stderr usageLine
  hPutStrLn stderr ("context-watch: error: " ++ msg)
  exitWith (ExitFailure 2)

-- | argparse's nonneg(): a finite, not negative number.
nonneg :: String -> String -> IO Double
nonneg opt t = case readMaybe (fixLead t) :: Maybe Double of
  Just v | not (isNaN v), not (isInfinite v), v >= 0 -> pure v
  _ -> argError ("argument " ++ opt ++ ": must be finite and not negative: " ++ show t)
  where
    fixLead x = if take 1 x == "." then '0' : x else x

parseArgs :: [String] -> IO Opts
parseArgs = go (Opts False Nothing Auto 30)
  where
    go o [] = pure o
    go o ("--json" : r) = go o { oJson = True } r
    go o ("--min-pct" : v : r) = nonneg "--min-pct" v >>= \n -> go o { oMinPct = Just n } r
    go o ("--source" : v : r) = case v of
      "auto" -> go o { oSource = Auto } r
      "paseo" -> go o { oSource = PaseoOnly } r
      "recent" -> go o { oSource = RecentOnly } r
      _ -> argError ("argument --source: invalid choice: " ++ show v ++ " (choose from 'auto', 'paseo', 'recent')")
    go o ("--recent-minutes" : v : r) = nonneg "--recent-minutes" v >>= \n -> go o { oRecent = n } r
    go _ ["--min-pct"] = argError "argument --min-pct: expected one argument"
    go _ ["--source"] = argError "argument --source: expected one argument"
    go _ ["--recent-minutes"] = argError "argument --recent-minutes: expected one argument"
    go _ (x : _) = argError ("unrecognized arguments: " ++ x)

envNonEmpty :: String -> IO (Maybe String)
envNonEmpty k = do
  m <- lookupEnv k
  pure $ case m of
    Just v | not (null v) -> Just v
    _ -> Nothing

homeDir :: IO FilePath
homeDir = fromMaybe "" <$> lookupEnv "HOME"

projectsDir :: IO FilePath
projectsDir = (</> ".claude" </> "projects") <$> homeDir

paseoHome :: IO FilePath
paseoHome = envNonEmpty "PASEO_HOME" >>= maybe ((</> ".paseo") <$> homeDir) pure

-- | A lower-case 8-4-4-4-12 hex id (the fleet PASEO_ID shape): the only ids allowed into paths or argv.
isUuid :: String -> Bool
isUuid s = length s == 36 && and (zipWith ok [0 :: Int ..] s)
  where
    ok i c
      | i `elem` [8, 13, 18, 23] = c == '-'
      | otherwise = isDigit c || (c >= 'a' && c <= 'f')

-- | The newest ~/.claude/projects/*/<session>.jsonl, by modification time.
findTranscript :: String -> IO (Maybe FilePath)
findTranscript session = do
  root <- projectsDir
  present <- doesDirectoryExist root
  if not present
    then pure Nothing
    else do
      dirs <- listDirectory root
      cands <- filterM doesFileExist [root </> d </> (session ++ ".jsonl") | d <- sortBy compare dirs]
      stamped <- forM cands $ \p -> do
        r <- try (getModificationTime p) :: IO (Either IOException UTCTime)
        pure (either (const Nothing) (\t -> Just (t, p)) r)
      pure $ case [x | Just x <- stamped] of
        [] -> Nothing
        xs -> Just (snd (foldl1 (\a b -> if fst b > fst a then b else a) xs))

-- | The first executable `paseo` in /opt/homebrew/bin then PATH (shutil.which with that path).
whichPaseo :: IO (Maybe FilePath)
whichPaseo = do
  path <- fromMaybe "" <$> lookupEnv "PATH"
  let dirs = "/opt/homebrew/bin" : splitColon ("/opt/homebrew/bin:" ++ path)
  hits <- filterM doesFileExist [d </> "paseo" | d <- dirs, not (null d)]
  pure (case hits of
    (h : _) -> Just h
    [] -> Nothing)
  where
    splitColon s = case break (== ':') s of
      (a, []) -> [a]
      (a, _ : r) -> a : splitColon r

-- | `paseo ls -g --background --json`: the object rows, or Left the reason it cannot be used.
paseoAgents :: IO (Either String [Value])
paseoAgents = do
  override <- envNonEmpty "CONTEXT_WATCH_PASEO"
  found <- maybe whichPaseo (pure . Just) override
  case found of
    Nothing -> pure (Left "paseo not found")
    Just cli -> do
      r <- try (readProcessWithExitCode cli ["ls", "-g", "--background", "--json"] "")
        :: IO (Either IOException (ExitCode, String, String))
      pure $ case r of
        Left e -> Left ("paseo ls failed (" ++ show e ++ ")")
        Right (ExitFailure n, _, _) -> Left ("paseo ls exited " ++ show n)
        Right (ExitSuccess, out, _) -> case parseJson out of
          Nothing -> Left "paseo ls printed no JSON"
          Just (VArr xs) -> Right [x | x@(VObj _) <- xs]
          Just _ -> Left "paseo ls JSON is not a list"

-- | The agent's state record: the first ~/.paseo/agents/*/<id>.json in sorted order that parses to an object.
agentState :: String -> IO Value
agentState aid = do
  home <- paseoHome
  let agentsDir = home </> "agents"
  present <- doesDirectoryExist agentsDir
  if not present
    then pure (VObj [])
    else do
      dirs <- listDirectory agentsDir
      cands <- filterM doesFileExist [agentsDir </> d </> (aid ++ ".json") | d <- sortBy compare dirs]
      firstObject cands
  where
    firstObject [] = pure (VObj [])
    firstObject (p : ps) = do
      r <- try (readFile p) :: IO (Either IOException String)
      case r of
        Right s | Just v@(VObj _) <- parseJson s -> pure v
        _ -> firstObject ps

-- | The session id from persistence or runtimeInfo, only when it is a uuid.
sessionOf :: Value -> Maybe String
sessionOf st = case [s | Just s <- map pick ["persistence", "runtimeInfo"]] of
  (s : _) -> Just s
  [] -> Nothing
  where
    pick k = do
      block <- field k st
      s <- asStr (field "sessionId" block)
      if isUuid s then Just s else Nothing

-- | The last tailBytes of a file as text (lenient UTF-8), a partial first line dropped.
readTail :: FilePath -> IO (Maybe [String])
readTail path = do
  r <- try $ withBinaryFile path ReadMode $ \h -> do
    size <- hFileSize h
    let start = max 0 (size - tailBytes)
    hSeek h AbsoluteSeek start
    bs <- B.hGetContents h
    pure (start, bs)
  case r of
    Left e -> const (pure Nothing) (e :: IOException)
    Right (start, bs) -> do
      let txt = T.unpack (TE.decodeUtf8With TEE.lenientDecode bs)
          body = if start > 0 then drop 1 (dropWhile (/= '\n') txt) else txt
      pure (Just (lines body))

-- | The raw `"subtype":"compact_boundary"` marker (whitespace after the colon allowed).
hasCompactBoundary :: String -> Bool
hasCompactBoundary l = any marker (tails l)
  where
    marker s = "\"subtype\":" `isPrefixOf` s && "\"compact_boundary\"" `isPrefixOf` dropWhile isSpace (drop 10 s)

isLiveAssistant :: Value -> Bool
isLiveAssistant rec = field "type" rec == Just (VStr "assistant") && field "isSidechain" rec /= Just (VBool True)

data Measured = Compacted | Tokens Integer | NoUsage

-- | The newest usage block's context size, or Compacted when a boundary is newer than any usage.
lastContext :: [String] -> Measured
lastContext ls = go (reverse ls)
  where
    go [] = NoUsage
    go (l : rest)
      | hasCompactBoundary l = Compacted
      | otherwise = case parseJson l of
          Just rec
            | isLiveAssistant rec
            , Just msg <- field "message" rec
            , Just usage <- field "usage" msg ->
                Tokens (sum [fromMaybe 0 (asInteger (field k usage)) | k <- usageKeys])
          _ -> go rest
    usageKeys = ["input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"]

-- | The newest live assistant record's model, skipping synthetic records.
lastModel :: [String] -> Maybe String
lastModel ls = case [m | l <- reverse ls, Just rec <- [parseJson l], isLiveAssistant rec
                       , Just msg <- [field "message" rec], Just m <- [asStr (field "model" msg)], m /= "<synthetic>"] of
  (m : _) -> Just m
  [] -> Nothing

-- | A settings window: a whole number above the buffer and at most maxWindow.
usableWindow :: Integer -> Maybe Integer
usableWindow n = if n > autoCompactBuffer && n <= maxWindow then Just n else Nothing

-- | The model's own window when its id says so: [1m] is 1M, Haiku 200k.
modelWindow :: Maybe String -> Maybe Integer
modelWindow Nothing = Nothing
modelWindow (Just m)
  | "[1m]" `isInfixOf` lower = Just longModelWindow
  | "haiku" `isInfixOf` lower = Just defaultModelWindow
  | otherwise = Nothing
  where
    lower = map toLower m

-- | Ceiling in tokens: the window minus the buffer; window = min(configured, model window).
ceilingFor :: Value -> Maybe String -> IO Integer
ceilingFor settings model = do
  envV <- envNonEmpty "CLAUDE_CODE_AUTO_COMPACT_WINDOW"
  let fromEnv = envV >>= \s -> readMaybe (trim s) >>= usableWindow
      perModel = do
        m <- model
        ms <- field "modelSettings" settings
        pm <- field m ms
        asInteger (field "autoCompactWindow" pm) >>= usableWindow
      fromSettings = asInteger (field "autoCompactWindow" settings) >>= usableWindow
      configured = firstJust [fromEnv, perModel, fromSettings]
      known = [w | Just w <- [configured, modelWindow model]]
      window = case known of
        [] | "[1m]" `isInfixOf` map toLower (fromMaybe "" (asStr (field "model" settings))) -> longModelWindow
           | otherwise -> defaultModelWindow
        ws -> minimum ws
  pure (window - autoCompactBuffer)
  where
    trim = dropWhile isSpace . reverse . dropWhile isSpace . reverse
    firstJust xs = case [x | Just x <- xs] of
      (x : _) -> Just x
      [] -> Nothing

readSettings :: IO Value
readSettings = do
  home <- homeDir
  r <- try (readFile (home </> ".claude" </> "settings.json")) :: IO (Either IOException String)
  pure $ case r of
    Right s | Just v@(VObj _) <- parseJson s -> v
    _ -> VObj []

-- | Fill ceiling, tokens, pct, headroom and status from a transcript (Nothing = missing).
measure :: Value -> Maybe String -> Row -> Maybe FilePath -> IO Row
measure settings providerModel row transcript = do
  tailLines <- maybe (pure Nothing) readTail transcript
  let ls = fromMaybe [] tailLines
      model = if null (fromMaybe "" providerModel) then lastModel ls else providerModel
  limit <- ceilingFor settings model
  let base = row { rTranscript = transcript, rTokens = Nothing, rPct = Nothing, rHeadroom = Nothing, rCeiling = Just limit }
  pure $ case transcript of
    Nothing -> base { rStatus = if null (rStatus row) then "no-transcript" else rStatus row }
    Just _ -> case lastContext ls of
      Compacted -> base { rStatus = "compacted" }
      Tokens t -> base
        { rStatus = "ok"
        , rTokens = Just t
        , rPct = Just (fromIntegral (round (1000 * fromIntegral t / fromIntegral limit :: Double) :: Integer) / 10)
        , rHeadroom = Just (limit - t)
        }
      NoUsage -> base { rStatus = "unreadable" }

blankRow :: String -> String -> Maybe String -> Maybe String -> String -> Row
blankRow aid title cwd session source = Row aid title cwd session source "" Nothing Nothing Nothing Nothing Nothing

paseoRows :: Value -> [Value] -> IO [Row]
paseoRows settings agents = fmap concat . forM agents $ \a -> do
  let provider = asStr (field "provider" a)
      aid = asStr (field "id" a)
  case (aid, provider) of
    (Just i, Just p) | isUuid i, "claude" `isPrefixOf` p -> do
      st <- agentState i
      let session = sessionOf st
          title = head ([t | Just t <- [nonEmpty (field "name" a), nonEmpty (field "title" st)]] ++ [""])
          cwd = case asStr (field "cwd" st) of
            Just c | not (null c) -> Just c
            _ -> asStr (field "cwd" a)
          model = drop 1 (dropWhile (/= '/') p)
          row0 = blankRow i title cwd session "paseo"
      case session of
        Nothing -> do
          row <- measure settings (Just model) row0 { rStatus = "no-session" } Nothing
          pure [row]
        Just s -> do
          tr <- findTranscript s
          row <- measure settings (Just model) row0 { rSession = Just s } tr
          pure [row]
    _ -> pure []
  where
    nonEmpty v = case asStr v of
      Just t | not (null t) -> Just t
      _ -> Nothing

-- | Recent transcripts modified within the window: the session id is the file stem.
recentRows :: Value -> Double -> IO [Row]
recentRows settings minutes = do
  root <- projectsDir
  now <- getCurrentTime
  present <- doesDirectoryExist root
  if not present
    then pure []
    else do
      dirs <- listDirectory root
      files <- fmap concat . forM (sortBy compare dirs) $ \d -> do
        names <- listDirectory (root </> d)
        pure [root </> d </> n | n <- sortBy compare names, ".jsonl" `isSuffixOf` n]
      fmap concat . forM files $ \path -> do
        let session = dropExtension (takeFileName path)
        if not (isUuid session)
          then pure []
          else do
            r <- try (getModificationTime path) :: IO (Either IOException UTCTime)
            case r of
              Left _ -> pure []
              Right mt
                | realToFrac (diffUTCTime now mt) > minutes * 60 -> pure []
                | otherwise -> do
                    cwd <- readCwd path
                    let title = case cwd of
                          Just c | not (null c) -> takeFileName c
                          _ -> lastDash (takeFileName (takeDirectory path))
                        lastDash = reverse . takeWhile (/= '-') . reverse
                    row <- measure settings Nothing (blankRow session title cwd (Just session) "recent") (Just path)
                    pure [row]

-- | `"cwd": "..."` from the first 64 KB of a transcript.
readCwd :: FilePath -> IO (Maybe String)
readCwd path = do
  r <- try (B.readFile path) :: IO (Either IOException B.ByteString)
  pure $ case r of
    Left _ -> Nothing
    Right bs ->
      let head' = T.unpack (TE.decodeUtf8With TEE.lenientDecode (B.take 65536 bs))
       in case [rest | t <- tails head', Just rest <- [afterKey t]] of
            (rest : _) -> rest
            [] -> Nothing
  where
    afterKey t
      | "\"cwd\":" `isPrefixOf` t =
          case parseJson ('"' : takeQuoted (dropWhile isSpace (drop 6 t))) of
            Just (VStr s) -> Just (Just s)
            _ -> Just Nothing
      | otherwise = Nothing
    takeQuoted ('"' : r) = scanStr r
    takeQuoted _ = "\"\""
    scanStr ('\\' : c : r) = '\\' : c : scanStr r
    scanStr ('"' : _) = "\""
    scanStr (c : r) = c : scanStr r
    scanStr [] = "\""

-- | Text from another process as one plain line: control characters out, whitespace runs to one space.
plain :: String -> String
plain = unwords . words . filter (\c -> c == '\n' || c == '\t' || not (isControl c))

kTokens :: Integer -> String
kTokens n = show (round (fromIntegral n / 1000 :: Double) :: Integer) ++ "k"

distance :: Integer -> String
distance n = if n < 1000 then "<1k" else kTokens n

formatRow :: Row -> String
formatRow r =
  let shortId = take 8 (rId r)
      headTxt = rstrip (plain shortId ++ " " ++ plain (rTitle r))
   in case (rStatus r, rTokens r, rCeiling r, rHeadroom r) of
        ("ok", Just t, Just limit, Just left) ->
          let wall = if left >= 0 then "wall in " ++ distance left else "wall passed by " ++ distance (negate left)
              pct = round (100 * fromIntegral t / fromIntegral limit :: Double) :: Integer
           in headTxt ++ " " ++ kTokens t ++ "/" ++ kTokens limit ++ " (" ++ show pct ++ "%) " ++ wall
        ("compacted", _, _, _) -> headTxt ++ " compacted"
        _ -> headTxt ++ " ?"
  where
    rstrip = reverse . dropWhile isSpace . reverse

-- | Python's json rendering of a row, in the key order the Python dict gains them.
rowOut :: Row -> Out
rowOut r =
  OObj $
    [ ("id", OStr (rId r))
    , ("short_id", OStr (take 8 (rId r)))
    , ("title", OStr (rTitle r))
    , ("cwd", maybe ONull OStr (rCwd r))
    , ("session", maybe ONull OStr (rSession r))
    , ("source", OStr (rSource r))
    ]
      ++ (if rStatus r == "no-session" then [("status", OStr "no-session")] else [])
      ++ [ ("transcript", maybe ONull OStr (rTranscript r))
         , ("tokens", maybe ONull OInt (rTokens r))
         , ("pct", maybe ONull OFloat (rPct r))
         , ("headroom", maybe ONull OInt (rHeadroom r))
         , ("ceiling", maybe ONull OInt (rCeiling r))
         ]
      ++ [("status", OStr (rStatus r)) | rStatus r /= "no-session"]

-- | `:g` formatting of the recent window for the stderr note.
gFormat :: Double -> String
gFormat x
  | x == fromIntegral (round x :: Integer) = show (round x :: Integer)
  | otherwise = show x

main :: IO ()
main = do
  opts <- getArgs >>= parseArgs
  settings <- readSettings
  paseoRes <-
    if oSource opts == RecentOnly
      then pure Nothing
      else do
        res <- paseoAgents
        case res of
          Right agents -> Just <$> paseoRows settings agents
          Left why
            | oSource opts == PaseoOnly -> do
                hPutStrLn stderr ("context-watch: " ++ why)
                pure (Just [])
            | otherwise -> do
                hPutStrLn stderr ("context-watch: " ++ why ++ "; using transcripts modified in the last "
                  ++ gFormat (oRecent opts) ++ " min")
                pure Nothing
  rows0 <- maybe (recentRows settings (oRecent opts)) pure paseoRes
  let rows = case oMinPct opts of
        Nothing -> rows0
        Just m -> [r | r <- rows0, Just t <- [rTokens r], Just l <- [rCeiling r], 100 * fromIntegral t / fromIntegral l >= m]
      sorted = sortBy (comparing (\r -> (isNothing (rPct r), negate (fromMaybe 0 (rPct r)), rId r))) rows
  if oJson opts
    then putStrLn (encodeIndent1 (OList (map rowOut sorted)))
    else mapM_ (putStrLn . formatRow) sorted
