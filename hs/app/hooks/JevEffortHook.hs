-- | UserPromptSubmit: optional effort observation through bin/jev. Failures never block a prompt.
-- Port of claude/hooks/jev_effort_hook.py (hs-curry).
--
-- Port notes: the Python SIGALRM budget (2.9 s) is System.Timeout, and the child's own 2.7 s
-- deadline is a timeout on the talk to it. A bracket kills the child's process group on every exit
-- path, as the Python finally block does. A compiled binary has no __file__, so the repo root comes
-- from ADE_REPO (default ~/src/djbclark-ade). Every error path returns quietly, as the original does.
module Main (main) where

import Ade.HsCurry.Hook
import Ade.HsCurry.Match (isWordChar, pyStrip)
import Ade.Json (Value (..), parseJson)
import Control.Exception (IOException, SomeException, bracket, catch, evaluate, try)
import Control.Monad (void)
import qualified Data.ByteString.Char8 as B8
import Data.Char (isSpace, toLower)
import Data.List (dropWhileEnd, isInfixOf, isPrefixOf, isSuffixOf, stripPrefix)
import GHC.Clock (getMonotonicTime)
import Numeric (showFFloat)
import System.Directory (getHomeDirectory)
import System.Environment (getEnvironment, lookupEnv)
import System.Exit (ExitCode (..), exitSuccess)
import System.FilePath ((</>))
import System.IO
import System.Posix.Signals (sigKILL, signalProcessGroup)
import System.Posix.Types (ProcessID)
import System.Process (CreateProcess (..), ProcessHandle, StdStream (..), createProcess, getPid, getProcessExitCode, proc, waitForProcess)
import System.Timeout (timeout)

question :: String
question = "How much reasoning does the next stretch of work this prompt asks for need?"

-- | mode(): JEV_MODE, else the first word of ~/.config/jev/mode; anything but shadow or act is off.
modeOf :: IO String
modeOf = do
  env <- lookupEnv "JEV_MODE"
  raw <- case env of
    Just v -> return v
    Nothing -> do
      home <- getHomeDirectory
      r <-
        try (do t <- readFile (home </> ".config/jev/mode"); _ <- evaluate (length t); return t)
          :: IO (Either IOException String)
      return $ case r of
        Right t -> case words t of
          (w : _) -> w
          [] -> "off"
        Left _ -> "off"
  return (if raw `elem` ["shadow", "act"] then raw else "off")

-- | Prompts that are too short, slash commands, wrapped notices or tool-result payloads are not observed.
skipPrompt :: String -> Bool
skipPrompt raw = length text < 20 || "/" `isPrefixOf` text || wrappedNotice text || toolResultsOnly text
  where
    text = pyStrip (unwrapPasted (pyStrip raw))

-- | Strip `<pasted_content ...>` at the front and `</pasted_content ...>` at the end, as the Python re.sub does.
unwrapPasted :: String -> String
unwrapPasted = stripTail . stripHead
  where
    stripHead s = case stripPrefix "<pasted_content" s of
      Just r@(c : _)
        | not (isWordChar c)
        , (_, '>' : rest) <- break (== '>') r ->
            dropWhile isSpace rest
      _ -> s
    stripTail s =
      case [ k
           | k <- [0 .. length s - 1]
           , "</pasted_content" `isPrefixOf` drop k s
           , last s == '>'
           , '>' `notElem` take (length s - 1 - k) (drop k s)
           ] of
        (k : _) -> dropWhileEnd isSpace (take k s)
        [] -> s

-- | `<(task-notification|tool_result|tool-result)\b[^>]*>.*</\1>` as a whole-text match.
wrappedNotice :: String -> Bool
wrappedNotice t = any wrapped ["task-notification", "tool_result", "tool-result"]
  where
    wrapped name = case stripPrefix ("<" ++ name) t of
      Just r@(c : _) | not (isWordChar c), (_, '>' : body) <- break (== '>') r ->
        let closing = "</" ++ name ++ ">"
         in closing `isSuffixOf` body && length body >= length closing
      _ -> False

-- | The text is JSON made only of tool_result blocks (one object or a non-empty list).
toolResultsOnly :: String -> Bool
toolResultsOnly t = case parseJson t of
  Nothing -> False
  Just v ->
    let blocks = case v of
          VArr xs -> xs
          other -> [other]
     in not (null blocks) && all isToolResult blocks
  where
    isToolResult (VObj kvs) = lookup "type" kvs == Just (VStr "tool_result")
    isToolResult _ = False

firstTruthy :: [Maybe Value] -> Maybe Value
firstTruthy xs = listToMaybe' [v | Just v <- xs, pyTruthy v]
  where
    listToMaybe' ys = case ys of
      (y : _) -> Just y
      [] -> Nothing

-- | model_from_tail(): the model of the last assistant entry in the final 64 KiB of the transcript.
-- Nothing where the Python would raise (a non-object entry, a non-string model), which ends the hook.
modelFromTail :: Maybe FilePath -> IO (Maybe String)
modelFromTail Nothing = return (Just "unknown")
modelFromTail (Just path) = do
  r <- try (withBinaryFile path ReadMode readTail) :: IO (Either IOException (Bool, B8.ByteString))
  case r of
    Left _ -> return (Just "unknown")
    Right (partial, bytes) -> do
      let ls0 = B8.lines bytes
          ls = if partial then drop 1 ls0 else ls0
      return (scan (reverse ls))
  where
    readTail h = do
      size <- hFileSize h
      let start = max 0 (size - 65536)
      hSeek h AbsoluteSeek start
      bytes <- B8.hGet h 65536
      return (start > 0, bytes)
    scan [] = Just "unknown"
    scan (l : rest) = case parseJson (B8.unpack l) of
      Nothing -> scan rest
      Just (VObj kvs)
        | lookup "type" kvs == Just (VStr "assistant") -> entryModel kvs
        | otherwise -> scan rest
      Just _ -> Nothing
    entryModel kvs = case objOf (lookup "message" kvs) of
      Nothing -> Nothing
      Just msg -> case firstTruthy [lookup "model" msg, lookup "model" kvs] of
        Nothing -> Just "unknown"
        Just (VStr m) -> Just m
        Just _ -> Nothing

-- | The child process: stdin and stdout pipes, stderr to /dev/null, its own session, JEV_MODE set.
type Child = (Handle, Handle, ProcessHandle, Maybe ProcessID)

spawnJev :: FilePath -> [String] -> String -> IO Child
spawnJev jev args sel = do
  environ <- getEnvironment
  devnull <- openFile "/dev/null" WriteMode
  (Just hin, Just hout, _, ph) <-
    createProcess
      (proc jev args)
        { std_in = CreatePipe
        , std_out = CreatePipe
        , std_err = UseHandle devnull
        , env = Just (("JEV_MODE", sel) : [kv | kv@(k, _) <- environ, k /= "JEV_MODE"])
        , new_session = True
        }
  hSetEncoding hin utf8
  hSetEncoding hout utf8
  pid <- getPid ph
  return (hin, hout, ph, pid)

-- | The finally block: kill the group if the child is still running, reap it, close the pipes.
releaseJev :: Child -> IO ()
releaseJev (hin, hout, ph, mpid) = do
  alive <- getProcessExitCode ph
  case (alive, mpid) of
    (Nothing, Just pid) -> void (try (signalProcessGroup sigKILL pid) :: IO (Either SomeException ()))
    _ -> return ()
  void (waitForProcess ph)
  mapM_ (\h -> void (try (hClose h) :: IO (Either SomeException ()))) [hin, hout]

-- | communicate(prompt[:4000], timeout=remaining): the child's exit code and stdout, or Nothing on timeout.
talk :: Child -> String -> Double -> IO (Maybe (ExitCode, String))
talk (hin, hout, ph, _) prompt remaining =
  timeout (round (remaining * 1000000)) $ do
    hPutStr hin (take 4000 prompt)
    hClose hin
    out <- hGetContents hout
    _ <- evaluate (length out)
    code <- waitForProcess ph
    return (code, out)

-- | Prints the systemMessage only in act mode, for a confident mechanical call on an Opus or Fable session.
handleOutput :: String -> String -> String -> IO ()
handleOutput sel model out = case parseJson out of
  Just (VObj r)
    | sel == "act"
    , lookup "answer" r == Just (VStr "mechanical")
    , maybe False pyTruthy (lookup "confident" r)
    , any (`isInfixOf` map toLower model) ["opus", "fable"]
    , Just (VNum pStr) <- lookup "prob" r
    , [(p, _)] <- (reads pStr :: [(Double, String)]) ->
        emit (JObj [("systemMessage", JStr (message p))])
  _ -> return ()
  where
    message p =
      "jev: this looks mechanical (p=" ++ showFFloat (Just 2) p "" ++ "); /model sonnet would cost less"

decide :: String -> [(String, Value)] -> String -> String -> Double -> IO ()
decide sel kvs model prompt remaining = do
  repo <- do
    env <- lookupEnv "ADE_REPO"
    case env of
      Just r | not (null r) -> return r
      _ -> (</> "src/djbclark-ade") <$> getHomeDirectory
  let sid = maybe "" pyStr (lookup "session_id" kvs)
      args =
        [ "decide", "--site", "prompt-effort", "--question", question
        , "--option", "mechanical", "--option", "normal", "--option", "hard"
        , "--meta", "model=" ++ model, "--meta", "session=" ++ sid
        , "--timeout", showFFloat Nothing (max 0.001 (remaining - 0.1)) ""
        ]
  r <-
    try (bracket (spawnJev (repo </> "bin/jev") args sel) releaseJev (\c -> talk c prompt remaining))
      :: IO (Either SomeException (Maybe (ExitCode, String)))
  case r of
    Right (Just (ExitSuccess, out)) -> handleOutput sel model out
    _ -> return ()

hookBody :: String -> Double -> IO ()
hookBody sel started = do
  mv <- readHookInput
  case mv of
    Just (VObj kvs) -> case lookup "prompt" kvs of
      Just (VStr prompt) | not (skipPrompt prompt) -> do
        let transcript = case lookup "transcript_path" kvs of
              Just (VStr p) -> Just p
              _ -> Nothing
        mmodel <- modelFromTail transcript
        case mmodel of
          Nothing -> return ()
          Just model -> do
            now <- getMonotonicTime
            let remaining = 2.7 - (now - started)
            if remaining <= 0 then return () else decide sel kvs model prompt remaining
      _ -> return ()
    _ -> return ()

main :: IO ()
main = do
  sel <- modeOf
  if sel == "off"
    then exitSuccess
    else do
      started <- getMonotonicTime
      _ <- timeout 2900000 (hookBody sel started `catch` ignore)
      exitSuccess
  where
    ignore :: SomeException -> IO ()
    ignore _ = return ()
