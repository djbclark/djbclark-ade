-- | autorename_nudge: ask the agent to title an untitled session, once (hs-thunk port).
--
-- UserPromptSubmit hook (Stop for Grok). Hands the agent a note to run the autorename skill in
-- --auto mode as the last step of the turn. Fires at most once per session (state in
-- ~/.local/state/autorename/<sid>.nudged). Always exits 0; a 2 s deadline ends a slow run silently.
--
-- Port notes: the title and manual-title lookups live in the Python autorename module (zcode keeps
-- its titles in a sqlite session db, and the boot packages have no sqlite), so those four
-- predicates are one-shot `python3 -I -c` calls into that module, arguments passed as argv and never
-- spliced into the code. A crash in the original (no output) is Nothing here. SKILL_DIR is
-- ADE_AUTORENAME_DIR, else ~/djbclark-ade/skills/autorename (the Python used its own __file__).
module Main (main) where

import Ade.HsThunk.Hook
import Ade.JsonLite (Json (..), parseJson)
import Control.Exception (evaluate)
import Control.Monad (unless, when)
import Data.Char (isSpace)
import Data.List (isPrefixOf)
import System.Directory (createDirectoryIfMissing, doesFileExist)
import System.Environment (lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath ((</>))
import System.IO (IOMode (..), hGetLine, hSetEncoding, utf8, withFile)
import System.Posix.Process (getParentProcessID)
import System.Process (proc, readCreateProcessWithExitCode)
import System.Timeout (timeout)

deadlineMicro, minPromptChars :: Int
deadlineMicro = 2000000
minPromptChars = 20

pyBinary :: FilePath
pyBinary = "/opt/homebrew/opt/python@3.14/bin/python3.14"

-- | The interpreter named in the note: the Homebrew 3.14 when it exists, else python3.
pyOf :: IO FilePath
pyOf = do
  there <- doesFileExist pyBinary
  pure (if there then pyBinary else "python3")

-- | The autorename module's folder.
skillDirOf :: IO FilePath
skillDirOf = do
  override <- lookupEnv "ADE_AUTORENAME_DIR"
  case override of
    Just d | not (null d) -> pure d
    _ -> fmap (</> "djbclark-ade/skills/autorename") homeDir

-- | The backend: cursor-agent, Grok, zcode (sess_ ids) or Claude Code.
data Backend = Claude | Zcode | Grok | Cursor deriving (Eq)

-- | One-shot query into the Python autorename module. Each snippet prints 1 or 0. A crash, a
-- non-zero exit or any other output is Nothing (the original raises, and prints nothing).
pyBool :: FilePath -> String -> [String] -> IO (Maybe Bool)
pyBool skillDir snippet args = do
  py <- pyOf
  r <- tryAny (readCreateProcessWithExitCode (proc py (["-I", "-c", snippet, skillDir] ++ args)) "")
  pure $ case r of
    Right (ExitSuccess, out, _) -> case strip out of
      "1" -> Just True
      "0" -> Just False
      _ -> Nothing
    _ -> Nothing

-- | Each snippet prints 1 when the session should NOT be nudged (titled, manual, or unknown).
snippetFor :: Backend -> String
snippetFor Claude = unlines
  [ "import sys", "sys.path.insert(0, sys.argv[1])", "from pathlib import Path"
  , "from autorename import current_title"
  , "print(int(current_title(Path(sys.argv[2])) is not None))" ]
snippetFor Zcode = unlines
  [ "import sys", "sys.path.insert(0, sys.argv[1])"
  , "from autorename import zcode_current_title"
  , "row = zcode_current_title(sys.argv[2])"
  , "print(int(row is None or row[1] in ('generated', 'custom')))" ]
snippetFor Grok = unlines
  [ "import sys", "sys.path.insert(0, sys.argv[1])"
  , "from autorename import find_grok_summary, grok_read"
  , "s = find_grok_summary(sys.argv[2])"
  , "if s is None:"
  , "    print(1)"
  , "else:"
  , "    try:"
  , "        print(int(grok_read(s)[2] == 'manual'))"
  , "    except (OSError, ValueError):"
  , "        print(1)" ]
snippetFor Cursor = unlines
  [ "import sys", "sys.path.insert(0, sys.argv[1])"
  , "from autorename import find_cursor_chat, cursor_read"
  , "c = find_cursor_chat(sys.argv[2])"
  , "if c is None:"
  , "    print(0)"
  , "else:"
  , "    try:"
  , "        print(int(cursor_read(c)[1] == 'manual'))"
  , "    except (OSError, ValueError):"
  , "        print(1)" ]

-- | claude_has_title: a missing transcript counts as untitled.
claudeHasTitle :: FilePath -> String -> IO (Maybe Bool)
claudeHasTitle skillDir transcript = do
  there <- if null transcript then pure False else doesFileExist transcript
  if there then pyBool skillDir (snippetFor Claude) [transcript] else pure (Just False)

-- | The first user message of a transcript (zcode writes one JSON line), or Nothing.
firstPromptFromTranscript :: FilePath -> IO (Maybe String)
firstPromptFromTranscript path = do
  r <- tryAny $ withFile path ReadMode $ \h -> do
    hSetEncoding h utf8
    line <- hGetLine h
    _ <- evaluate (length line)
    pure line
  pure $ case r of
    Right line -> case parseJson line of
      Right obj -> case (field "message" obj, field "content" (field "message" obj)) of
        (JObj _, JArr (b : _)) -> case field "text" b of
          JStr t -> Just t
          _ -> Nothing
        _ -> Nothing
      Left _ -> Nothing
    Left _ -> Nothing

-- | True when the cursor-agent above this hook runs headless (acp, -p or --print). Walks the parent
-- chain of ps, 64 levels at most.
cursorHeadless :: IO Bool
cursorHeadless = do
  r <- tryAny (timeout 1000000 (readCreateProcessWithExitCode (proc "ps" ["-A", "-o", "pid=,ppid=,args="]) ""))
  case r of
    Right (Just (_, out, _)) -> do
      let procs = [ (pid, (ppid, argv)) | Just (pid, ppid, argv) <- map parseProc (lines out) ]
      me <- getParentProcessID
      pure (walk procs (fromIntegral me) (64 :: Int))
    _ -> pure False
  where
    walk _ _ 0 = False
    walk procs pid n = case lookup pid procs of
      Nothing -> False
      Just (ppid, argv)
        | pid <= 1 -> False
        | (cmd : rest) <- argv, baseName cmd == "cursor-agent" ->
            any (`elem` ["acp", "-p", "--print"]) rest
        | otherwise -> walk procs ppid (n - 1)
    baseName = reverse . takeWhile (/= '/') . reverse

-- | Python line.split(None, 2): pid, ppid, then the argv words. Digits-only ids.
parseProc :: String -> Maybe (Int, Int, [String])
parseProc l =
  let (a, r1) = break isSpace (dropWhile isSpace l)
      (b, r2) = break isSpace (dropWhile isSpace r1)
      rest = dropWhile isSpace r2
  in if null a || null b || null rest || not (all isDigitC a) || not (all isDigitC b)
       then Nothing
       else Just (read a, read b, words rest)
  where
    isDigitC c = c >= '0' && c <= '9'

-- | The note, exactly as the original prints it.
noteText :: FilePath -> String -> String
noteText py skillDir = concat
  [ "[autorename] This session has no title yet. As the LAST step of this turn, after "
  , "the requested work, follow the autorename skill in --auto mode: pick a title, run "
  , "`", py, " ", skillDir, "/autorename.py --auto \"<title>\"`, THEN run "
  , "`", py, " ", skillDir, "/herdr_place.py label --from-title` (labels a generic herdr tab from the new "
  , "title; prints `skipped:` outside herdr and in a Paseo-hosted agent, whose tab autorename.py names). "
  , "Rename nothing else: no workspace, no moving the tab. "
  , "Mention the result in one line; don't otherwise discuss this note." ]

-- | Plain text for Claude Code, a cursor additional_context, or hookSpecificOutput for zcode/Grok.
emit :: Backend -> String -> IO ()
emit Claude note = putStrLn note
emit Cursor note = putStrLn (renderCompact (JObj [("additional_context", JStr note)]))
emit b note =
  let event = if b == Grok then "Stop" else "UserPromptSubmit"
  in putStrLn (renderCompact (JObj
       [("hookSpecificOutput", JObj [("hookEventName", JStr event), ("additionalContext", JStr note)])]))

-- | The title check for the backend, then the note if the session still needs one.
dispatch :: Backend -> String -> String -> String -> IO ()
dispatch backend sid transcript skillDir = do
  verdict <- case backend of
    Claude -> claudeHasTitle skillDir transcript
    _ -> pyBool skillDir (snippetFor backend) [sid]
  py <- pyOf
  case verdict of
    Just False -> emit backend (noteText py skillDir)
    _ -> pure ()

run :: Json -> IO ()
run dataV = do
  let event = strField "hook_event_name" dataV
      eventSnake = strField "hookEventName" dataV
      cursor = any jTruthy [field "cursor_version" dataV, field "generation_id" dataV]
               || event == "beforeSubmitPrompt"
      grok = not cursor && (event == "Stop" || eventSnake == "stop")
      sid = case filter (not . null)
              [if cursor then strField "conversation_id" dataV else "", strField "session_id" dataV, strField "sessionId" dataV] of
              (s : _) -> s
              [] -> ""
      zcode = not (grok || cursor) && "sess_" `isPrefixOf` sid
      backend | cursor = Cursor
              | grok = Grok
              | zcode = Zcode
              | otherwise = Claude
      transcript = strField "transcript_path" dataV
  entry <- maybe "cli" id <$> lookupEnv "CLAUDE_CODE_ENTRYPOINT"
  -- the per-backend gate: a Python `return` here is a silent exit
  proceed <- if cursor
    then if event `notElem` ["", "beforeSubmitPrompt", "UserPromptSubmit"]
           then pure False
           else not <$> cursorHeadless
    else if grok
      then pure (not (any jTruthy [field "stopHookActive" dataV, field "subagentType" dataV])
                 && field "reason" dataV `elem` [JNull, JStr "", JStr "end_turn"])
      else pure (zcode || entry == "cli")
  when proceed $ do
    ok <- if grok
      then pure (not (null sid))
      else do
        prompt0 <- case field "prompt" dataV of
          JStr p -> pure p
          _ | jTruthy (field "transcript_path" dataV) ->
                maybe "" id <$> firstPromptFromTranscript transcript
          _ -> pure ""
        let prompt = strip prompt0
            slashCommand = "/" `isPrefixOf` prompt && ' ' `notElem` prompt
        pure (not (null sid) && length prompt >= minPromptChars && not slashCommand)
    when ok $ do
      -- the id becomes a filename: reject a path (Grok and Claude ids are uuids)
      let unsafe = '/' `elem` sid || '\\' `elem` sid || sid `elem` [".", ".."]
      unless unsafe $ do
        home <- homeDir
        let stateDir = home </> ".local/state/autorename"
            marker = stateDir </> (sid ++ ".nudged")
        already <- doesFileExist marker
        unless already $ do
          createDirectoryIfMissing True stateDir
          writeFile marker "1\n"
          skillDir <- skillDirOf
          dispatch backend sid transcript skillDir

realMain :: IO ()
realMain = do
  raw <- readStdin
  case parseJson raw of
    Right dataV@(JObj _) -> run dataV
    _ -> pure ()

main :: IO ()
main = do
  setUtf8
  _ <- tryAny (timeout deadlineMicro realMain)
  exitWith ExitSuccess
