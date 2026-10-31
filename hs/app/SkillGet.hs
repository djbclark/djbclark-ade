-- | skill-get: load one agent skill on demand, for small-context models.
--
-- SCOPE: only for small-context models (Crush + Qwen on SIPB LLMs, 32k window). Models with real web search
-- and skill loaders (Claude, Codex, Grok, ...) should use those; this is the lean replacement, not a general tool.
--
--   skill-get --list [keyword ...]        compact catalogue (names only; with keywords: name + one-liner)
--   skill-get <name> [--offset N] [--max-chars N]
--   skill-get <name> --ref <relative/path>   a file under the skill's references/ or scripts/
--
-- A model whose context is small (Crush + Qwen on SIPB, 32k) cannot afford every skill's description in
-- every request. Keep the skills disabled in its harness and let it pull exactly one with this
-- command when the task needs it: the SKILL.md body (frontmatter stripped) is printed in pages of at
-- most --max-chars (default 7000), with the exact command for the next page.
-- Exit 0 ok, 1 not found, 2 usage.
--
-- Port of bin/skill-get (HEAD). The fuzzy "Close:" suggestions follow difflib.get_close_matches
-- (cutoff 0.5, five best, ties broken by name as difflib does). Roots come from SKILL_GET_ROOTS
-- (os.pathsep separated) or the four default roots under $HOME.
module Main (main) where

import Control.Exception (IOException, try)
import Control.Monad (filterM, forM, unless, when)
import Data.Char (isSpace, toLower)
import Data.List (isInfixOf, isPrefixOf, sort, sortBy)
import Data.Ord (Down (..), comparing)
import qualified Data.Map.Strict as M
import System.Directory
  ( canonicalizePath
  , doesDirectoryExist
  , doesFileExist
  , listDirectory
  )
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (makeRelative, takeFileName, (</>))
import System.IO (hPutStrLn, stderr)
import Text.Read (readMaybe)

-- | A skill directory: its name and the directory itself.
type Skills = M.Map String FilePath

defaultRoots :: FilePath -> [FilePath]
defaultRoots home =
  [ home </> "src/djbclark-ade/skills"
  , home </> ".claude/skills"
  , home </> ".agents/skills"
  , home </> "ops/site-private/skills"
  ]

splitOnColon :: String -> [String]
splitOnColon s = case break (== ':') s of
  (a, []) -> [a]
  (a, _ : r) -> a : splitOnColon r

-- | Every directory under a root that holds a SKILL.md; the first root to name a skill wins.
findSkills :: IO Skills
findSkills = do
  home <- fromMaybe' <$> lookupEnv "HOME"
  override <- lookupEnv "SKILL_GET_ROOTS"
  let roots = case override of
        Just v | not (null v) -> filter (not . null) (splitOnColon v)
        _ -> defaultRoots home
  pairs <- fmap concat . forM roots $ \root -> do
    isDir <- doesDirectoryExist root
    if not isDir
      then pure []
      else do
        names <- sort <$> listDirectory root
        fmap concat . forM [n | n <- names, not ("." `isPrefixOf` n)] $ \n -> do
          let d = root </> n
          ok <- doesFileExist (d </> "SKILL.md")
          pure [(n, d) | ok]
  pure (M.fromListWith (\_new old -> old) pairs)
  where
    fromMaybe' = maybe "" id

-- | (frontmatter, body): the block between a leading `---` line and the next `---` line.
splitFrontmatter :: String -> (String, String)
splitFrontmatter text = case lines' of
  (first : rest) | trimEnd first == "---" ->
    case break (\l -> trimEnd l == "---") rest of
      (front, _ : after) -> (unlines' front, unlines' after)
      _ -> ("", text)
  _ -> ("", text)
  where
    lines' = splitLines text
    unlines' ls = concatMap (++ "\n") ls
    trimEnd = reverse . dropWhile isSpace . reverse

-- | Lines keeping the newline-free text; a trailing empty piece is dropped.
splitLines :: String -> [String]
splitLines s = case break (== '\n') s of
  (a, []) -> [a | not (null a)]
  (a, _ : r) -> a : splitLines r

-- | The description: the `description:` value with its continuation lines, whitespace collapsed,
-- a leading YAML block marker removed, and surrounding quotes stripped.
description :: String -> String
description front = strip (stripBlock (collapse raw))
  where
    ls = splitLines front
    raw = case break (\l -> "description:" `isPrefixOf` l) ls of
      (_, l : more) ->
        let first = drop (length "description:") l
            cont = takeWhile (\x -> not (null x) && (head x == ' ' || head x == '\t')) more
         in unwords (first : cont)
      _ -> ""
    collapse = unwords . words
    stripBlock d = case d of
      (c : r) | c `elem` ">|" -> dropWhile isSpace (dropWhile (`elem` "-+") r)
      _ -> d
    strip = reverse . dropWhile (`elem` "\"'") . reverse . dropWhile (`elem` "\"'")

-- | difflib's matching-block ratio (no junk heuristics: skill names are short).
ratio :: String -> String -> Double
ratio a b
  | la + lb == 0 = 1
  | otherwise = 2 * fromIntegral (matches a b) / fromIntegral (la + lb)
  where
    la = length a
    lb = length b

matches :: String -> String -> Int
matches a b = go a b
  where
    go x y
      | null x || null y = 0
      | otherwise =
          let (i, j, k) = longest x y
           in if k == 0
                then 0
                else k + go (take i x) (take j y) + go (drop (i + k) x) (drop (j + k) y)

-- | Longest common run; ties go to the earliest start in the first string, then the second.
longest :: String -> String -> (Int, Int, Int)
longest x y = foldl pick (0, 0, 0) [(i, j, runAt i j) | i <- [0 .. length x - 1], j <- [0 .. length y - 1]]
  where
    runAt i j = length (takeWhile id (zipWith (==) (drop i x) (drop j y)))
    pick best@(_, _, bk) cand@(_, _, ck) = if ck > bk then cand else best

closeMatches :: String -> [String] -> [String]
closeMatches word names =
  take 5 (map snd (sortBy (comparing (\(s, n) -> (Down s, Down n))) scored))
  where
    scored = [(ratio word n, n) | n <- names, ratio word n >= 0.5]

cmdList :: Skills -> [String] -> IO ExitCode
cmdList skills words
  | null words = do
      let names = M.keys skills
      putStrLn (show (length names) ++ " skills. Names only; `skill-get --list <keyword>` shows what they do, "
        ++ "`skill-get <name>` loads one.")
      putStrLn (commaJoin names)
      pure ExitSuccess
  | otherwise = do
      rows <- fmap concat . forM (M.toList skills) $ \(name, d) -> do
        text <- readFileLenient (d </> "SKILL.md")
        let desc = description (fst (splitFrontmatter text))
            hay = map toLower (name ++ " " ++ desc)
        pure [name ++ ": " ++ take 120 desc | all (\w -> map toLower w `isInfixOf` hay) words]
      if null rows
        then do
          putStrLn ("no skill matches " ++ unwords words ++ "; try one keyword, or `skill-get --list`.")
          pure (ExitFailure 1)
        else do
          mapM_ putStrLn (take 25 rows)
          when (length rows > 25) $ putStrLn ("... " ++ show (length rows - 25) ++ " more; add a keyword.")
          pure ExitSuccess

commaJoin :: [String] -> String
commaJoin [] = ""
commaJoin [x] = x
commaJoin (x : xs) = x ++ ", " ++ commaJoin xs

readFileLenient :: FilePath -> IO String
readFileLenient p = do
  r <- try (readFile p) :: IO (Either IOException String)
  pure (either (const "") id r)

cmdGet :: Skills -> String -> Int -> Int -> Maybe String -> IO ExitCode
cmdGet skills name offset maxChars ref =
  case M.lookup name skills of
    Nothing -> do
      let near = closeMatches name (M.keys skills)
      putStrLn ("skill-get: no skill named " ++ show name ++ "." ++ (if null near then "" else " Close: " ++ commaJoin near ++ ".")
        ++ " `skill-get --list <keyword>` searches.")
      pure (ExitFailure 1)
    Just d -> do
      dReal <- canonicalizePath d
      case ref of
        Just r -> do
          f <- canonicalizePath (d </> r)
          isFile <- doesFileExist f
          if not (dReal `isPrefixOf` f) || not isFile
            then do
              putStrLn ("skill-get: " ++ show r ++ " is not a file inside " ++ d ++ ".")
              pure (ExitFailure 1)
            else do
              body <- readFileLenient f
              let again = "skill-get " ++ name ++ " --ref " ++ r
              emit ("FILE: " ++ f) body again
              pure ExitSuccess
        Nothing -> do
          text <- readFileLenient (d </> "SKILL.md")
          let body = dropWhile (== '\n') (snd (splitFrontmatter text))
              again = "skill-get " ++ name
              head' = "SKILL: " ++ name ++ "   DIR: " ++ dReal ++ "   (relative paths in it are under DIR)"
          emit head' body again
          when (offset == 0) $ do
            extra <- fmap (take 12 . concat) . forM ["references", "scripts"] $ \sub -> do
              let sd = dReal </> sub
              present <- doesDirectoryExist sd
              if not present
                then pure []
                else do
                  names <- sort <$> listDirectory sd
                  files <- filterM doesFileExist [sd </> n | n <- names]
                  pure (map (makeRelative dReal) files)
            unless (null extra) $
              putStrLn ("\nMORE FILES (read one only if needed): " ++ commaJoin extra ++ "  -> " ++ again ++ " --ref <path>")
          pure ExitSuccess
  where
    emit hd body again = do
      let chunk = take maxChars (drop offset body)
          end = offset + length chunk
      putStrLn hd
      putStrLn ""
      putStrLn (reverse (dropWhile isSpace (reverse chunk)))
      when (end < length body) $
        putStrLn ("\nTRUNCATED: " ++ show (length body - end) ++ " more characters. Next page: " ++ again
          ++ " --offset " ++ show end)

usageError :: String -> IO a
usageError msg = do
  hPutStrLn stderr "usage: skill-get [-h] [--list] [--offset OFFSET] [--max-chars MAX_CHARS] [--ref REF] [name ...]"
  hPutStrLn stderr ("skill-get: error: " ++ msg)
  exitWith (ExitFailure 2)

main :: IO ()
main = do
  args <- getArgs
  let (listFlag, rest) = (any (== "--list") args, filter (/= "--list") args)
  (names, offset, maxChars, ref) <- parseOpts rest
  skills <- findSkills
  code <-
    if listFlag
      then cmdList skills names
      else case names of
        [n] -> cmdGet skills (dropWhile (== '/') n) (max 0 offset) (max 500 maxChars) ref
        _ -> usageError "give exactly one skill name, or --list [keyword]"
  exitWith code
  where
    parseOpts = go ([], 0, 7000, Nothing)
    go (ns, o, m, r) xs = case xs of
      [] -> pure (reverse ns, o, m, r)
      ("--offset" : v : more) -> case readMaybe v of
        Just n -> go (ns, n, m, r) more
        Nothing -> usageError ("argument --offset: invalid int value: " ++ show v)
      ("--max-chars" : v : more) -> case readMaybe v of
        Just n -> go (ns, o, n, r) more
        Nothing -> usageError ("argument --max-chars: invalid int value: " ++ show v)
      ("--ref" : v : more) -> go (ns, o, m, Just v) more
      (x : more) | "--" `isPrefixOf` x && x /= "--" -> usageError ("unrecognized arguments: " ++ x)
      (x : more) -> go (x : ns, o, m, r) more
