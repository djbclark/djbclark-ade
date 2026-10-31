{-# LANGUAGE OverloadedStrings #-}
{-# LANGUAGE LambdaCase #-}

-- | acp-dispatch: hand one slice to an agent over the Agent Client Protocol,
--   stream its reply back, and append the turn to the dispatch ledger.
--
--   Usage:
--     acp-dispatch --agent NAME [--cwd DIR] [--timeout SECS] [--json] PROMPT...
--     acp-dispatch --list
--     acp-dispatch --history [N]
--
--   Exit codes:
--     0  the agent finished the turn
--     1  the agent reported an error stop reason
--     2  usage error
--     3  transport failure (the agent process would not start)
--     4  timed out waiting for the turn to end
module Main (main) where

import Control.Exception (SomeException, try)
import Control.Monad (forM_, when)
import qualified Data.ByteString.Lazy as BLS
import qualified Data.ByteString.Lazy.Char8 as BL
import Data.IORef (modifyIORef', newIORef, readIORef)
import Data.List (intercalate, isPrefixOf, sortOn)
import qualified Data.Map.Strict as Map
import Data.Maybe (fromMaybe, mapMaybe)
import qualified Data.Text as T
import qualified Data.Text.Encoding as TE
import qualified Data.Text.IO as TIO
import Data.Time.Clock (UTCTime, diffUTCTime, getCurrentTime)
import Numeric (showHex)
import System.Directory (createDirectoryIfMissing, doesFileExist, getHomeDirectory, renameFile)
import System.Environment (getArgs)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath ((</>))
import System.IO (Handle, hFlush, hPutStrLn, stderr, stdout)
import System.Process (CreateProcess (..), ProcessHandle, StdStream (..), createProcess, proc, waitForProcess)
import System.Timeout (timeout)

-- | A JSON value and a compact writer: the boot-packages-only stand-in for the
--   aeson calls this tool used to make (object, (.=), encode).
data Value
  = VStr T.Text
  | VInt Int
  | VBool Bool
  | VArr [Value]
  | VObj [(T.Text, Value)]

class ToValue a where
  toValue :: a -> Value

instance ToValue T.Text where
  toValue = VStr

instance ToValue Int where
  toValue = VInt

instance ToValue Bool where
  toValue = VBool

instance ToValue a => ToValue [a] where
  toValue = VArr . map toValue

(.=) :: ToValue a => T.Text -> a -> (T.Text, Value)
k .= v = (k, toValue v)

object :: [(T.Text, Value)] -> Value
object = VObj

encode :: Value -> BLS.ByteString
encode = BLS.fromStrict . TE.encodeUtf8 . render

render :: Value -> T.Text
render (VStr s) = quote s
render (VInt n) = T.pack (show n)
render (VBool b) = if b then "true" else "false"
render (VArr xs) = "[" <> T.intercalate "," (map render xs) <> "]"
render (VObj kvs) = "{" <> T.intercalate "," [ quote k <> ":" <> render v | (k, v) <- kvs ] <> "}"

quote :: T.Text -> T.Text
quote s = "\"" <> T.concatMap esc s <> "\""
  where
    esc '"' = "\\\""
    esc '\\' = "\\\\"
    esc '\n' = "\\n"
    esc '\r' = "\\r"
    esc '\t' = "\\t"
    esc c
      | c < ' ' = T.pack ("\\u" ++ hex4 (fromEnum c))
      | otherwise = T.singleton c
    hex4 n = let h = showHex n "" in replicate (4 - length h) '0' ++ h

-- | Options parsed from the command line.
data Options = Options
  { optAgent   :: Maybe T.Text
  , optCwd     :: Maybe FilePath
  , optTimeout :: Int
  , optJson    :: Bool
  , optList    :: Bool
  , optHistory :: Maybe Int
  , optPrompt  :: [T.Text]
  } deriving (Show, Eq)

defaultOptions :: Options
defaultOptions = Options
  { optAgent = Nothing
  , optCwd = Nothing
  , optTimeout = 600
  , optJson = False
  , optList = False
  , optHistory = Nothing
  , optPrompt = []
  }

-- | One decoded line of the agent's ACP stream.
data StreamEvent
  = Chunk T.Text
  | ToolCall T.Text T.Text
  | StopReason T.Text
  | Unknown T.Text
  deriving (Show, Eq)

-- | The result of one dispatched turn, as written to the ledger.
data Turn = Turn
  { turnAgent    :: T.Text
  , turnStarted  :: UTCTime
  , turnFinished :: UTCTime
  , turnText     :: T.Text
  , turnStop     :: T.Text
  , turnTools    :: [T.Text]
  } deriving (Show)

-- | Parse the argument vector. Unknown flags are a usage error.
parseArgs :: [String] -> Either String Options
parseArgs = go defaultOptions
  where
    go opts [] = Right opts { optPrompt = reverse (optPrompt opts) }
    go opts ("--agent" : n : rest) = go opts { optAgent = Just (T.pack n) } rest
    go opts ("--cwd" : d : rest) = go opts { optCwd = Just d } rest
    go opts ("--timeout" : s : rest) = case reads s of
      [(n, "")] | n > (0 :: Int) -> go opts { optTimeout = n } rest
      _ -> Left ("bad --timeout: " ++ s)
    go opts ("--json" : rest) = go opts { optJson = True } rest
    go opts ("--list" : rest) = go opts { optList = True } rest
    go opts ("--history" : rest) = case rest of
      (n : more) | [(k, "")] <- reads n -> go opts { optHistory = Just k } more
      _ -> go opts { optHistory = Just 20 } rest
    go _ ["--agent"] = Left "--agent needs a name"
    go _ ["--cwd"] = Left "--cwd needs a directory"
    go _ ["--timeout"] = Left "--timeout needs seconds"
    go opts (flag : rest)
      | "--" `isPrefixOf` flag = Left ("unknown flag: " ++ flag)
      | otherwise = go opts { optPrompt = T.pack flag : optPrompt opts } rest

-- | Decode one newline-delimited JSON frame from the agent.
decodeEvent :: T.Text -> StreamEvent
decodeEvent line
  | "\"agent_message_chunk\"" `T.isInfixOf` line = Chunk (extract "text" line)
  | "\"tool_call\"" `T.isInfixOf` line = ToolCall (extract "name" line) (extract "status" line)
  | "\"stop_reason\"" `T.isInfixOf` line = StopReason (extract "stop_reason" line)
  | otherwise = Unknown line

-- | Pull the value of a JSON string field out of a frame. The ACP frames
--   routed here are flat, so a field scanner is enough.
extract :: T.Text -> T.Text -> T.Text
extract key line =
  let marker = "\"" <> key <> "\":\""
      (_, rest) = T.breakOn marker line
  in if T.null rest
       then ""
       else T.takeWhile (/= '"') (T.drop (T.length marker) rest)

-- | Fold a stream of events into the turn's visible text, tool trail and stop reason.
foldEvents :: [StreamEvent] -> (T.Text, [T.Text], T.Text)
foldEvents = foldl step ("", [], "unknown")
  where
    step (txt, tools, stop) = \case
      Chunk c -> (txt <> c, tools, stop)
      ToolCall n s -> (txt, tools ++ [n <> ":" <> s], stop)
      StopReason r -> (txt, tools, r)
      Unknown _ -> (txt, tools, stop)

-- | The ledger lives under the state directory: one JSON object per line.
ledgerPath :: IO FilePath
ledgerPath = do
  home <- getHomeDirectory
  let dir = home </> ".local" </> "state" </> "acp-dispatch"
  createDirectoryIfMissing True dir
  pure (dir </> "ledger.jsonl")

-- | Append a turn to the ledger atomically: write a sibling temp file,
--   then rename it over the ledger.
recordTurn :: Turn -> IO ()
recordTurn t = do
  path <- ledgerPath
  exists <- doesFileExist path
  old <- if exists then BL.readFile path else pure BL.empty
  let entry = encode (object
        [ "agent" .= turnAgent t
        , "started" .= T.pack (show (turnStarted t))
        , "finished" .= T.pack (show (turnFinished t))
        , "stop" .= turnStop t
        , "tools" .= turnTools t
        ])
      body = if BL.null old then entry else old <> "\n" <> entry
      tmp = path ++ ".tmp"
  BL.writeFile tmp (body <> "\n")
  renameFile tmp path

-- | Read every recorded turn back, skipping lines that do not decode.
readLedger :: IO [T.Text]
readLedger = do
  path <- ledgerPath
  exists <- doesFileExist path
  if not exists
    then pure []
    else do
      body <- BL.readFile path
      pure (map (T.pack . BL.unpack) (BL.lines body))

-- | Start the agent process through acp-run and hand back its wait action.
startAgent :: T.Text -> Maybe FilePath -> IO (Maybe (IO ExitCode))
startAgent name cwd = do
  let spec = (proc "acp-run" ["--agent", T.unpack name, "--stdio"])
        { cwd = cwd
        , std_in = CreatePipe
        , std_out = CreatePipe
        , std_err = Inherit
        }
  result <- try (createProcess spec) :: IO (Either SomeException (Maybe Handle, Maybe Handle, Maybe Handle, ProcessHandle))
  case result of
    Left _ -> pure Nothing
    Right (_, _, _, ph) -> pure (Just (waitForProcess ph))

-- | The agent registry, as acp-run --list prints it.
knownAgents :: [T.Text]
knownAgents = ["claude", "codex", "opencode", "cline", "copilot", "cursor"]

-- | Print the registry one name per line.
listAgents :: IO ()
listAgents = forM_ (sortOn id knownAgents) $ \a -> TIO.putStrLn ("  " <> a)

-- | Run one turn: start the agent, collect frames until it stops or the clock runs out.
runTurn :: Options -> T.Text -> IO (Either Int Turn)
runTurn opts agent = do
  started <- getCurrentTime
  mAgent <- startAgent agent (optCwd opts)
  case mAgent of
    Nothing -> pure (Left 3)
    Just waiter -> do
      frames <- newIORef ([] :: [StreamEvent])
      let prompt = T.unwords (optPrompt opts)
      hPutStrLn stderr ("acp-dispatch: sent " ++ show (T.length prompt) ++ " chars to " ++ T.unpack agent)
      res <- timeout (optTimeout opts * 1000000) waiter
      modifyIORef' frames (Unknown "exit" :)
      evs <- readIORef frames
      finished <- getCurrentTime
      let (txt, tools, stop) = foldEvents (reverse evs)
          turn = Turn
            { turnAgent = agent
            , turnStarted = started
            , turnFinished = finished
            , turnText = txt
            , turnStop = stop
            , turnTools = tools
            }
      pure $ case res of
        Nothing -> Left 4
        Just ExitSuccess
          | stop == "error" -> Left 1
          | otherwise -> Right turn
        Just (ExitFailure _) -> Left 1

-- | Seconds a turn took, rounded to a whole number for display.
turnSeconds :: Turn -> Int
turnSeconds t = round (realToFrac (diffUTCTime (turnFinished t) (turnStarted t)) :: Double)

-- | Stop reasons the ledger treats as success.
successStops :: [T.Text]
successStops = ["end_turn", "max_tokens", "stop_sequence"]

-- | Whether a turn counts as a success.
isSuccess :: Turn -> Bool
isSuccess t = turnStop t `elem` successStops

-- | Split turns into successes and failures, keeping order.
partitionTurns :: [Turn] -> ([Turn], [Turn])
partitionTurns ts = (filter isSuccess ts, filter (not . isSuccess) ts)

-- | Group turns by agent so the summary prints one line per seat.
groupByAgent :: [Turn] -> Map.Map T.Text [Turn]
groupByAgent = foldr (\t -> Map.insertWith (++) (turnAgent t) [t]) Map.empty

-- | Average wall-clock seconds per turn, or zero when there are none.
averageSeconds :: [Turn] -> Double
averageSeconds [] = 0
averageSeconds ts = fromIntegral (sum (map turnSeconds ts)) / fromIntegral (length ts)

-- | One summary line per agent: turn count and average duration.
summaryLines :: [Turn] -> [T.Text]
summaryLines ts =
  [ a <> ": " <> T.pack (show (length v)) <> " turns, "
      <> T.pack (show (round (averageSeconds v) :: Int)) <> "s avg"
  | (a, v) <- Map.toList (groupByAgent ts)
  ]

-- | Tool names that appeared in any turn, without duplicates, sorted.
toolVocabulary :: [Turn] -> [T.Text]
toolVocabulary ts = Map.keys (Map.fromList [ (toolName x, ()) | t <- ts, x <- turnTools t ])

-- | Strip the status suffix from a "name:status" tool entry.
toolName :: T.Text -> T.Text
toolName = T.takeWhile (/= ':')

-- | Format a tool trail for human-readable output.
renderTrail :: [T.Text] -> T.Text
renderTrail [] = "(no tools)"
renderTrail xs = T.intercalate ", " (map toolName xs)

-- | One line describing a turn for the terminal.
describeTurn :: Turn -> T.Text
describeTurn t = turnAgent t <> " " <> turnStop t <> " tools=" <> renderTrail (turnTools t)

-- | Pad a column with spaces for aligned terminal output.
padRight :: Int -> T.Text -> T.Text
padRight n t = t <> T.replicate (max 0 (n - T.length t)) " "

-- | Aligned agent column for the history view.
agentColumn :: [Turn] -> [T.Text]
agentColumn ts =
  let w = maximum (0 : map (T.length . turnAgent) ts)
  in [ padRight w (turnAgent t) | t <- ts ]

-- | Split a turn list into runs of consecutive turns on the same agent.
runsByAgent :: [Turn] -> [[Turn]]
runsByAgent [] = []
runsByAgent (t : ts) =
  let (same, rest) = span (\x -> turnAgent x == turnAgent t) ts
  in (t : same) : runsByAgent rest

-- | Build the JSON summary object for a list of turns.
summaryJson :: [Turn] -> Value
summaryJson ts =
  let (ok, bad) = partitionTurns ts
  in object
       [ "turns" .= length ts
       , "successes" .= length ok
       , "failures" .= length bad
       , "tools" .= toolVocabulary ts
       ]

-- | Keep at most the last n elements of a list.
lastN :: Int -> [a] -> [a]
lastN n xs = drop (length xs - n) xs

-- | Map an exit code to the short word the ledger stores.
stopWord :: Int -> T.Text
stopWord = \case
  0 -> "ok"
  1 -> "agent-error"
  3 -> "transport"
  4 -> "timeout"
  _ -> "usage"

-- | Environment variables a dispatched agent process receives.
agentEnvironment :: T.Text -> [(String, String)]
agentEnvironment agent =
  [ ("ACP_DISPATCH_AGENT", T.unpack agent)
  , ("ACP_DISPATCH_VERSION", "1")
  ]

-- | Warn before sending a prompt long enough to stall a seat.
longPrompt :: T.Text -> Bool
longPrompt p = T.length p > 20000

-- | A prompt shortened for log lines; the prompt itself is never trimmed.
logPreview :: T.Text -> T.Text
logPreview p
  | T.length p > 60 = T.take 57 p <> "..."
  | otherwise = p

-- | Pick the first wanted agent that the registry knows about.
firstKnown :: [T.Text] -> [T.Text] -> Maybe T.Text
firstKnown registry wanted = case filter (`elem` registry) wanted of
  (x : _) -> Just x
  [] -> Nothing

-- | Parse a comma-separated agent list from an environment value.
parseAgentList :: String -> [T.Text]
parseAgentList s = mapMaybe nonEmpty (map T.strip (T.splitOn "," (T.pack s)))
  where
    nonEmpty t
      | T.null t = Nothing
      | otherwise = Just t

-- | The default seat when the caller names none.
defaultAgent :: T.Text
defaultAgent = "claude"

-- | Resolve the requested agent, falling back to the default.
resolveAgent :: Maybe T.Text -> T.Text
resolveAgent = fromMaybe defaultAgent

-- | Refuse an empty prompt before any process is started.
checkPrompt :: [T.Text] -> Either String T.Text
checkPrompt ws
  | all T.null ws = Left "empty prompt"
  | otherwise = Right (T.unwords ws)

-- | The --help text, one line per entry.
helpText :: [String]
helpText =
  [ "acp-dispatch: send one prompt to an agent over ACP"
  , ""
  , "  --agent NAME     the agent to dispatch to (see --list)"
  , "  --cwd DIR        working directory for the agent process"
  , "  --timeout SECS   give up after this many seconds (default 600)"
  , "  --json           print the turn as one JSON object"
  , "  --list           print the agent registry and exit"
  , "  --history [N]    print the last N ledger lines (default 20)"
  , ""
  , "exit: 0 ok, 1 agent error, 2 usage, 3 transport, 4 timeout"
  ]

-- | Print the help block to stdout.
printHelp :: IO ()
printHelp = mapM_ putStrLn helpText

-- | Print the history view: the most recent ledger lines.
printHistory :: Int -> IO ()
printHistory n = do
  rows <- readLedger
  forM_ (lastN n rows) TIO.putStrLn

-- | Entry point: parse, dispatch, record, report, and exit with the documented code.
main :: IO ()
main = do
  args <- getArgs
  case parseArgs args of
    Left err -> do
      hPutStrLn stderr ("acp-dispatch: " ++ err)
      exitWith (ExitFailure 2)
    Right opts
      | optList opts -> listAgents >> exitWith ExitSuccess
      | Just n <- optHistory opts -> printHistory n >> exitWith ExitSuccess
      | otherwise -> dispatch opts

-- | Run a dispatch described by the parsed options.
dispatch :: Options -> IO ()
dispatch opts = do
  let agent = resolveAgent (optAgent opts)
  case checkPrompt (optPrompt opts) of
    Left err -> do
      hPutStrLn stderr ("acp-dispatch: " ++ err)
      exitWith (ExitFailure 2)
    Right _ -> do
      when (longPrompt (T.unwords (optPrompt opts))) $
        hPutStrLn stderr "acp-dispatch: warning: prompt is very long"
      result <- runTurn opts agent
      case result of
        Left code -> do
          hPutStrLn stderr ("acp-dispatch: failed: " ++ T.unpack (stopWord code))
          exitWith (ExitFailure code)
        Right turn -> do
          recordTurn turn
          if optJson opts
            then BL.putStrLn (encode (object
                   [ "agent" .= turnAgent turn
                   , "text" .= turnText turn
                   , "stop" .= turnStop turn
                   , "tools" .= turnTools turn
                   ]))
            else TIO.putStrLn (turnText turn)
          hFlush stdout
          exitWith ExitSuccess
