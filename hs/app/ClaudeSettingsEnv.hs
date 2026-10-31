-- | claude-settings-env: keep required and default `env` keys in ~/.claude/settings.json (2026-10-16).
--
-- graft's `Stop` hook runs `graft build`, which appends a `/graft/` block to the repo's tracked
-- `.gitignore` unless GRAFT_NO_GITIGNORE=1 is in the env block of settings.json. Claude Code applies
-- that block to every child process, so it is the one place that covers hooks, stdio MCP servers and
-- the Bash tool. Since 2026-10-23 it also adds CLAUDE_CODE_SUBAGENT_MODEL=sonnet as a default.
--
--   claude-settings-env            # add or correct REQUIRED keys, add absent DEFAULTS
--   claude-settings-env --check    # exit 1 if a REQUIRED key is missing or different,
--                                  # or a DEFAULTS key is absent
--
-- A REQUIRED key has one valid value and is corrected. A DEFAULTS key is added when absent; a value
-- the operator set on purpose is left alone and reported. Keys in neither table are never touched.
-- The file is replaced atomically on its realpath (rename(2) from a temp file beside it), keeping
-- its mode and key order.
--
-- Exit: 0 ok or set, 1 (--check) a key is missing or differs, 2 usage, 1 unreadable settings.
module Main (main) where

import Ade.JsonLite (Json (..), objLookup, objSet, parseJson, renderJson)
import Control.Exception (IOException, bracketOnError, try)
import Control.Monad (forM_)
import Data.List (intercalate)
import System.Directory (canonicalizePath, getHomeDirectory, removeFile)
import System.Environment (getArgs)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (takeDirectory, takeFileName, (</>))
import System.IO
  ( IOMode (..)
  , hClose
  , hGetContents
  , hPutStr
  , hPutStrLn
  , hSetEncoding
  , openTempFile
  , stderr
  , stdout
  , utf8
  , withFile
  )
import System.Posix.Files (fileMode, getFileStatus, rename, setFileMode)
import System.Posix.Process (getProcessID)

requiredKeys :: [(String, String)]
requiredKeys =
  -- graft: never write graft/ into the repo's tracked .gitignore (trailhq/Graft#582).
  [ ("GRAFT_NO_GITIGNORE", "1") ]

defaultKeys :: [(String, String)]
defaultKeys =
  -- Agent-tool sub-agents with no `model` default to Sonnet (djbclark, 2026-10-23).
  [ ("CLAUDE_CODE_SUBAGENT_MODEL", "sonnet") ]

usage :: String
usage = "usage: claude-settings-env [-h] [--check] [--settings SETTINGS]"

data Opts = Opts { optCheck :: Bool, optSettings :: Maybe FilePath }

-- | Nothing means help was asked for.
parseArgs :: [String] -> Either String (Maybe Opts)
parseArgs = go (Opts False Nothing)
  where
    go o [] = Right (Just o)
    go _ ("-h" : _) = Right Nothing
    go _ ("--help" : _) = Right Nothing
    go o ("--check" : as) = go o { optCheck = True } as
    go o ("--settings" : p : as) = go o { optSettings = Just p } as
    go _ ["--settings"] = Left "argument --settings: expected one argument"
    go o (a : as)
      | take 11 a == "--settings=" = go o { optSettings = Just (drop 11 a) } as
      | otherwise = Left ("unrecognized arguments: " ++ a)

main :: IO ()
main = do
  hSetEncoding stdout utf8
  hSetEncoding stderr utf8
  args <- getArgs
  case parseArgs args of
    Left err -> do
      hPutStrLn stderr (usage ++ "\nclaude-settings-env: error: " ++ err)
      exitWith (ExitFailure 2)
    Right Nothing -> putStrLn usage >> exitWith ExitSuccess
    Right (Just opts) -> do
      home <- getHomeDirectory
      let target = maybe (home </> ".claude" </> "settings.json") id (optSettings opts)
      rc <- apply target (optCheck opts)
      exitWith (if rc == 0 then ExitSuccess else ExitFailure rc)

-- | Python's str() for the scalar values a settings env block holds.
pyStr :: Json -> String
pyStr (JStr s) = s
pyStr (JNum n) = n
pyStr (JBool True) = "True"
pyStr (JBool False) = "False"
pyStr JNull = "None"
pyStr other = renderJson other

-- | `settings.get("env") or {}`: a missing or non-object env reads as empty.
envOf :: Json -> Json
envOf settings = case objLookup "env" settings of
  Just e@(JObj _) -> e
  _ -> JObj []

-- | Keys still to write: REQUIRED keys whose value differs, DEFAULTS keys that are absent.
missingKeys :: Json -> [(String, String)]
missingKeys settings =
  [ (k, v) | (k, v) <- requiredKeys, objLookup k env /= Just (JStr v) ]
    ++ [ (k, v) | (k, v) <- defaultKeys, objLookup k env == Nothing ]
  where env = envOf settings

apply :: FilePath -> Bool -> IO Int
apply path check = do
  real <- canonicalizePath path
  raw <- try (readUtf8 real) :: IO (Either IOException String)
  case raw of
    Left e -> do
      hPutStrLn stderr ("claude-settings-env: cannot read " ++ path ++ ": " ++ show e)
      pure 1
    Right text -> case parseJson text of
      Left e -> do
        hPutStrLn stderr ("claude-settings-env: " ++ path ++ " is not valid JSON: " ++ e)
        pure 1
      Right settings -> report path real settings check

report :: FilePath -> FilePath -> Json -> Bool -> IO Int
report shown real settings check = do
  let env = envOf settings
  forM_ defaultKeys $ \(k, v) -> case objLookup k env of
    Just cur | cur /= JStr v ->
      putStrLn ("left alone in " ++ shown ++ ": " ++ k ++ "=" ++ pyStr cur ++ " (default " ++ v ++ ")")
    _ -> pure ()
  let todo = missingKeys settings
      pairs = intercalate ", " [k ++ "=" ++ v | (k, v) <- todo]
      names = intercalate ", " (map fst requiredKeys ++ map fst defaultKeys)
  if null todo
    then putStrLn ("ok: " ++ names ++ " already set in " ++ shown) >> pure 0
    else if check
      then putStrLn ("missing in " ++ shown ++ ": " ++ pairs) >> pure 1
      else do
        let merged = foldl (\e (k, v) -> objSet k (JStr v) e) env todo
        writeAtomic real (renderJson (objSet "env" merged settings) ++ "\n")
        putStrLn ("set in " ++ shown ++ ": " ++ pairs)
        pure 0

-- | Replace the file through a temp file beside it, keeping the mode.
writeAtomic :: FilePath -> String -> IO ()
writeAtomic real text = do
  st <- getFileStatus real
  pid <- getProcessID
  let base = takeFileName real ++ "." ++ show pid ++ "."
  bracketOnError (openTempFile (takeDirectory real) base)
    (\(tmp, h) -> hClose h >> removeFile tmp)
    (\(tmp, h) -> do
        hSetEncoding h utf8
        hPutStr h text
        hClose h
        setFileMode tmp (fileMode st)
        rename tmp real)

readUtf8 :: FilePath -> IO String
readUtf8 p = withFile p ReadMode $ \h -> do
  hSetEncoding h utf8
  s <- hGetContents h
  length s `seq` pure s
