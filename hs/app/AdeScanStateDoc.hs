import Ade.JsonLite (Json (..), parseJson)
import Control.Exception (IOException, onException, try)
import Control.Monad (when)
import Data.Char (isControl, ord)
import Data.List (isPrefixOf)
import Numeric (showHex)
import System.Directory (canonicalizePath, doesDirectoryExist, doesFileExist, removeFile)
import System.Environment (getArgs)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (takeDirectory, takeExtension, takeFileName)
import System.IO (IOMode (..), hClose, hGetContents, hPutStr, hPutStrLn, hSetEncoding, openTempFile, stderr, utf8, withFile)
import System.Posix.Files (rename, setFileMode)
import System.Posix.Process (getProcessID)

usage :: String
usage = "usage: ade-scan-state-doc SCAN.json OUT.md [--force]"

main :: IO ()
main = do
  argv <- getArgs
  let force = "--force" `elem` argv
      args = filter (/= "--force") argv
  case args of
    [src, out] -> run src out force
    _ -> failWith 1 (usage ++ "\n(ade-scan-state-doc: see the Python tool for the full help)")

run :: FilePath -> FilePath -> Bool -> IO ()
run src out force = do
  checkPaths src out force
  r <- try (readUtf8 src) :: IO (Either IOException String)
  case r of
    Left e -> failWith 1 ("ade-scan-state-doc: cannot read " ++ src ++ ": " ++ show e)
    Right text -> case parseJson text of
      Left e -> failWith 1 ("ade-scan-state-doc: " ++ src ++ " is not valid JSON: " ++ e)
      Right _scan ->
        failWith 2 "ade-scan-state-doc: render is not ported in this build; use the Python tool. Nothing was written."

-- | Refuse an OUT that would destroy the input, a non-markdown file or an existing file.
checkPaths :: FilePath -> FilePath -> Bool -> IO ()
checkPaths src out force = do
  srcAbs <- canonicalizePath src
  outAbs <- canonicalizePath out
  when (outAbs == srcAbs) $ failWith 1 ("refusing: OUT is the input " ++ src)
  when (takeExtension out /= ".md") $ failWith 1 ("refusing: OUT " ++ out ++ " does not end in .md")
  isDir <- doesDirectoryExist out
  when isDir $ failWith 1 ("refusing: OUT " ++ out ++ " is a directory")
  exists <- doesFileExist out
  when (exists && not force) $ failWith 1 ("refusing: " ++ out ++ " exists (--force replaces it)")

failWith :: Int -> String -> IO a
failWith code' msg = hPutStrLn stderr msg >> exitWith (if code' == 0 then ExitSuccess else ExitFailure code')

readUtf8 :: FilePath -> IO String
readUtf8 p = withFile p ReadMode $ \h -> do
  hSetEncoding h utf8
  s <- hGetContents h
  length s `seq` pure s

-- ---------------------------------------------------------------------------------------------
-- Escaping and display helpers (the same contract as the Python originals).

-- | One markdown table cell. Outside a code span `&`, `<`, `>` are HTML-escaped and backticks
-- backslash-escaped; `|` is always escaped; control characters are shown as text.
esc :: Bool -> String -> String
esc inCode value = visible (concatMap cellChar (pipeEsc value))
  where
    cellChar c
      | inCode = [c]
      | c == '&' = "&amp;"
      | c == '<' = "&lt;"
      | c == '>' = "&gt;"
      | c == '`' = "\\`"
      | otherwise = [c]
    pipeEsc = concatMap (\c -> if c == '|' then "\\|" else [c])

-- | A value shown, never pasted: control characters as backslash-n, -r, -t or -xNN text.
visible :: String -> String
visible = concatMap f
  where
    f '\n' = "\\n"
    f '\r' = "\\r"
    f '\t' = "\\t"
    f c | isControl c = "\\x" ++ hex2 (ord c)
        | otherwise = [c]
    hex2 n = let h = showHex n "" in if length h < 2 then '0' : h else h

-- | A code span: the format's `|` escaped, values escaped for a code span, fenced with one more
-- backtick than the longest run in the result. A control character in a value is refused.
code :: String -> [String] -> Either String String
code fmt values
  | any (any isControl) values = Left "control character in a code span value"
  | otherwise = Right (if null runs then "`" ++ text ++ "`" else fence ++ " " ++ text ++ " " ++ fence)
  where
    text = pipeEsc fmt `fill` map (esc True) values
    pipeEsc = concatMap (\c -> if c == '|' then "\\|" else [c])
    runs = backtickRuns text
    fence = replicate (maximum (map length runs) + 1) '`'
    fill s vs = go s vs
      where
        go ('{' : '}' : rest) (v : vrest) = v ++ go rest vrest
        go (c : rest) vs' = c : go rest vs'
        go [] _ = []
    backtickRuns s = case dropWhile (/= '`') s of
      [] -> []
      rest -> let (r, more) = span (== '`') rest in r : backtickRuns more

-- | `shlex.quote`: a plain word stays bare, anything else is single-quoted.
shquote :: String -> String
shquote v
  | not (null v) && all safe v = v
  | otherwise = "'" ++ concatMap (\c -> if c == '\'' then "'\"'\"'" else [c]) v ++ "'"
  where safe c = c `elem` (['a' .. 'z'] ++ ['A' .. 'Z'] ++ ['0' .. '9'] ++ "@%+=:,./-_")

-- | Human-readable size in the Python original's units (B, K, M, G), one decimal from K upward.
human :: Double -> String
human n = go n ["B", "K", "M", "G"]
  where
    go v [u] = fmt1 v u
    go v (u : us)
      | v < 1024 = fmt1 v u
      | otherwise = go (v / 1024) us
    go v [] = show v
    fmt1 v "B" = show (round v :: Integer) ++ "B"
    fmt1 v u = showFixed1 v ++ u
    showFixed1 v = let t = round (v * 10) :: Integer
                       (q, r) = t `divMod` 10
                   in show q ++ "." ++ show r

-- | A scan count as an int: a skipped or incomplete record's null is 0.
num :: Json -> Integer
num (JNum n) | all (`elem` "0123456789") n, not (null n) = read n
num _ = 0

-- | The directory below DEST that holds one checkout's captures, from its full path.
checkoutDir :: FilePath -> FilePath -> String
checkoutDir home p
  | p == home = "checkouts/home"
  | (home ++ "/") `isPrefixOf` p = "checkouts/home/" ++ drop (length home + 1) p
  | otherwise = "checkouts/abs/" ++ dropWhile (== '/') p

-- | Temp file beside OUT, then rename: OUT is whole before and whole after. The mode is 0644.
writeAtomic :: FilePath -> String -> IO ()
writeAtomic out text = do
  pid <- getProcessID
  (tmp, h) <- openTempFile (takeDirectory out) ("." ++ takeFileName out ++ "." ++ show pid ++ ".tmp")
  (do hSetEncoding h utf8
      hPutStr h text
      hClose h
      setFileMode tmp 0o644
      rename tmp out) `onException` removeFile tmp
