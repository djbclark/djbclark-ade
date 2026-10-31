-- | skill-everywhere: make a shared skill visible to every agent TUI on this machine by symlinking it
-- into each TUI's user-level skills dir.
--
--     skill-everywhere --all                sync every public/private shared skill
--     skill-everywhere --check --all        verify every installed target; exit 1 for gaps
--     skill-everywhere <name>...            link (idempotent, collapses chains)
--     skill-everywhere --check <name>...    report per-TUI status, change nothing; ends with a "== end" line
--     skill-everywhere --remove <name>...   remove links this script would make
--     --dry-run (-n) with link or --remove: print the changes, make none
--     SKILL_EVERYWHERE_ONLY=grokbot,claude limits the run to those targets
--     SKILL_EVERYWHERE_NO_COPY=1 skips the copy target (grokbot)
--
-- Content lives in exactly one place: ~/src/djbclark-ade/skills/<name> (public, default) or
-- ~/ops/site-private/skills/<name> (private), and every TUI links directly at that path. Editing the
-- skill in its git repo updates it everywhere; never copy (copies drift).
--
-- Port of bin/skill-everywhere (HEAD). The same target table, states, messages, --check sentinel,
-- exit codes, the grokbot rendered copy (dereferenced files, banner after the second front-matter
-- rule, .skill-everywhere marker, unsafe-symlink refusal) and the Hermes plugin-reload nudge. Shell
-- helpers become direct filesystem calls: readlink is getSymbolicLinkTarget, realpath is
-- canonicalizePath, and the tree comparison is by file contents (diff -r).
module Main (main) where

import Control.Exception (IOException, try)
import Control.Monad (forM, forM_, unless, when)
import Data.Char (isAlphaNum, isSpace)
import Data.IORef (IORef, modifyIORef', newIORef, readIORef, writeIORef)
import Data.List (isPrefixOf, sort)
import Data.Maybe (fromMaybe)
import System.Directory
import System.Environment (getArgs, lookupEnv, setEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (takeDirectory, (</>))
import System.IO (hPutStrLn, stderr)
import System.Process (proc, readProcessWithExitCode, std_err, StdStream (..), createProcess, waitForProcess)

-- | binary | dir spec: "~/..." (link into dir), "via <dir>", "x <why>", or "copy <dir>".
targetTable :: [(String, String)]
targetTable =
  [ ("claude", "~/.claude/skills")
  , ("codex", "~/.agents/skills")
  , ("goose", "~/.agents/skills")
  , ("agy", "~/.gemini/antigravity-cli/skills")
  , ("copilot", "~/.copilot/skills")
  , ("opencode", "~/.config/opencode/skills")
  , ("qwen", "~/.qwen/skills")
  , ("devin", "~/.config/devin/skills")
  , ("cline", "~/.cline/skills")
  , ("hermes", "~/.local/share/skill-everywhere/skills")
  , ("cursor-agent", "via ~/.claude/skills")
  , ("grok", "~/.grok/skills")
  , ("muse", "via ~/.claude/skills")
  , ("zcode", "via ~/.agents/skills")
  , ("omp", "~/.omp/agent/skills")
  , ("grokbot", "copy ~/agent-data/workflows")
  ]

-- | The header block the original prints on a bare invocation (its lines 2 to 15).
usageHeader :: [String]
usageHeader =
  [ "Make a shared skill visible to every agent TUI on this machine by"
  , "symlinking it into each TUI's user-level skills dir."
  , "    skill-everywhere --all                sync every public/private shared skill"
  , "    skill-everywhere --check --all        verify every installed target; exit 1 for gaps"
  , "    skill-everywhere <name>...            link (idempotent, collapses chains)"
  , "    skill-everywhere --check <name>...    report per-TUI status, change nothing; ends with a \"== end\" line"
  , "    skill-everywhere --remove <name>...   remove links this script would make"
  , "    --dry-run (-n) with link or --remove: print the changes, make none"
  , "    SKILL_EVERYWHERE_ONLY=grokbot,claude limits the run to those targets"
  , "    SKILL_EVERYWHERE_NO_COPY=1 skips the copy target (grokbot): ade-update sets it for a non-canonical checkout, which"
  , "    is a report-only run, so such a run neither lists nor renders the Grok Bot copy"
  , "    The grokbot copy refuses a skill holding a symlink that is not a link to a regular file inside the skill (one that"
  , "    leaves the skill, dangles, or names a directory or special file): --check reports \"unsafe source symlink\"; link"
  , "    mode copies nothing, leaves any existing copy alone and exits 1"
  ]

-- | The state of one run: options, the current skill, and the exit status being built.
data Ctx = Ctx
  { cMode :: String
  , cDry :: Bool
  , cAll :: Bool
  , cNoCopy :: Bool
  , cOnly :: String
  , cHome :: FilePath
  , cRc :: IORef Int
  }

-- | printf '  %-13s %s': one line of the per-target report.
report :: String -> String -> IO ()
report bin msg = putStrLn ("  " ++ padR 13 bin ++ " " ++ msg)

padR :: Int -> String -> String
padR n s = s ++ replicate (n - length s) ' '

-- | act: print "would ..." in dry-run mode, otherwise run the change.
act :: Ctx -> String -> String -> IO () -> IO ()
act ctx bin msg change
  | cDry ctx = putStrLn ("  " ++ padR 13 bin ++ " would " ++ msg)
  | otherwise = change

failRc :: Ctx -> IO ()
failRc ctx = modifyIORef' (cRc ctx) (const 1)

expandHome :: FilePath -> FilePath -> FilePath
expandHome home p
  | "~/" `isPrefixOf` p = home </> drop 2 p
  | otherwise = p

-- | wanted: SKILL_EVERYWHERE_ONLY is empty or lists this target.
wanted :: Ctx -> String -> Bool
wanted ctx b = null (cOnly ctx) || b `elem` splitComma (cOnly ctx)
  where
    splitComma s = case break (== ',') s of
      (a, []) -> [a]
      (a, _ : r) -> a : splitComma r

isLink :: FilePath -> IO Bool
isLink = pathIsSymbolicLink

linkTarget :: FilePath -> IO String
linkTarget p = do
  r <- try (getSymbolicLinkTarget p) :: IO (Either IOException FilePath)
  pure (either (const "") id r)

-- | realpath, or Nothing when the path does not exist (grealpath -e).
realpathE :: FilePath -> IO (Maybe FilePath)
realpathE p = do
  ok <- doesPathExist p
  if ok then Just <$> canonicalizePath p else pure Nothing

-- | unsafe_links: symlinks under a skill that do not resolve to a regular file inside it.
unsafeLinks :: FilePath -> IO [FilePath]
unsafeLinks src = do
  r <- try (canonicalizePath src) :: IO (Either IOException FilePath)
  case r of
    Left _ -> pure [src]
    Right root -> do
      links <- symlinksUnder src
      fmap concat . forM links $ \l -> do
        t <- realpathE l
        case t of
          Nothing -> pure [l]
          Just tt -> do
            isFile <- doesFileExist tt
            pure [l | not ((root ++ "/") `isPrefixOf` tt && isFile)]

symlinksUnder :: FilePath -> IO [FilePath]
symlinksUnder dir = do
  names <- sort <$> listDirectory dir
  fmap concat . forM names $ \n -> do
    let p = dir </> n
    link <- isLink p
    if link
      then pure [p]
      else do
        isDir <- doesDirectoryExist p
        if isDir then symlinksUnder p else pure []

-- | Every regular file under a directory, as (path relative to base, contents), sorted.
treeFiles :: FilePath -> FilePath -> IO [(FilePath, String)]
treeFiles base dir = do
  names <- sort <$> listDirectory dir
  fmap concat . forM names $ \n -> do
    let p = dir </> n
    isDir <- doesDirectoryExist p
    if isDir
      then treeFiles base p
      else do
        c <- readFile p
        length c `seq` pure [(drop (length base + 1) p, c)]

dirsEqual :: FilePath -> FilePath -> IO Bool
dirsEqual a b = do
  ok <- doesDirectoryExist b
  if not ok
    then pure False
    else (==) <$> treeFiles a a <*> treeFiles b b

-- | Copy a tree, following symlinks (cp -rL).
copyTreeFollowing :: FilePath -> FilePath -> IO ()
copyTreeFollowing src dst = do
  createDirectoryIfMissing True dst
  names <- listDirectory src
  forM_ names $ \n -> do
    let p = src </> n
        q = dst </> n
    isDir <- doesDirectoryExist p
    if isDir then copyTreeFollowing p q else copyFile p q

pruneCaches :: FilePath -> IO ()
pruneCaches dir = do
  names <- listDirectory dir
  forM_ names $ \n -> do
    let p = dir </> n
    isDir <- doesDirectoryExist p
    when isDir $
      if n == "__pycache__" then removeDirectoryRecursive p else pruneCaches p

-- | The banner the grokbot copy carries after its front matter.
bannerText :: String -> String -> String
bannerText name note = joinLines (base ++ extra)
  where
    base =
      [ "> **Managed copy, do not edit here.** Rendered by djbclark-ade `bin/skill-everywhere` from"
      , "> [`skills/" ++ name ++ "`](https://github.com/djbclark/djbclark-ade/tree/master/skills/" ++ name ++ "); the next sync"
      , "> overwrites local edits. Written for the agent TUIs on djbclark's Mac: `~/src/<repo>` is"
      , "> `/home/box/src/<repo>` here when cloned, and Mac-only tools (launchd, herdr, Orca, Keychain,"
      , "> `hermes-ping`) are absent. Grok Bot's own rules win: sending, posting, pushing or merging still"
      , "> needs the operator's explicit approval."
      ]
    extra = if null note then [] else [">", "> " ++ note]
    joinLines = foldr1 (\a b -> a ++ "\n" ++ b)

-- | The gawk stage: after the first two `---` lines, a blank line and the banner.
insertBanner :: String -> String -> String
insertBanner banner = unlines . go (0 :: Int) . lines
  where
    go _ [] = []
    go n (l : ls)
      | n < 2 && isRule l =
          let n' = n + 1
           in l : (if n' == 2 then ["", banner] else []) ++ go n' ls
      | otherwise = l : go n ls
    isRule l = reverse (dropWhile isSpace (reverse l)) == "---"

-- | render_copy: a rendered copy of a skill, or False with nothing copied when a link is unsafe.
renderCopy :: String -> FilePath -> FilePath -> IO Bool
renderCopy name src out = do
  bad <- unsafeLinks src
  if not (null bad)
    then do
      hPutStrLn stderr ("error: unsafe source symlink, not copying " ++ src
        ++ " (a link must point at a regular file inside the skill): " ++ unwords bad)
      pure False
    else do
      copyTreeFollowing src out
      let gitDir = out </> ".git"
      hasGit <- doesDirectoryExist gitDir
      when hasGit $ removeDirectoryRecursive gitDir
      pruneCaches out
      writeFile (out </> ".skill-everywhere")
        ("source=djbclark-ade/skills/" ++ name ++ "\nmanaged-by=bin/skill-everywhere (grokbot target)\n")
      note <- fromMaybe "" <$> lookupEnv "SKILL_EVERYWHERE_GROKBOT_NOTE"
      text <- readFile (out </> "SKILL.md")
      length text `seq` writeFile (out </> "SKILL.md.new") (insertBanner (bannerText name note) text)
      renameFile (out </> "SKILL.md.new") (out </> "SKILL.md")
      pure True

-- | copy_target: the grokbot rendered copy under ~/agent-data/workflows (or another dir).
copyTarget :: Ctx -> String -> String -> String -> FilePath -> IO ()
copyTarget ctx bin name src dirSpec = do
  let dir = expandHome (cHome ctx) dirSpec
      mode = cMode ctx
      dest = dir </> ("ade-" ++ name)
  dirOk <- doesDirectoryExist dir
  if not dirOk
    then report bin ("not installed (no " ++ dir ++ ")")
    else do
      destExists <- doesPathExist dest
      destOurs <- doesFileExist (dest </> ".skill-everywhere")
      srcOk <- doesFileExist (src </> "SKILL.md")
      let initial
            | not destExists = "missing"
            | not destOurs = "real dir/file (not ours)"
            | not srcOk = "copy of a removed skill"
            | otherwise = "render"
          renders = initial == "missing" || initial == "render"
      state <-
        if mode /= "remove" && renders && srcOk
          then do
            bad <- unsafeLinks src
            if null bad
              then judge initial
              else do
                hPutStrLn stderr ("warning: " ++ name ++ ": " ++ src
                  ++ " is not copied, a symlink in it leaves the skill or is not a regular file: " ++ unwords bad)
                pure "unsafe source symlink"
          else judge initial
      case mode of
        "check" -> do
          report bin (state ++ " (" ++ dest ++ ")")
          when (cAll ctx && state /= "copied") $ failRc ctx
        "remove"
          | state == "missing" || "real" `isPrefixOf` state -> report bin (state ++ " (left alone)")
          | otherwise -> do
              act ctx bin ("remove " ++ dest) (removeDirectoryRecursive dest)
              unless (cDry ctx) $ report bin ("removed " ++ dest)
        _
          | state == "copied" -> report bin "already copied"
          | state == "missing" || state == "stale copy" -> do
              act ctx bin ("copy to " ++ dest ++ " (" ++ state ++ ")") $ do
                let stage = dir </> (".ade-" ++ name ++ ".new")
                stageExists <- doesPathExist stage
                when stageExists $ removeDirectoryRecursive stage
                ok <- renderCopy name src stage
                unless ok $ ioError (userError "render failed")
                destNow <- doesPathExist dest
                when destNow $ removeDirectoryRecursive dest
                renameDirectory stage dest
              unless (cDry ctx) $ report bin ("copied (was " ++ state ++ ")")
          | otherwise -> do
              report bin (state ++ "; left alone")
              failRc ctx
  where
    -- a render-state destination is compared with a fresh render, in a scratch dir
    judge "render" = do
      tmp <- getTemporaryDirectory
      let scratch = tmp </> ("skill-everywhere-" ++ name ++ "-check")
      exists <- doesPathExist scratch
      when exists $ removeDirectoryRecursive scratch
      createDirectoryIfMissing True scratch
      if cMode ctx == "remove"
        then pure "copied"
        else do
          ok <- renderCopy name src (scratch </> "x")
          same <- if ok then dirsEqual (scratch </> "x") dest else pure False
          removeDirectoryRecursive scratch
          pure (if same then "copied" else "stale copy")
    judge s = pure s
    dest = expandHome (cHome ctx) dirSpec </> ("ade-" ++ name)

-- | The Hermes plugin-reload nudge: find a python for the hermes launcher, then run the snippet with it.
hermesNudge :: IO ()
hermesNudge = do
  found <- findExecutable "hermes"
  case found of
    Nothing -> pure ()
    Just start -> do
      hpy <- findInterpreter start (3 :: Int)
      py <- maybe (findExecutable "python3") (pure . Just) hpy
      case py of
        Nothing -> pure ()
        Just p -> do
          home <- fromMaybe "" <$> lookupEnv "HOME"
          hh <- nonEmptyEnv "HERMES_HOME"
          setEnv "HERMES_HOME" (fromMaybe (home </> ".hermes") hh)
          r <- try (readProcessWithExitCode p ["-c", nudgeSnippet] "") :: IO (Either IOException (ExitCode, String, String))
          case r of
            Right (_, out, _) -> putStr out
            Left _ -> pure ()

-- | The first `#!` interpreter that is an executable python, following a launcher's `exec` line.
findInterpreter :: FilePath -> Int -> IO (Maybe FilePath)
findInterpreter file n
  | n <= 0 = pure Nothing
  | otherwise = do
      text <- readFileLenient file
      let line1 = takeWhile (/= '\n') text
          sb = takeWhile (not . isSpace) (if take 2 line1 == "#!" then drop 2 line1 else line1)
          nxt = firstExec text
      sbOk <- if isPython sb then isExec sb else pure False
      nxtOk <- case nxt of
        Just x | isPython x -> isExec x
        _ -> pure False
      case () of
        _ | sbOk -> pure (Just sb)
          | nxtOk -> pure nxt
          | otherwise -> case nxt of
              Just x -> do
                isF <- doesFileExist x
                if isF then findInterpreter x (n - 1) else pure Nothing
              Nothing -> pure Nothing
  where
    isPython p = "python" `isPrefixOf` reverse (takeWhile (/= '/') (reverse p))

isExec :: FilePath -> IO Bool
isExec p = do
  r <- try (getPermissions p) :: IO (Either IOException Permissions)
  pure (either (const False) executable r)

-- | The path named by the first `exec /path` in a launcher script.
firstExec :: String -> Maybe FilePath
firstExec text = case [x | t <- suffixes text, Just x <- [execPath t]] of
  (x : _) -> Just x
  [] -> Nothing
  where
    suffixes [] = [[]]
    suffixes xs@(_ : r) = xs : suffixes r
    execPath t = do
      rest <- stripPrefix' "exec" t
      let spaces = takeWhile (== ' ') rest
          path = drop (length spaces) rest
      if not (null spaces) && take 1 path == "/" && length path > 1
        then Just (takeWhile (\c -> c /= ' ' && c /= '"' && c /= '\'') path)
        else Nothing

stripPrefix' :: String -> String -> Maybe String
stripPrefix' pre s = if pre `isPrefixOf` s then Just (drop (length pre) s) else Nothing

nonEmptyEnv :: String -> IO (Maybe String)
nonEmptyEnv k = do
  m <- lookupEnv k
  pure $ case m of
    Just v | not (null v) -> Just v
    _ -> Nothing

readFileLenient :: FilePath -> IO String
readFileLenient p = do
  r <- try (readFile p) :: IO (Either IOException String)
  pure (either (const "") id r)

nudgeSnippet :: String
nudgeSnippet = unlines' ["import os, sys", "from pathlib import Path", "bin_dir = Path(sys.executable).parent", "root = bin_dir.parent.parent.resolve() if bin_dir.name == \".venv\" else bin_dir.parent.parent", "for r in (Path(os.environ[\"HERMES_HOME\"]) / \"hermes-agent\", root):  # a pinned tools python is not in the tree", "    if r.is_dir() and str(r) not in sys.path:", "        sys.path.insert(0, str(r))", "try:", "    from gateway.control_socket import reload_gateway_plugins", "except Exception:", "    raise SystemExit", "os.environ.setdefault(\"HERMES_HOME\", os.path.expanduser(\"~/.hermes\"))", "try:", "    r = reload_gateway_plugins(Path(os.environ[\"HERMES_HOME\"]), timeout=20)", "    print(\"hermes gateway: plugins %s\" % (\"reloaded\" if r and r.get(\"reloaded\") else \"not reloaded (no answer)\"))", "except Exception as e:", "    print(\"hermes gateway: plugin nudge skipped: %s\" % e)"]
  where
    unlines' = foldr1 (\a b -> a ++ "\n" ++ b)

main :: IO ()
main = do
  path <- fromMaybe "" <$> lookupEnv "PATH"
  setEnv "PATH" ("/opt/homebrew/bin:" ++ path)
  home <- fromMaybe "" <$> lookupEnv "HOME"
  argv <- getArgs
  (mode, dry, allFlag, rest) <- parseFlags argv ("link", False, False, [])
  adeRoot <- fromMaybe (home </> "src/djbclark-ade/skills") <$> nonEmpty "SKILL_EVERYWHERE_ADE"
  privRoot <- do
    p <- nonEmpty "SKILL_EVERYWHERE_PRIVATE"
    case p of
      Just v -> pure v
      Nothing -> do
        ops <- fromMaybe (home </> "ops") <$> nonEmpty "OPS_ROOT"
        pure (ops </> "site-private/skills")
  noCopy <- maybe False (not . null) <$> lookupEnv "SKILL_EVERYWHERE_NO_COPY"
  only <- fromMaybe "" <$> lookupEnv "SKILL_EVERYWHERE_ONLY"
  rcRef <- newIORef 0
  let ctx = Ctx mode dry allFlag noCopy only home rcRef
  names <-
    if allFlag
      then do
        unless (null rest || mode == "remove") $ do
          hPutStrLn stderr "error: --all accepts no names and cannot be used with --remove"
          exitWith (ExitFailure 2)
        found <- fmap concat . forM [adeRoot, privRoot] $ \root -> do
          exists <- doesDirectoryExist root
          if not exists
            then pure []
            else do
              entries <- sort <$> listDirectory root
              fmap concat . forM entries $ \e -> do
                ok <- doesFileExist (root </> e </> "SKILL.md")
                if not ok
                  then pure []
                  else do
                    unless (validName e) $ do
                      hPutStrLn stderr ("error: unsafe skill directory name: " ++ e)
                      exitWith (ExitFailure 2)
                    pure [e]
        let dedup = foldl (\acc n -> if n `elem` acc then acc else acc ++ [n]) [] found
        when (null dedup) $ do
          hPutStrLn stderr ("error: no readable shared SKILL.md files under " ++ adeRoot ++ " or " ++ privRoot)
          exitWith (ExitFailure 2)
        pure dedup
      else pure rest
  when (null names) $ do
    mapM_ (\l -> hPutStrLn stderr ("# " ++ l)) usageHeader
    exitWith (ExitFailure 2)
  -- Codex's shared instructions can point at a retired location while the skill links are healthy.
  codexHome <- fromMaybe (home </> ".codex") <$> nonEmpty "CODEX_HOME"
  let codexInstr = codexHome </> "AGENTS.md"
  when (mode == "check" && wanted ctx "codex") $ do
    isL <- isLink codexInstr
    exists <- doesPathExist codexInstr
    when (isL && not exists) $ do
      tgt <- linkTarget codexInstr
      hPutStrLn stderr ("warning: codex global instructions dangling: " ++ codexInstr ++ " -> " ++ tgt)
      failRc ctx
  forM_ names $ \name -> do
    let adeSrc = adeRoot </> name
        privSrc = privRoot </> name
    adeOk <- doesFileExist (adeSrc </> "SKILL.md")
    privOk <- doesFileExist (privSrc </> "SKILL.md")
    src <-
      if adeOk then pure (Just adeSrc)
      else if privOk then pure (Just privSrc)
      else if mode /= "remove"
        then do
          hPutStrLn stderr ("error: no SKILL.md under " ++ adeSrc ++ " or " ++ privSrc)
          failRc ctx
          pure Nothing
        else pure (Just adeSrc)
    case src of
      Nothing -> pure ()
      Just s -> do
        putStrLn ("== " ++ name)
        forM_ targetTable $ \(bin, spec) -> when (wanted ctx bin) $
          if "copy " `isPrefixOf` spec
            then unless noCopy $ copyTarget ctx bin name s (drop 5 spec)
            else do
              installed <- findExecutable bin
              case installed of
                Nothing -> report bin "not installed"
                Just _
                  | "via " `isPrefixOf` spec -> report bin spec
                  | otherwise -> linkTargetFor ctx bin name s (expandHome home spec)
  when (mode == "check") $ putStrLn "== end"
  hermesFound <- if wanted ctx "hermes" then findExecutable "hermes" else pure Nothing
  case hermesFound of
    Nothing -> pure ()
    Just _ -> do
      cfg <- readFileLenient (home </> ".hermes/config.yaml")
      unless ("skill-everywhere/skills" `isInfixOfS` cfg) $
        hPutStrLn stderr "warning: hermes no longer lists ~/.local/share/skill-everywhere/skills in skills.external_dirs; ask Hermes to re-add it"
  when (mode == "link" && not dry && isJust' hermesFound) $ hermesNudge
  code <- readIORef rcRef
  exitWith (if code == 0 then ExitSuccess else ExitFailure code)
  where
    nonEmpty k = nonEmptyEnv k
    isJust' = maybe False (const True)
    isInfixOfS needle hay = any (needle `isPrefixOf`) (suffixesS hay)
    suffixesS [] = [[]]
    suffixesS xs@(_ : r) = xs : suffixesS r

-- | One link target for a skill: check, link, remove, or report left alone.
linkTargetFor :: Ctx -> String -> String -> FilePath -> FilePath -> IO ()
linkTargetFor ctx bin name src dir = do
  let link = dir </> name
  linkedFlag <- isLink link
  state <-
    if linkedFlag
      then do
        tgt <- linkTarget link
        srcExists <- doesPathExist src
        linkExists <- doesPathExist link
        realLink <- realpathE link
        realSrc <- realpathE src
        pure $
          if tgt == src then "linked"
          else if srcExists && realLink == realSrc && realSrc /= Nothing then "chained via " ++ tgt
          else if not linkExists then "dangling -> " ++ tgt
          else "other link -> " ++ tgt
      else do
        exists <- doesPathExist link
        pure (if exists then "real dir/file (not ours)" else "missing")
  case cMode ctx of
    "check" -> do
      report bin state
      when (cAll ctx && state /= "linked") $ failRc ctx
    "remove"
      | state == "linked" -> do
          act ctx bin ("remove " ++ link) (removeFile link)
          unless (cDry ctx) $ report bin "removed"
      | otherwise -> report bin (state ++ " (left alone)")
    _
      | state == "missing" -> do
          act ctx bin ("link " ++ link) (createDirectoryIfMissing True dir >> createFileLink src link)
          unless (cDry ctx) $ report bin "linked"
      | state == "linked" -> report bin "already linked"
      | "chained " `isPrefixOf` state -> do
          act ctx bin ("relink " ++ link ++ " direct") (removeFile link >> createFileLink src link)
          unless (cDry ctx) $ report bin ("relinked direct (was " ++ state ++ ")")
      | "dangling " `isPrefixOf` state -> do
          act ctx bin ("relink " ++ link) (removeFile link >> createFileLink src link)
          unless (cDry ctx) $ report bin ("relinked (was " ++ state ++ ")")
      | otherwise -> do
          report bin (state ++ "; left alone")
          failRc ctx
validName :: String -> Bool
validName (c : cs) = c `elem` alnum && all (\x -> x `elem` alnum || x `elem` "._-") cs
  where
    alnum = ['A' .. 'Z'] ++ ['a' .. 'z'] ++ ['0' .. '9']
validName [] = False

-- | Command-line flags: --check, --remove, --dry-run/-n, --all; anything else starting with '-' is an error.
parseFlags :: [String] -> (String, Bool, Bool, [String]) -> IO (String, Bool, Bool, [String])
parseFlags args (m, d, a, rest) = case args of
  (x : more) | "-" `isPrefixOf` x -> case x of
    "--check" -> parseFlags more ("check", d, a, rest)
    "--remove" -> parseFlags more ("remove", d, a, rest)
    "--dry-run" -> parseFlags more (m, True, a, rest)
    "-n" -> parseFlags more (m, True, a, rest)
    "--all" -> parseFlags more (m, d, True, rest)
    _ -> do
      hPutStrLn stderr ("error: unknown option " ++ x)
      exitWith (ExitFailure 2)
  _ -> pure (m, d, a, args)
