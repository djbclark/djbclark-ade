-- | PreToolUse (Bash): deny a pytest / tox / nox / run_tests*.py / swift build|test|run / xcodebuild
-- command that is not run through bg. Port of claude/hooks/bg_test_gate.py (hs-curry).
--
-- Port notes: the Python patterns are written with Ade.HsCurry.Match, whose matchers return every
-- possible remainder, so backtracking agrees with Python's `re` for these shapes. Allowed without bg:
-- the help, version and collect-only flags, anything already starting with bg, and words inside quotes
-- or heredocs. Fails open on a parse error. A JSON document that is not an object exits 1, as the
-- Python AttributeError does (that code sits outside the try in the original).
module Main (main) where

import Ade.HsCurry.Hook
import Ade.HsCurry.Match
import Ade.Json (Value (..))
import Data.Char (isDigit, isSpace)
import Data.List (isPrefixOf)
import System.Exit (ExitCode (..), exitSuccess, exitWith)
import System.IO (hPutStrLn, stderr)

bgCmd :: String
bgCmd = "~/ops/site-private/bin/bg"

notSpace :: Char -> Bool
notSpace = not . isSpace

-- | `-\S+\s+` (python prefixes).
dashArg :: RM
dashArg = seqM [lit "-", runs notSpace 1, runs isSpace 1]

-- | `--?\S+\s+` (uv prefixes).
dashArgUv :: RM
dashArgUv = seqM [lit "-", optM (lit "-"), runs notSpace 1, runs isSpace 1]

-- | `\w+=\S*\s+`: one VAR=value prefix.
varPrefix :: RM
varPrefix = seqM [runs isWordChar 1, lit "=", runs notSpace 0, runs isSpace 1]

-- | TEST_WORD: the test runner the command names.
testWord :: RM
testWord =
  altM
    [ lit "pytest"
    , lit "py.test"
    , lit "tox"
    , lit "nox"
    , seqM [lit "run_tests", runs isWordChar 0, lit ".py"]
    , lit "xcodebuild"
    , lit "swift-test"
    , lit "swift-build"
    , seqM
        [ lit "swift"
        , runs isSpace 1
        , starM (seqM [lit "-", runs notSpace 1, runs isSpace 1])
        , altM (map lit ["test", "build", "run"])
        ]
    ]

-- | SEGMENT: a test command at the start of a pipeline segment, behind VAR=x, env, uv, python -m or a path.
segmentRe :: RM
segmentRe =
  seqM
    [ altM [pureM, oneOfC ";&|(", lit "&&", lit "||"]
    , runs isSpace 0
    , starM varPrefix
    , optM (seqM [altM (map lit ["env", "time", "nice", "command", "exec"]), runs isSpace 1, starM varPrefix])
    , optM
        ( seqM
            [ altM [lit "uvx", lit "uv"]
            , runs isSpace 1
            , optM (seqM [lit "run", runs isSpace 1])
            , starM dashArgUv
            ]
        )
    , optM
        ( seqM
            [ runs notSpace 0
            , lit "python"
            , runs (\c -> isDigit c || c == '.') 0
            , runs isSpace 1
            , starM dashArg
            , optM (seqM [lit "-m", runs isSpace 1])
            ]
        )
    , optM (seqM [runs notSpace 0, lit "/"])
    , testWord
    , guardM (\r -> null r || isSpace (head r))
    ]

-- | BG_PREFIX: the segment already runs bg, by full path or bare.
bgPrefixRe :: RM
bgPrefixRe =
  seqM
    [ altM [pureM, seqM [oneOfC ";&|(", runs isSpace 0], runs isSpace 1]
    , optM (seqM [runs notSpace 0, lit "/"])
    , lit "bg"
    , optM (lit "b")
    , runs isSpace 1
    ]

-- | SAFE: a help, version or collect-only flag anywhere in the segment.
safeFlag :: String -> Bool
safeFlag s = or [any ok (flags (drop k s)) | k <- [0 .. length s], k == 0 || isSpace (s !! (k - 1))]
  where
    flags = altM (map lit ["--version", "-V", "--help", "-h", "--collect-only", "--co"])
    ok r = null r || isSpace (head r)

-- | The Python loop body: a non-empty segment that is a test command, not already under bg, not a help query.
offends :: String -> Bool
offends seg = not (null seg) && not (null (segmentRe seg)) && null (bgPrefixRe seg) && not (safeFlag seg)

-- | re.split(r"\n|;|&&|\|\||\|", plain).
splitSegs :: String -> [String]
splitSegs = go ""
  where
    go acc [] = [reverse acc]
    go acc s@(c : cs)
      | "&&" `isPrefixOf` s || "||" `isPrefixOf` s = reverse acc : go "" (drop 2 s)
      | c == '\n' || c == ';' || c == '|' = reverse acc : go "" cs
      | otherwise = go (c : acc) cs

reason :: String
reason =
  "Tests run through bg, not bare: " ++ bgCmd
    ++ " <your command> (bare `bg` is the shell job-control builtin, so use the full path). "
    ++ "bg caps parallelism, runs at utility QoS and takes one of two machine-wide test slots; "
    ++ "a bare run of a full suite sent the load average to 220 on 2026-10-08. "
    ++ "Run the changed files first (--lf -x); run the full suite only when asked."

denyOutput :: J
denyOutput =
  JObj
    [ ( "hookSpecificOutput"
      , JObj
          [ ("hookEventName", JStr "PreToolUse")
          , ("permissionDecision", JStr "deny")
          , ("permissionDecisionReason", JStr reason)
          ]
      )
    ]

main :: IO ()
main = do
  mv <- readHookInput
  off <- envSet "BG_GATE_OFF"
  case mv of
    Nothing -> exitSuccess
    Just (VObj kvs)
      | strField "tool_name" kvs /= "Bash" || off -> exitSuccess
      | otherwise -> case objOf (lookup "tool_input" kvs) of
          Nothing -> do
            hPutStrLn stderr "AttributeError: 'tool_input' has no attribute 'get'"
            exitWith (ExitFailure 1)
          Just tin -> do
            let cmd = orDefault "" (lookup "command" tin)
            if any offends (map pyStrip (splitSegs (stripLiterals cmd)))
              then emit denyOutput
              else exitSuccess
    Just _ -> do
      hPutStrLn stderr "AttributeError: hook input is not a JSON object (no attribute 'get')"
      exitWith (ExitFailure 1)
