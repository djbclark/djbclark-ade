-- | ade-template-check: check the agents/ config templates (Phase 0 item 4.4, 2026-10-20).
--
-- Usage: ade-template-check [--diff] [--root DIR] [TEMPLATE ...]
--
-- Exit 0 clean, 1 findings, 2 usage.
--
-- Scope of this port (boot packages only: there is no regex engine and no TOML, YAML or JSON parser
-- among them). Ported: argument handling, template discovery, the `{{ .field }}` and
-- `{{ secret "NAME" }}` tag extraction, and the check that every field and secret used is documented
-- in agents/README.md. Not ported: the credential scan, the render and hostile round-trip checks, and
-- --diff, which exits 2 with a message in this build. The Python tool of the same name stays the
-- reference for those.
module Main (main) where

import Ade.Prelude (warn)
import Control.Monad (filterM, forM, unless, when)
import Data.Char (isAlpha, isAlphaNum, isSpace)
import Data.List (isPrefixOf, isSuffixOf, nub, sort, stripPrefix)
import System.Directory
  ( canonicalizePath
  , doesDirectoryExist
  , doesFileExist
  , listDirectory
  )
import System.Environment (getArgs)
import System.Exit (ExitCode (..), exitSuccess, exitWith)
import System.FilePath ((</>))

-- | Parsed command line.
data Opts = Opts
  { optDiff      :: Bool
  , optRoot      :: FilePath
  , optTemplates :: [FilePath]
  }

data Parsed = Run Opts | ShowHelp

-- | A `{{ ... }}` tag found in a template.
data Tag = FieldTag String | SecretTag String
  deriving (Eq, Show)

usage :: String
usage = "usage: ade-template-check [--diff] [--root DIR] [TEMPLATE ...]"

defaultRoot :: FilePath
defaultRoot = "."

-- | Command-line parsing: flags and TEMPLATE arguments in any order, `--` ends the flags.
parseArgs :: [String] -> Either String Parsed
parseArgs = go (Opts False defaultRoot []) False
  where
    go o _ [] = Right (Run o { optTemplates = reverse (optTemplates o) })
    go o True (a : as) = go o { optTemplates = a : optTemplates o } True as
    go _ _ ("-h" : _) = Right ShowHelp
    go _ _ ("--help" : _) = Right ShowHelp
    go o _ ("--" : as) = go o True as
    go o _ ("--diff" : as) = go o { optDiff = True } False as
    go o _ ("--root" : d : as) = go o { optRoot = d } False as
    go _ _ ["--root"] = Left "argument --root: expected one argument"
    go o _ (a : as)
      | Just d <- stripPrefix "--root=" a = go o { optRoot = d } False as
      | "-" `isPrefixOf` a && a /= "-" = Left ("unrecognized arguments: " ++ a)
      | otherwise = go o { optTemplates = a : optTemplates o } False as

-- | Every `{{ ... }}` tag in the text, in order. A `{{` that does not close, or whose contents are
-- neither `.field` nor `secret "NAME"`, is an error: the template's placeholders are a closed set.
tagsOf :: String -> Either String [Tag]
tagsOf [] = Right []
tagsOf s =
  case breakOn "{{" s of
    Nothing -> Right []
    Just (_, rest) ->
      case breakOn "}}" rest of
        Nothing -> Left "an unclosed {{ tag"
        Just (inner, after) -> do
          t <- parseTag (trim inner)
          (t :) <$> tagsOf after

-- | Split at the first occurrence of a literal needle; the needle is dropped from the second part.
breakOn :: String -> String -> Maybe (String, String)
breakOn needle = go []
  where
    go acc str
      | needle `isPrefixOf` str = Just (reverse acc, drop (length needle) str)
      | otherwise = case str of
          [] -> Nothing
          (c : cs) -> go (c : acc) cs

parseTag :: String -> Either String Tag
parseTag ('.' : name@(c : cs))
  | isIdentStart c && all isIdentChar cs = Right (FieldTag name)
parseTag inner
  | Just rest <- stripPrefix "secret" inner
  , (sp : _) <- rest
  , isSpace sp
  , Just quoted <- stripQuotes (trim rest)
  , not (null quoted)
  , all isIdentChar quoted = Right (SecretTag quoted)
parseTag _ = Left "a {{ ... }} tag other than `.field` or `secret \"NAME\"`"

isIdentStart :: Char -> Bool
isIdentStart c = isAlpha c || c == '_'

isIdentChar :: Char -> Bool
isIdentChar c = isAlphaNum c || c == '_'

stripQuotes :: String -> Maybe String
stripQuotes ('"' : rest)
  | not (null rest), last rest == '"' = Just (init rest)
stripQuotes _ = Nothing

trim :: String -> String
trim = dropWhile isSpace . reverse . dropWhile isSpace . reverse

-- | Field and secret names of a template, deduplicated and sorted.
fieldsUsed :: String -> Either String ([String], [String])
fieldsUsed text = do
  tags <- tagsOf text
  let fields = [n | FieldTag n <- tags]
      secrets = [n | SecretTag n <- tags]
  pure (sort (nub fields), sort (nub secrets))

-- | Names in the first column of agents/README.md table rows (`| `name` | ...`).
documentedFields :: String -> [String]
documentedFields = concatMap rowName . lines
  where
    rowName line =
      case dropWhile isSpace line of
        ('|' : rest) ->
          case dropWhile isSpace rest of
            ('`' : more) ->
              let (name, after) = span isIdentChar more
              in case after of
                   ('`' : tailPart)
                     | not (null name)
                     , isIdentStart (head name)
                     , ('|' : _) <- dropWhile isSpace tailPart -> [name]
                   _ -> []
            _ -> []
        _ -> []

-- | Templates under agents/<dir>/*.tmpl, sorted, as the Python glob `agents/*/*.tmpl` lists them.
discover :: FilePath -> IO [FilePath]
discover root = do
  let agents = root </> "agents"
  hasAgents <- doesDirectoryExist agents
  if not hasAgents
    then pure []
    else do
      subdirs <- sort <$> listDirectory agents
      dirs <- filterM (doesDirectoryExist . (agents </>)) subdirs
      files <- forM dirs $ \d -> do
        names <- sort <$> listDirectory (agents </> d)
        pure [agents </> d </> n | n <- names, ".tmpl" `isSuffixOf` n, take 1 n /= "."]
      pure (concat files)

-- | Label a path relative to the root when it sits under it, otherwise as given.
labelFor :: FilePath -> FilePath -> String
labelFor root p =
  case stripPrefix (root ++ "/") p of
    Just rel -> rel
    Nothing -> p

-- | Findings for one template, printed to stdout as the Python tool does.
checkOne :: FilePath -> FilePath -> IO Int
checkOne root path = do
  text <- readFile path
  let label = labelFor root path
  case fieldsUsed text of
    Left err -> do
      putStrLn (label ++ ": " ++ err)
      pure 1
    Right (fields, secrets) -> do
      doc <- readFileOr (root </> "agents" </> "README.md")
      let documented = documentedFields doc
          missingF = [f | f <- fields, f `notElem` documented]
          missingS = [s | s <- secrets, s `notElem` documented]
      mapM_ (\f -> putStrLn (label ++ ": field `" ++ f ++ "` is not in the agents/README.md table")) missingF
      mapM_ (\s -> putStrLn (label ++ ": secret `" ++ s ++ "` is not in the agents/README.md table")) missingS
      pure (length missingF + length missingS)

readFileOr :: FilePath -> IO String
readFileOr p = do
  ok <- doesFileExist p
  if ok then readFile p else pure ""

run :: Opts -> IO ()
run o = do
  when (optDiff o) $ do
    warn "ade-template-check: --diff is not available in this build"
    exitWith (ExitFailure 2)
  root <- canonicalizePath (optRoot o)
  paths <- if null (optTemplates o) then discover root else pure (optTemplates o)
  when (null paths) $ do
    warn ("ade-template-check: no templates under " ++ root ++ "/agents")
    exitWith (ExitFailure 2)
  forM_' paths $ \p -> do
    isFile <- doesFileExist p
    unless isFile $ do
      warn ("ade-template-check: " ++ p ++ ": not a file")
      exitWith (ExitFailure 2)
  total <- sum <$> mapM (\p -> canonicalizePath p >>= checkOne root) paths
  putStrLn ("ade-template-check: " ++ show (length paths) ++ " template(s), " ++ show total ++ " finding(s)")
  if total > 0 then exitWith (ExitFailure 1) else exitSuccess
  where
    forM_' xs f = mapM_ f xs

main :: IO ()
main = do
  argv <- getArgs
  case parseArgs argv of
    Left err -> do
      warn ("ade-template-check: " ++ err)
      warn usage
      exitWith (ExitFailure 2)
    Right ShowHelp -> do
      putStrLn usage
      exitSuccess
    Right (Run opts) -> run opts
