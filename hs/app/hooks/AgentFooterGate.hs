-- | PreToolUse (Agent): give an Agent-tool sub-agent the acp-dispatch delivery footer when its prompt
-- lacks it. Port of claude/hooks/agent_footer_gate.py (hs-curry).
--
-- Port notes: the two `re` patterns become hand-written scanners (pathAt, labelledAt) because no
-- regex package is among the boot packages. The 15 s acp-dispatch timeout is System.Timeout. Every
-- failure fails open, as the original does; only the footer's own deny path denies.
module Main (main) where

import Ade.HsCurry.Hook
import Ade.HsCurry.Match (isWordChar, pyStrip)
import Ade.Json (Value (..), field)
import Control.Exception (IOException, SomeException, catch, try)
import Data.Char (isSpace, toLower)
import Data.List (dropWhileEnd, isInfixOf, isSuffixOf, nub)
import Data.Maybe (catMaybes, fromMaybe, listToMaybe)
import System.Directory (createDirectoryIfMissing, doesPathExist, getHomeDirectory)
import System.Environment (lookupEnv)
import System.Exit (ExitCode (..), exitSuccess)
import System.FilePath ((</>))
import System.Process (readProcessWithExitCode)
import System.Timeout (timeout)

markFooter :: String
markFooter = "Delivery contract"

exempt :: [String]
exempt = ["claude-code-guide", "statusline-setup"]

denyReason :: String
denyReason =
  "This sub-agent prompt has no delivery footer (~/CLAUDE.md rule 25) and the hook could not build one. Run "
    ++ "`~/src/djbclark-ade/bin/acp-dispatch footer --report <scratchpad>/<name>-report.md`, paste its "
    ++ "output (it starts with '## Delivery contract') at the end of the prompt, and launch again; then "
    ++ "read that report file, not the final message."

-- Pattern shapes -------------------------------------------------------------

pathChar :: Char -> Bool
pathChar c = isWordChar c || c `elem` ".@~+/-"

-- | `/[\w.@~+/-]+-report\.md\b` at the front of the text: the longest run ending in -report.md
-- that is followed by a word boundary, with the text after it.
pathAt :: String -> Maybe (String, String)
pathAt s@('/' : _) =
  listToMaybe
    [ (take j s, drop j s)
    | j <- [length run, length run - 1 .. 1]
    , length (take j s) >= 12
    , "-report.md" `isSuffixOf` take j s
    , boundary j
    ]
  where
    run = takeWhile pathChar s
    boundary j = case drop j s of
      (c : _) -> not (isWordChar c)
      [] -> True
pathAt _ = Nothing

-- | findall of REPORT_IN_PROMPT: every bare report path, scanning left to right without overlap.
barePaths :: String -> [String]
barePaths s = case pathAt s of
  Just (p, rest) -> p : barePaths rest
  Nothing -> case s of
    [] -> []
    (_ : cs) -> barePaths cs

-- | Case-insensitive prefix test, returning the remainder.
ci :: String -> String -> Maybe String
ci p s
  | map toLower (take (length p) s) == map toLower p = Just (drop (length p) s)
  | otherwise = Nothing

-- | `(?i)report(?: path| file)?\s*(?:is|:|=)\s*`?(/...-report\.md)\b` at the front of the text.
labelledAt :: String -> Maybe (String, String)
labelledAt s
  | map toLower (take 6 s) /= "report" = Nothing
  | otherwise = listToMaybe (catMaybes (map attempt options))
  where
    rest = drop 6 s
    options = catMaybes [ci " path" rest, ci " file" rest] ++ [rest]
    attempt r = do
      r2 <- listToMaybe (catMaybes [ci sep (dropWhile isSpace r) | sep <- ["is", ":", "="]])
      let r3 = dropWhile isSpace r2
      pathAt (case r3 of
        ('`' : t) -> t
        _ -> r3)

-- | findall of REPORT_LABELLED.
labelledPaths :: String -> [String]
labelledPaths s = case labelledAt s of
  Just (p, rest) -> p : labelledPaths rest
  Nothing -> case s of
    [] -> []
    (_ : cs) -> labelledPaths cs

-- | named_report(): the path the prompt itself gives, when it gives exactly one (or any labelled one).
namedPath :: String -> Maybe String
namedPath prompt
  | (p : _) <- labelledPaths prompt = Just p
  | [p] <- nub (barePaths prompt) = Just p
  | otherwise = Nothing

-- | slug(): lowercase, runs of non-alphanumerics to '-', trimmed, at most 40 characters.
slug :: String -> String
slug t = case dashTrim (take 40 (dashTrim (squash (map toLower t)))) of
  "" -> "subagent"
  r -> r
  where
    dashTrim = dropWhileEnd (== '-') . dropWhile (== '-')
    squash = go False
    go _ [] = []
    go inRun (c : cs)
      | alnum c = c : go False cs
      | inRun = go True cs
      | otherwise = '-' : go True cs
    alnum c = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')

-- IO ------------------------------------------------------------------------

envNonEmpty :: String -> IO (Maybe String)
envNonEmpty k = nonEmpty <$> lookupEnv k
  where
    nonEmpty m = case m of
      Just s | not (null s) -> Just s
      _ -> Nothing

-- | report_path(): the prompt's own report path (unless its .done marker exists), else a state path.
reportFor :: Value -> [(String, Value)] -> IO String
reportFor dat tin = do
  named <- case namedPath (orDefault "" (lookup "prompt" tin)) of
    Nothing -> return Nothing
    Just p -> do
      done <- doesPathExist (p ++ ".done")
      return (if done then Nothing else Just p)
  case named of
    Just p -> return p
    Nothing -> do
      let session = slug (orDefault "session" (field "session_id" dat))
          name = slug (orDefault (orDefault "" (lookup "description" tin)) (lookup "name" tin))
      home <- getHomeDirectory
      base <- fromMaybe (home </> ".local/state/agent-reports") <$> envNonEmpty "AGENT_FOOTER_REPORT_DIR"
      let dir = base </> session
      createDirectoryIfMissing True dir
      return (dir </> (name ++ "-report.md"))

acpPath :: IO FilePath
acpPath = do
  override <- envNonEmpty "AGENT_FOOTER_ACP_DISPATCH"
  home <- getHomeDirectory
  return (fromMaybe (home </> "src/djbclark-ade/bin/acp-dispatch") override)

-- | footer(): the stripped footer text when acp-dispatch exits 0 and prints the marker.
footerText :: FilePath -> FilePath -> IO (Maybe String)
footerText acp report = do
  r <-
    try (timeout (15 * 1000000) (readProcessWithExitCode acp ["footer", "--report", report] ""))
      :: IO (Either IOException (Maybe (ExitCode, String, String)))
  return $ case r of
    Right (Just (ExitSuccess, out, _))
      | markFooter `isInfixOf` pyStrip out -> Just (pyStrip out)
    _ -> Nothing

deny :: J
deny =
  JObj
    [ ( "hookSpecificOutput"
      , JObj
          [ ("hookEventName", JStr "PreToolUse")
          , ("permissionDecision", JStr "deny")
          , ("permissionDecisionReason", JStr denyReason)
          ]
      )
    ]

gate :: Value -> [(String, Value)] -> String -> IO ()
gate dat tin prompt = do
  rep <- try (reportFor dat tin) :: IO (Either IOException String)
  case rep of
    Left _ -> emit deny
    Right report -> do
      acp <- acpPath
      mtext <- footerText acp report
      case mtext of
        Nothing -> emit deny
        Just text -> do
          let newPrompt = dropWhileEnd isSpace prompt ++ "\n\n" ++ text ++ "\n"
              updated = JObj (setKey "prompt" (JStr newPrompt) (map (fmap fromValue) tin))
              ctx =
                "agent_footer_gate appended the delivery footer to this sub-agent's prompt. Its report is "
                  ++ report
                  ++ " (done marker "
                  ++ report
                  ++ ".done): read that file, not the final message."
          emit
            ( JObj
                [
                  ( "hookSpecificOutput"
                  , JObj
                      [ ("hookEventName", JStr "PreToolUse")
                      , ("updatedInput", updated)
                      , ("additionalContext", JStr ctx)
                      ]
                  )
                ]
            )

run :: IO ()
run = do
  mv <- readHookInput
  off <- envSet "AGENT_FOOTER_GATE_OFF"
  case mv of
    Just dat@(VObj kvs)
      | strField "tool_name" kvs `elem` ["Agent", "Task"], not off ->
          case objOf (lookup "tool_input" kvs) of
            Nothing -> return ()
            Just tin -> do
              let sub = orDefault "" (lookup "subagent_type" tin)
                  prompt = orDefault "" (lookup "prompt" tin)
              if sub `elem` exempt || markFooter `isInfixOf` prompt
                then return ()
                else gate dat tin prompt
    _ -> return ()

-- | A gate must never break the tool: any exception exits 0 with no output.
main :: IO ()
main = (run `catch` ignore) >> exitSuccess
  where
    ignore :: SomeException -> IO ()
    ignore _ = return ()
