-- | crush-context-check: ask before Crush auto-loads project context files into its prompt.
--
-- SCOPE: only for Crush on small-context models (SIPB LLMs, 32k window). Crush v0.98.1 puts AGENTS.md,
-- CLAUDE.md, GEMINI.md, .cursorrules, .cursor/rules/ ... from the starting directory (plus
-- ~/.config/crush/CRUSH.md and ~/.config/AGENTS.md) into every request, with no way to ask first or opt
-- out (upstream issue charmbracelet/crush#4070). This runs from the `crush()` shell function before the
-- TUI starts: it lists what Crush will load, with sizes and a token estimate against the 32k window, and asks.
--
--   crush-context-check [--cwd DIR] [--window N] [--force-interactive]
--
-- Answer: [y]es start / [a]lways for this directory (until the files change) / [N]o quit.
-- Exit 0 = start Crush, 1 = declined, 2 = usage. Silent when nothing would load, when stdin is not a
-- terminal, or when CRUSH_CONTEXT_OK=1. Crush follows symlinks, so a `CLAUDE.md -> AGENTS.md` pair is
-- sent twice (#4018); shown as such.
--
-- Port of bin/crush-context-check (HEAD). The approval file and its signature (SHA-256 over the
-- directory and each file's name, size and mtime_ns) keep the Python format, so an answer given
-- under either build is honoured by the other.
module Main (main) where

import Control.Exception (IOException, try)
import Control.Monad (filterM, forM, unless)
import Data.Char (isSpace, toLower)
import Data.List (intercalate, isPrefixOf, isSuffixOf, sort)
import Data.Maybe (fromMaybe)
import Data.Time.Clock (UTCTime)
import Data.Time.Clock.POSIX (utcTimeToPOSIXSeconds)
import System.Directory
  ( canonicalizePath
  , createDirectoryIfMissing
  , doesDirectoryExist
  , doesFileExist
  , getFileSize
  , getHomeDirectory
  , getModificationTime
  , listDirectory

  )
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (makeRelative, takeDirectory, (</>))
import System.IO (hFlush, hIsTerminalDevice, hPutStr, hPutStrLn, stderr, stdin, stdout)
import Text.Read (readMaybe)
import Ade.Sha256 (sha256Hex)

-- | crush v0.98.1 internal/config/config.go defaultContextPaths (the list is only ever appended to).
defaults :: [FilePath]
defaults =
  [ ".github/copilot-instructions.md", ".cursorrules", ".cursor/rules/", "CLAUDE.md", "CLAUDE.local.md"
  , "GEMINI.md", "gemini.md", "crush.md", "crush.local.md", "Crush.md", "Crush.local.md", "CRUSH.md"
  , "CRUSH.local.md", "AGENTS.md", "agents.md", "Agents.md"
  ]

charsPerToken :: Double
charsPerToken = 2.7 -- measured 2026-10-14: 45,367 chars = 16,762 tokens through Qwen3.6 on SIPB

baseTokens :: Integer
baseTokens = 13000 -- Crush's own prompt with trimmed tools and no skills (measured)

summarizeAt :: Double
summarizeAt = 0.8 -- Crush summarizes when less than 20% of a small window remains

data Row = Row
  { rPath :: FilePath
  , rShown :: String
  , rSize :: Integer
  , rNote :: String
  }

envNonEmpty :: String -> IO (Maybe String)
envNonEmpty k = do
  m <- lookupEnv k
  pure $ case m of
    Just v | not (null v) -> Just v
    _ -> Nothing

okFile :: IO FilePath
okFile = do
  o <- envNonEmpty "CRUSH_CONTEXT_OK_FILE"
  case o of
    Just p -> pure p
    Nothing -> (\h -> h </> ".config/crush/context-ok.txt") <$> getHomeDirectory

globalPaths :: IO [FilePath]
globalPaths = do
  c <- envNonEmpty "CRUSH_GLOBAL_CONFIG"
  home <- getHomeDirectory
  let cdir = fromMaybe (home </> ".config/crush") c
  pure [cdir </> "CRUSH.md", takeDirectory cdir </> "AGENTS.md"]

-- | Files Crush reads from the starting directory, keyed on the lower-cased name as Crush does.
projectFiles :: FilePath -> IO [FilePath]
projectFiles cwd = go defaults [] []
  where
    go [] _ acc = pure (reverse acc)
    go (rel : rest) seen acc = do
      let key = map toLower rel
      if key `elem` seen
        then go rest seen acc
        else
          if "/" `isSuffixOf` rel
            then do
              isDir <- doesDirectoryExist (cwd </> rel)
              if isDir
                then do
                  fs <- rglob (cwd </> rel)
                  go rest (key : seen) (reverse (sort fs) ++ acc)
                else go rest seen acc
            else do
              isFile <- doesFileExist (cwd </> rel)
              if isFile
                then go rest (key : seen) ((cwd </> rel) : acc)
                else go rest seen acc

-- | Every regular file under a directory, recursively.
rglob :: FilePath -> IO [FilePath]
rglob dir = do
  names <- listDirectory dir
  fmap concat . forM (sort names) $ \n -> do
    let p = dir </> n
    isDir <- doesDirectoryExist p
    if isDir then rglob p else do
      isFile <- doesFileExist p
      pure [p | isFile]

-- | The files Crush would send, one row per time it sends them (a symlink to an earlier file is a repeat).
collect :: FilePath -> IO [Row]
collect cwd = do
  proj <- projectFiles cwd
  globals <- globalPaths >>= filterM doesFileExist
  home <- getHomeDirectory
  let loop _ [] = pure []
      loop seen (p : ps) = do
        real <- canonicalizePath p
        size <- getFileSize p
        let shown
              | cwd `isPrefixOf` p = makeRelative cwd p
              | otherwise = replaceHome home p
            note = case lookup real seen of
              Just s -> "same file as " ++ s ++ ": Crush sends it twice (#4018)"
              Nothing -> ""
            seen' = if real `elem` map fst seen then seen else seen ++ [(real, shown)]
        rest <- loop seen' ps
        pure (Row p shown size note : rest)
  loop [] (proj ++ globals)
  where
    replaceHome home p
      | home `isPrefixOf` p = "~" ++ drop (length home) p
      | otherwise = p

-- | The approval signature: "<cwd>\t<16 hex digits>" over name, size and mtime_ns of each row.
signature :: FilePath -> [Row] -> IO String
signature cwd rows = do
  parts <- forM rows $ \r -> do
    r' <- try (getModificationTime (rPath r)) :: IO (Either IOException UTCTime)
    pure $ case r' of
      Right t ->
        let ns = floor (toRational (utcTimeToPOSIXSeconds t) * 1000000000) :: Integer
         in rShown r ++ ":" ++ show (rSize r) ++ ":" ++ show ns
      Left _ -> rShown r
  pure (cwd ++ "\t" ++ take 16 (sha256Hex (cwd ++ concat parts)))

approved :: String -> IO Bool
approved sig = do
  p <- okFile
  r <- try (readFile p) :: IO (Either IOException String)
  pure $ case r of
    Right s -> sig `elem` lines s
    Left _ -> False

remember :: FilePath -> String -> IO ()
remember cwd sig = do
  p <- okFile
  r <- try $ do
    exists <- doesFileExist p
    old <- if exists then lines <$> readFile p else pure []
    length old `seq` pure ()
    let keep = [l | l <- old, not ((cwd ++ "\t") `isPrefixOf` l)]
    createDirectoryIfMissing True (takeDirectory p)
    writeFile p (unlines (keep ++ [sig]))
  case r of
    Left e -> hPutStrLn stderr ("crush-context-check: could not remember the answer (" ++ show (e :: IOException) ++ ")")
    Right () -> pure ()

commaNum :: Integer -> String
commaNum n = sign ++ intercalate "," (reverse (map reverse (chunks (reverse (show (abs n))))))
  where
    sign = if n < 0 then "-" else ""
    chunks [] = []
    chunks xs = let (a, b) = splitAt 3 xs in a : chunks b

-- | The dialog a user sees: file list, token estimate against the window, and the question.
main :: IO ()
main = do
  args <- getArgs
  cwdDefault <- getCurrentDir
  (cwdArg, windowArg, force) <- parseArgs args cwdDefault
  windowEnv <- envNonEmpty "CRUSH_CONTEXT_WINDOW"
  window <- case windowArg of
    Just w -> pure w
    Nothing -> case windowEnv of
      Nothing -> pure 32768
      Just e -> case readMaybe (trimSpace e) of
        Just w -> pure w
        Nothing -> do
          hPutStrLn stderr ("ValueError: invalid literal for int() with base 10: " ++ show e)
          exitWith (ExitFailure 1)
  cwd <- canonicalizePath cwdArg
  ctxOk <- lookupEnv "CRUSH_CONTEXT_OK"
  tty <- hIsTerminalDevice stdin
  if ctxOk == Just "1" || not (force || tty)
    then exitWith ExitSuccess
    else do
      rows <- collect cwd
      unless (null rows) $ do
        sig <- signature cwd rows
        ok <- approved sig
        unless ok $ ask cwd window rows sig
  where
    trimSpace = dropWhile isSpace . reverse . dropWhile isSpace . reverse

getCurrentDir :: IO FilePath
getCurrentDir = do
  pwd <- lookupEnv "PWD"
  maybe (canonicalizePath ".") pure pwd

parseArgs :: [String] -> FilePath -> IO (FilePath, Maybe Int, Bool)
parseArgs xs def = go (Nothing, Nothing, False) xs
  where
    go (c, w, f) ys = case ys of
      [] -> pure (fromMaybe def c, w, f)
      ("--cwd" : v : r) -> go (Just v, w, f) r
      ("--window" : v : r) -> case readMaybe v of
        Just n -> go (c, Just n, f) r
        Nothing -> usageError ("argument --window: invalid int value: " ++ show v)
      ("--force-interactive" : r) -> go (c, w, True) r
      (y : _) -> usageError ("unrecognized arguments: " ++ y)
    usageError :: String -> IO a
    usageError msg = do
      hPutStrLn stderr "usage: crush-context-check [-h] [--cwd CWD] [--window WINDOW] [--force-interactive]"
      hPutStrLn stderr ("crush-context-check: error: " ++ msg)
      exitWith (ExitFailure 2)

ask :: FilePath -> Int -> [Row] -> String -> IO ()
ask cwd window rows sig = do
  let totalBytes = sum (map rSize rows)
      tokens = round (fromIntegral totalBytes / charsPerToken) :: Integer
      limit = floor (fromIntegral window * summarizeAt) :: Integer
  putStrLn ("Crush will load these into its prompt (" ++ cwd ++ "):")
  mapM_ (\r ->
    putStrLn ("  " ++ rShown r ++ "  " ++ commaNum (rSize r) ++ " bytes (~"
      ++ commaNum (round (fromIntegral (rSize r) / charsPerToken)) ++ " tokens)"
      ++ (if null (rNote r) then "" else "  <- " ++ rNote r))) rows
  let flag = if baseTokens + tokens > limit
        then "  <- ABOVE the summarize trigger: every turn will end in a summary"
        else ""
  putStrLn ("  total ~" ++ commaNum tokens ++ " tokens + ~" ++ commaNum baseTokens ++ " base = ~"
    ++ commaNum (baseTokens + tokens) ++ " of " ++ commaNum limit
    ++ " (Crush summarizes above this, window " ++ commaNum (fromIntegral window) ++ ")" ++ flag)
  hPutStr stdout "Load them? [y]es / [a]lways for this directory / [N]o quit: "
  hFlush stdout
  r <- try getLine :: IO (Either IOException String)
  let ans = map toLower (trimSpace (either (const "") id r))
  case ans of
    _ | ans `elem` ["y", "yes"] -> exitWith ExitSuccess
    _ | ans `elem` ["a", "always"] -> remember cwd sig >> exitWith ExitSuccess
    _ -> do
      putStrLn "Not started. To skip them: start Crush from a subdirectory that has none of these files, or CRUSH_CONTEXT_OK=1 crush to skip this question."
      exitWith (ExitFailure 1)
  where
    trimSpace = dropWhile isSpace . reverse . dropWhile isSpace . reverse
