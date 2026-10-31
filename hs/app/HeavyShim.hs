-- | heavy-shim: PATH shim for `swift` and `xcodebuild` (linked as ~/.local/bin/swift and
-- ~/.local/bin/xcodebuild, which come before /usr/bin on PATH).
--
-- Why (2026-10-13): an agy session ran a bare `swift test --filter X` in ~/src/CodexBar. SwiftPM
-- started one swift-frontend per core and, with a Gradle daemon, took the 16 GB Mac to load 180.
-- The Claude hook denies this, but agy, codex, cursor and the rest have no hooks; a shim on PATH
-- covers every TUI that runs the command by name.
--
-- What: `swift build|test|run` and any heavy `xcodebuild` re-exec through ~/ops/site-private/bin/bg,
-- which takes a machine-wide test slot. `swift package`, `--version`, `--help`, and xcodebuild
-- -version/-help/-list and friends go straight to /usr/bin. BG_SHIM=1 is set before calling bg so
-- the `swift` bg launches does not loop back here.
--
-- Port note: the original takes its tool name from $0. Under ade-hs-run the program's own name is
-- not the tool's, so the name is read from ADE_SHIM_NAME (default "swift"). The shim that calls
-- this program must export ADE_SHIM_NAME=xcodebuild for the xcodebuild link.
--
-- Exit: exec'd into the target, so its status is the exit status. 127 when the target cannot be
-- executed.
module Main (main) where

import Control.Exception (IOException, try)
import System.Directory (Permissions, doesFileExist, executable, getPermissions)
import System.Environment (getArgs, lookupEnv, setEnv)
import System.Exit (ExitCode (..), exitWith)
import System.IO (hPutStrLn, stderr)
import System.Posix.Process (executeFile)

-- | Decide whether the invocation is heavy, following the original's first-word rules.
isHeavy :: String -> [String] -> Bool
isHeavy "swift" args = swiftHeavy args
isHeavy "xcodebuild" args = not (any (`elem` xcodeLight) args)
isHeavy _ _ = False

-- | swift: the first word that does not start with '-' decides; version and help flags anywhere
-- before it mean light. Matches the original's for-loop with `continue` on dashed words.
swiftHeavy :: [String] -> Bool
swiftHeavy = go
  where
    go [] = False
    go (a : as)
      | a `elem` swiftLight = False
      | take 1 a == "-" = go as
      | otherwise = a `elem` ["build", "test", "run"]

swiftLight :: [String]
swiftLight = ["--version", "-version", "--help", "-h", "-help"]

xcodeLight :: [String]
xcodeLight = ["-version", "-help", "-usage", "-showsdks", "-list", "-showBuildSettings", "-showdestinations"]

main :: IO ()
main = do
  args <- getArgs
  name <- maybe "swift" id <$> lookupEnv "ADE_SHIM_NAME"
  home <- maybe "" id <$> lookupEnv "HOME"
  let real = "/usr/bin/" ++ name
      bg = home ++ "/ops/site-private/bin/bg"
  batch <- lookupEnv "BG_SHIM"
  bgOk <- doesExecutable bg
  let heavy = null batch && bgOk && isHeavy name args
  if heavy
    then do
      setEnv "BG_SHIM" "1"
      run bg (real : args)
    else run real args

doesExecutable :: FilePath -> IO Bool
doesExecutable p = do
  ok <- doesFileExist p
  if not ok then pure False else do
    r <- try (getPermissions p) :: IO (Either IOException Permissions)
    pure (either (const False) executable r)

-- | Replace this process with argv (never a shell string).
run :: FilePath -> [String] -> IO ()
run path argv = do
  r <- try (executeFile path True argv Nothing) :: IO (Either IOException ())
  case r of
    Left e -> do
      hPutStrLn stderr ("heavy-shim: cannot exec " ++ path ++ ": " ++ show e)
      exitWith (ExitFailure 127)
    Right () -> pure ()
