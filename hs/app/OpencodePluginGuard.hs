-- | opencode-plugin-guard: keep the tool-managed OpenCode plugin (rtk) at the v2 module shape that
-- OpenCode 2 requires.
--
-- Why: rtk writes its plugin file from an embedded template that is still the v1 shape (a bare
-- exported function), which OpenCode 2 rejects at load. `rtk init -g --opencode` therefore silently
-- reverts a working plugin. The canonical copy is the patched file; this guard restores it only when
-- the v2 shape is missing, or migrates the exact known unsafe RTK shim.
--
--   opencode-plugin-guard --check   report only, change nothing
--   opencode-plugin-guard           restore what is missing (default)
--
-- Idempotent and non-destructive: a live file that already has the v2 shape and differs from the
-- canonical copy is left alone. Unknown RTK copies are flagged for review.
--
-- Exit codes: 0 ok / nothing to do; 1 something was restored or needs attention.
--
-- Environment: OPENCODE_PLUGIN_GUARD_CANONICAL, OPENCODE_CONFIG_DIR, HOME.
-- Port notes: the SHA-256 checks run `sha256sum` (an argv call, no shell). The v2 shape and version
-- checks are substring and whole-word matches standing in for the original grep -E patterns.
module Main (main) where

import Control.Exception (IOException, try)
import qualified Data.ByteString as B
import qualified Data.ByteString.Char8 as BC
import Data.Char (isAlphaNum, isDigit)
import Data.IORef (IORef, modifyIORef, newIORef, readIORef)
import Data.List (isPrefixOf, tails)
import Data.Time (defaultTimeLocale, formatTime, getCurrentTime)
import System.Directory
  (canonicalizePath, createDirectoryIfMissing, doesDirectoryExist, doesFileExist, getHomeDirectory, pathIsSymbolicLink)
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (takeDirectory, takeFileName, (</>))
import System.Posix.Files (rename, setFileMode)
import System.Posix.Process (getProcessID)
import System.Process (readProcessWithExitCode)

-- | SHA-256 of the former managed RTK shim, which is never restored or treated as safe.
knownUnsafeSha :: String
knownUnsafeSha = "8e46510ecdc95d4268838e435d33752d179675a6005b8de2483c7355b5d7da44"

data Ctx = Ctx
  { cCheck :: Bool
  , cRc :: IORef Int
  , cState :: FilePath
  , cCanonDir :: FilePath
  }

main :: IO ()
main = do
  args <- getArgs
  home <- getHomeDirectory
  canonicalDir <- maybe (home </> "src" </> "djbclark-ade" </> "opencode-plugins") id
                    <$> lookupEnv "OPENCODE_PLUGIN_GUARD_CANONICAL"
  configDir <- maybe (home </> ".config" </> "opencode") id <$> lookupEnv "OPENCODE_CONFIG_DIR"
  let checkMode = take 1 args == ["--check"]
      liveDir = configDir </> "plugins"
      stateDir = home </> ".local" </> "state" </> "opencode-plugin-guard"
  createDirectoryIfMissing True stateDir
  rcRef <- newIORef 0
  stamp <- utcStamp
  putStrLn ("opencode-plugin-guard " ++ (if checkMode then "(check)" else "(enforce)") ++ " — " ++ stamp)
  let ctx = Ctx { cCheck = checkMode, cRc = rcRef, cState = stateDir, cCanonDir = canonicalDir }
  -- An old obsolescence sentinel is not evidence of permission safety; the managed file is always
  -- inspected, and `rtk hook opencode` is never run as a probe.
  handle ctx "rtk" (liveDir </> "rtk.ts") (canonicalDir </> "rtk.ts")
  rc <- readIORef rcRef
  exitWith (if rc == 0 then ExitSuccess else ExitFailure rc)

utcStamp :: IO String
utcStamp = formatTime defaultTimeLocale "%Y-%m-%dT%H:%M:%SZ" <$> getCurrentTime

flag :: Ctx -> IO ()
flag ctx = modifyIORef (cRc ctx) (const 1)

handle :: Ctx -> String -> FilePath -> FilePath -> IO ()
handle ctx name file canonical = do
  canonExists <- doesFileExist canonical
  unsafeCanon <- if name == "rtk" && canonExists then isKnownUnsafe canonical else pure False
  dangling <- isDangling file
  present <- entryPresent file
  regular <- doesFileExist file
  if not canonExists
    then putStrLn ("  " ++ name ++ ": no canonical copy at " ++ canonical ++ " — skipping")
    else if unsafeCanon
      then do
        putStrLn ("  rtk: canonical " ++ canonical ++ " is the known unsafe shim; refresh it; no write")
        flag ctx
      else if dangling
        then do
          putStrLn ("  " ++ name ++ ": dangling or cyclic plugin symlink preserved; review its target; no write")
          flag ctx
        else if present && not regular
          then do
            putStrLn ("  " ++ name ++ ": non-regular plugin entry preserved; review it; no write")
            flag ctx
          else inspect
  where
    inspect = do
      unsafeLive <- if name == "rtk" then isKnownUnsafe file else pure False
      v2 <- if unsafeLive then pure False else hasV2 file
      if unsafeLive
        then putStrLn "  rtk: known unsafe automatic rewrite shim; migrate to disabled entrypoints" >> restore
        else if v2
          then do
            same <- sameBytes file canonical
            if name == "rtk" && not same
              then putStrLn "  rtk: unknown v2 copy preserved; permission safety needs review" >> flag ctx
              else upstreamOrDrift
          else putStrLn ("  " ++ name ++ ": v2 shape MISSING in " ++ file) >> restore

    upstreamOrDrift = do
      same <- sameBytes file canonical
      if same
        then putStrLn ("  " ++ name ++ ": v2 present, identical to the canonical copy")
        else do
          putStrLn ("  " ++ name ++ ": v2 shape present but differs from the canonical copy")
          liveVer <- versionOf file
          canonVer <- versionOf canonical
          if not (null liveVer) && not (null canonVer) && liveVer /= canonVer
            then do
              putStrLn ("    WARNING: canonical drift — live says '" ++ liveVer ++ "', canonical '" ++ canonVer ++ "'.")
              putStrLn ("    Refresh " ++ cCanonDir ctx </> takeFileName canonical ++ " and re-run.")
              flag ctx
            else do
              putStrLn "    -> treating as upstream v2 (or a local edit); not touching it"
              stamp <- utcStamp
              appendFile (cState ctx </> ("upstream-v2-" ++ name)) (stamp ++ "\n")

    restore
      | cCheck ctx = putStrLn ("    would restore from " ++ canonical) >> flag ctx
      | otherwise = do
          real <- canonicalizePath file
          createDirectoryIfMissing True (takeDirectory real)
          pid <- getProcessID
          let tmp = real ++ ".new." ++ show pid
          B.readFile canonical >>= B.writeFile tmp
          setFileMode tmp 0o644
          rename tmp real
          sha <- take 12 <$> sha256 real
          putStrLn ("    restored " ++ takeFileName real ++ " from canonical (sha " ++ sha ++ ")")
          flag ctx

-- | `[ -L f ] && [ ! -e f ]`: a symlink whose target does not exist.
isDangling :: FilePath -> IO Bool
isDangling p = do
  l <- pathIsSymbolicLink' p
  if not l then pure False else not <$> doesFileExist p

pathIsSymbolicLink' :: FilePath -> IO Bool
pathIsSymbolicLink' p = do
  r <- try (pathIsSymbolicLink p) :: IO (Either IOException Bool)
  pure (either (const False) id r)

-- | `[ -e f ]` for a path, including a symlink or directory.
entryPresent :: FilePath -> IO Bool
entryPresent p = do
  f <- doesFileExist p
  d <- doesDirectoryExist p
  l <- pathIsSymbolicLink' p
  pure (f || d || l)

-- | `has_v2`: `export default {` then optional whitespace then `id:`, and a whole word `setup` or
-- `effect` anywhere in the file.
hasV2 :: FilePath -> IO Bool
hasV2 f = do
  e <- doesFileExist f
  if not e then pure False else do
    text <- readText f
    pure (defaultObjectWithId text && any (wholeWordIn text) ["setup", "effect"])

defaultObjectWithId :: String -> Bool
defaultObjectWithId t = any startsHere (tails t)
  where
    startsHere s = case stripPrefixS "export default {" s of
      Just rest -> "id:" `isPrefixOf` dropWhile (`elem` " \t\r\n") rest
      Nothing -> False

stripPrefixS :: String -> String -> Maybe String
stripPrefixS p s
  | p `isPrefixOf` s = Just (drop (length p) s)
  | otherwise = Nothing

-- | A whole-word occurrence of w: not preceded or followed by a letter, digit or underscore.
wholeWordIn :: String -> String -> Bool
wholeWordIn text w = any ok (zip (Nothing : map Just text) (tails text))
  where
    ok (prev, s) = w `isPrefixOf` s && maybe True (not . isWordChar) prev
                     && maybe True (not . isWordChar) (safeHead (drop (length w) s))
    safeHead [] = Nothing
    safeHead (c : _) = Just c
    isWordChar c = isAlphaNum c || c == '_'

-- | The first `opencode-integration-version: <digits and dots>` in the file, or "".
versionOf :: FilePath -> IO String
versionOf f = do
  e <- doesFileExist f
  if not e then pure "" else do
    text <- readText f
    let key = "opencode-integration-version: "
    pure $ case [drop (length key) s | s <- tails text, key `isPrefixOf` s] of
      (rest : _) -> key ++ takeWhile (\c -> isDigit c || c == '.') rest
      [] -> ""

sameBytes :: FilePath -> FilePath -> IO Bool
sameBytes a b = do
  x <- try (B.readFile a) :: IO (Either IOException B.ByteString)
  y <- try (B.readFile b) :: IO (Either IOException B.ByteString)
  pure (either (const False) id ((==) <$> x <*> y))

isKnownUnsafe :: FilePath -> IO Bool
isKnownUnsafe f = (== knownUnsafeSha) <$> sha256 f

-- | The hex digest from `sha256sum`, or "" when it cannot run.
sha256 :: FilePath -> IO String
sha256 f = do
  ok <- doesFileExist f
  if not ok then pure "" else do
    r <- try (readProcessWithExitCode "sha256sum" [f] "") :: IO (Either IOException (ExitCode, String, String))
    pure $ case r of
      Right (ExitSuccess, out, _) -> takeWhile (/= ' ') out
      _ -> ""

readText :: FilePath -> IO String
readText p = BC.unpack <$> B.readFile p
