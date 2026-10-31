-- | gnu-tools-check: find macOS shell code that calls a BSD tool where the GNU one is wanted.
--
-- Usage: gnu-tools-check [--exclude GLOB]... [PATH...]   (default PATH: .)
--
-- Scans shell code only (*.sh, *.bash, *.zsh, *.sh.j2, justfiles, *.just, files with a sh/bash/zsh
-- shebang, and in *.md the fenced bash/sh/shell/zsh/console blocks and inline code spans that hold a
-- pipeline) and reports, at command position:
--
--   1. a bare name of a tool whose BSD and GNU versions differ (sed, awk, grep, tr, date, stat, ...):
--      use the g-prefixed name;
--   2. a GNU-only long option (--foo) on a basic tool macOS provides as BSD (cp, ln, ls, rm, mkdir,
--      ...): use the g-prefixed name for that call.
--
-- Identical basics (cat, mkdir -p, rm -f, sleep N, ...) may stay bare, and so may the GNU-only tools
-- Homebrew links unprefixed (timeout, nproc, tac, shuf, numfmt).
--
-- Skip a file with "gnu-tools-check: portable" in its first 20 lines, an --exclude glob, or a
-- .gnu-tools-check-ignore file (one glob per line, relative to that root, # comments) at a scanned
-- root. Skip one line with "gnu-tools-check: ignore" on it. Single-quoted text, heredoc bodies and
-- double-quoted text (except $(...) inside it) are not scanned.
--
-- Exit 0 clean, 1 findings, 2 usage error.
--
-- Port notes: globs support * and ? only (no bracket classes). Command position is found by a
-- word scanner over the blanked code, not the original regular expressions.
module Main (main) where

import Control.Exception (IOException, try)
import Control.Monad (filterM, forM, forM_)
import qualified Data.ByteString.Char8 as BC
import Data.Char (isAlphaNum, isSpace)
import Data.List (isPrefixOf, isSuffixOf, isInfixOf, sort)
import System.Directory (doesDirectoryExist, doesFileExist, listDirectory, pathIsSymbolicLink, getCurrentDirectory)
import System.Environment (getArgs)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (takeExtension, takeFileName, (</>))
import System.IO (hPutStrLn, stderr)
import System.Process (readProcessWithExitCode)

-- | Tools whose BSD and GNU versions differ in ways that have bitten us.
differTools :: [String]
differTools = words "awk base64 cut date du find grep head mktemp readlink realpath sed seq sort split stat tail tar tee touch tr uniq wc xargs"

-- | macOS ships these as BSD; GNU long options on them fail there.
bsdBasics :: [String]
bsdBasics = words "cat chmod chown cp df env id install ln ls mkdir mv rm rmdir sleep uname"

defaultExcludes :: [String]
defaultExcludes =
  [ "*/.git/*", "*/node_modules/*", "*/graft/*", "*/vendor/*", "*/.venv/*", "*/termux/*", "*/android/*"
  , "*/.github/*", "*/.forgejo/*", "*/Dockerfile*", "*/gradlew", "*/handoffs/*", "*/reports/*", "*/MEMORY.md" ]

ignoreFile, portableMark, ignoreMark :: String
ignoreFile = ".gnu-tools-check-ignore"
portableMark = "gnu-tools-check: portable"
ignoreMark = "gnu-tools-check: ignore"

-- | One finding: file, line number, message.
type Finding = (FilePath, Int, String)

main :: IO ()
main = do
  args <- getArgs
  case parseArgs args ([], []) of
    Left msg -> hPutStrLn stderr ("usage: gnu-tools-check [--exclude GLOB]... [PATH...]\ngnu-tools-check: error: " ++ msg) >> exitWith (ExitFailure 2)
    Right (excl, paths) -> do
      let roots = if null paths then ["."] else paths
      results <- forM roots $ \raw -> do
        ok <- doesFileExist raw
        dirOk <- doesDirectoryExist raw
        if not (ok || dirOk)
          then hPutStrLn stderr ("gnu-tools-check: no such path: " ++ raw) >> pure Nothing
          else do
            ignores <- loadIgnore raw
            let globs = defaultExcludes ++ excl ++ ignores
            files <- iterFiles raw globs
            fs <- forM files $ \p -> scanFile globs p
            pure (Just (concat fs))
      if any (== Nothing) results
        then exitWith (ExitFailure 2)
        else do
          let findings = concat [f | Just f <- results]
          forM_ findings $ \(p, n, m) -> putStrLn (p ++ ":" ++ show n ++ ": " ++ m)
          exitWith (if null findings then ExitSuccess else ExitFailure 1)

parseArgs :: [String] -> ([String], [String]) -> Either String ([String], [String])
parseArgs [] (e, p) = Right (reverse e, reverse p)
parseArgs ("--" : rest) (e, p) = Right (reverse e, reverse p ++ rest)
parseArgs ("--exclude" : g : rest) (e, p) = parseArgs rest (g : e, p)
parseArgs ["--exclude"] _ = Left "argument --exclude: expected one argument"
parseArgs (a : rest) (e, p)
  | "--exclude=" `isPrefixOf` a = parseArgs rest (drop 10 a : e, p)
  | "-" `isPrefixOf` a && a /= "-" = Left ("unrecognized arguments: " ++ a)
  | otherwise = parseArgs rest (e, a : p)

-- | Glob match with * and ? (no bracket classes).
globMatch :: String -> String -> Bool
globMatch [] s = null s
globMatch ('*' : ps) s = any (globMatch ps) (suffixes s)
  where suffixes x = x : case x of { [] -> []; (_ : xs) -> suffixes xs }
globMatch ('?' : ps) (_ : s) = globMatch ps s
globMatch (p : ps) (c : s) = p == c && globMatch ps s
globMatch _ [] = False

excluded :: FilePath -> [String] -> Bool
excluded path globs = any (\g -> globMatch g path || globMatch g ('/' : path)) globs

loadIgnore :: FilePath -> IO [String]
loadIgnore raw = do
  isDir <- doesDirectoryExist raw
  let f = (if isDir then raw else parentOf raw) </> ignoreFile
  ok <- doesFileExist f
  if not ok then pure [] else do
    text <- readUtf8 f
    pure [ if "*" `isPrefixOf` l then l else dirOf f </> l
         | l0 <- lines text, let l = trim l0, not (null l), not ("#" `isPrefixOf` l) ]
  where
    parentOf p = let d = reverse (dropWhile (/= '/') (reverse p)) in if null d then "." else init d
    dirOf p = parentOf p

trim :: String -> String
trim = f . f where f = reverse . dropWhile isSpace

-- | The files under root: git's view when root is in a repository, else a directory walk.
iterFiles :: FilePath -> [String] -> IO [FilePath]
iterFiles root globs = do
  isFile <- doesFileExist root
  if isFile then pure [root] else do
    listed <- gitFiles root
    case listed of
      Just fs -> filterM (\p -> (\f -> f && not (excluded p globs)) <$> doesFileExist p) [root </> f | f <- fs]
      Nothing -> walk root
  where
    walk dir = do
      names <- sort <$> listDirectory dir
      fmap concat $ forM names $ \n -> do
        let p = dir </> n
        link <- pathIsSymbolicLink p
        isDir <- doesDirectoryExist p
        if link then pure []
        else if isDir
          then if excluded (p ++ "/") globs then pure [] else walk p
          else pure [p | not (excluded p globs)]

gitFiles :: FilePath -> IO (Maybe [FilePath])
gitFiles root = do
  r <- try (readProcessWithExitCode "git" ["-C", root, "ls-files", "-z", "-co", "--exclude-standard"] "")
         :: IO (Either IOException (ExitCode, String, String))
  pure $ case r of
    Right (ExitSuccess, out, _) -> Just (filter (not . null) (splitNul out))
    _ -> Nothing
  where
    splitNul s = case break (== '\0') s of
      (a, []) -> [a]
      (a, _ : rest) -> a : splitNul rest

-- | Whether a file is scanned as shell code (or, for Markdown, as a Markdown file).
isShellFile :: FilePath -> IO Bool
isShellFile p = do
  let name = takeFileName p
  if any (`isSuffixOf` name) [".sh", ".bash", ".zsh", ".sh.j2", ".just"] || name `elem` ["justfile", "Justfile"]
    then pure True
    else do
      r <- try (BC.readFile p) :: IO (Either IOException BC.ByteString)
      pure $ case r of
        Right bs -> shebangShell (BC.take 128 bs)
        Left _ -> False
  where
    shebangShell bs = case BC.lines bs of
      (l : _) -> "#!" `isPrefixOf` BC.unpack l && any (`isInfixOf` BC.unpack l) ["sh", "bash", "zsh"]
      _ -> False

scanFile :: [String] -> FilePath -> IO [Finding]
scanFile _ path = do
  let isMd = takeExtension path == ".md"
  shell <- if isMd then pure True else isShellFile path
  if not shell then pure [] else do
    r <- try (readUtf8 path) :: IO (Either IOException String)
    case r of
      Left _ -> pure []
      Right text ->
        let raw = lines text
            body = if isMd then markdownShell text else text
        in if any (portableMarkIn) (take 20 (if isMd then raw else raw))
             then pure []
             else pure [ (path, n, msg) | (n, msg) <- scanText raw body ]
  where
    portableMarkIn l = portableMark `isInfixOf` l

-- | Findings for one file: the raw lines (for ignore markers) and the blanked code text.
scanText :: [String] -> String -> [(Int, String)]
scanText raw code =
  [ (n, msg)
  | (n, line) <- zip [1 ..] (codeLines code)
  , not (null (trim line))
  , not (n <= length raw && ignoreMark `isInfixOf` (raw !! (n - 1)))
  , msg <- lineFindings line
  ]

-- | Messages for one line of blanked code.
lineFindings :: String -> [String]
lineFindings line =
  [ "bare " ++ t ++ " is BSD on macOS: use g" ++ t | t <- commandWords line, t `elem` differTools ]
  ++ [ t ++ " " ++ opt ++ " is GNU-only: use g" ++ t | (t, opt) <- basicLongOpts line ]

-- | First words of each command segment.
commandWords :: String -> [String]
commandWords line = [ w | seg <- segments line, (w : _) <- [skipPrefixes (words seg)] ]

skipPrefixes :: [String] -> [String]
skipPrefixes ws = case ws of
  (w : rest) | w `elem` prefixWords -> skipPrefixes rest
  _ -> ws

prefixWords :: [String]
prefixWords = ["then", "do", "else", "exec", "command", "xargs", "nohup", "sudo", "time", "!"]

-- | (tool, option) for a BSD basic tool called with a GNU-only long option before any `--`.
basicLongOpts :: String -> [(String, String)]
basicLongOpts line =
  [ (w, o) | seg <- segments line, (w : args) <- [skipPrefixes (words seg)], w `elem` bsdBasics
           , Just o <- [firstLong args] ]
  where
    firstLong [] = Nothing
    firstLong ("--" : _) = Nothing
    firstLong (a : as)
      | "--" `isPrefixOf` a && length a > 2 && isAlphaNum (a !! 2) && all (\c -> isAlphaNum c || c `elem` "-_=") a =
          Just (takeWhile (/= '=') a)
      | "-" `isPrefixOf` a = firstLong as
      | otherwise = Nothing

-- | Command segments: the text between separators (| ; & ( ) { } and backticks).
segments :: String -> [String]
segments s = case break (`elem` "|;&(){}`\n") s of
  (a, []) -> [a]
  (a, _ : rest) -> a : segments rest

-- | The code lines of a shell file with quoted text, comments and heredoc bodies blanked. Single
-- quotes blank everything inside; double quotes blank everything except $(...) and backticks.
codeLines :: String -> [String]
codeLines text = lines (blank ' ' text)
  where
    -- prev is the character before the current one; a '#' starts a comment only at a word start
    blank _ [] = []
    blank prev ('#' : r)
      | prev `elem` " \t\n;|&(" =
          let (c, rest) = break (== '\n') r in replicate (length c + 1) ' ' ++ blank '#' rest
    blank prev ('\'' : r) = ' ' : skipSq r
    blank prev ('"' : r) = ' ' : blankDq r
    blank _ ('\\' : c : r) = ' ' : ' ' : blank c r
    blank _ (c : r) = c : blank c r
    skipSq [] = []
    skipSq ('\'' : r) = ' ' : blank '\'' r
    skipSq (c : r) = (if c == '\n' then '\n' else ' ') : skipSq r
    blankDq [] = []
    blankDq ('"' : r) = ' ' : blank '"' r
    blankDq ('\\' : c : r) = ' ' : (if c == '\n' then '\n' else ' ') : blankDq r
    blankDq ('$' : '(' : r) = '$' : '(' : blank '(' r
    blankDq ('`' : r) = '`' : blank '`' r
    blankDq (c : r) = (if c == '\n' then '\n' else ' ') : blankDq r

-- | Shell code of a Markdown file: fenced shell blocks and inline pipeline spans, other lines blank.
markdownShell :: String -> String
markdownShell text = unlines (go (lines text) Nothing)
  where
    go [] _ = []
    go (l : ls) Nothing
      | ("```" `isPrefixOf` trim l || "~~~" `isPrefixOf` trim l) =
          let lang = trim (drop 3 (trim l))
              shell = takeWhile (not . isSpace) lang `elem` ["bash", "sh", "shell", "zsh", "console"]
          in if ignoreMark `isInfixOf` l then "" : go ls Nothing
             else "" : go ls (if shell then Just ("```", takeWhile (not . isSpace) lang == "console") else Just ("NOSHELL", False))
      | otherwise = inlineSpans l : go ls Nothing
    go (l : ls) (Just (fence, console))
      | fence /= "NOSHELL" && fence `isPrefixOf` trim l = "" : go ls Nothing
      | fence == "NOSHELL" && "```" `isPrefixOf` trim l = "" : go ls Nothing
      | console = (if "$ " `isPrefixOf` trim l || "% " `isPrefixOf` trim l then drop 2 (trim l) else "") : go ls (Just (fence, console))
      | fence == "NOSHELL" = "" : go ls (Just (fence, console))
      | otherwise = l : go ls (Just (fence, console))

-- | Inline code spans holding a pipeline, each prefixed with a dummy word.
inlineSpans :: String -> String
inlineSpans l = intercalateS " ; " [ "x " ++ s | s <- spans l, any (`elem` "|;&`") s || "$(" `isInfixOf` s ]
  where
    spans str = case break (== '`') str of
      (_, []) -> []
      (_, _ : rest) -> case break (== '`') rest of
        (inner, _ : more) | not (null inner) && '\n' `notElem` inner -> inner : spans more
        _ -> []
    intercalateS sep xs = foldr1' (\a b -> a ++ sep ++ b) xs
    foldr1' _ [] = ""
    foldr1' f xs = foldr1 f xs

readUtf8 :: FilePath -> IO String
readUtf8 p = BC.unpack <$> BC.readFile p
