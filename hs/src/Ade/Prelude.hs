-- | Shared helpers for ade-hs entry points: argv handling, process calls, exit codes.
module Ade.Prelude
  ( die'
  , warn
  , runCapture
  , runStatus
  , lookupEnvDefault
  , ExitCode (..)
  , exitWith
  ) where

import Control.Exception (IOException, try)
import System.Environment (lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.IO (hPutStrLn, stderr)
import System.Process (readProcessWithExitCode)

-- | Print to stderr and exit with the given status.
die' :: Int -> String -> IO a
die' code msg = hPutStrLn stderr msg >> exitWith (if code == 0 then ExitSuccess else ExitFailure code)

warn :: String -> IO ()
warn = hPutStrLn stderr

-- | Run argv (never a shell string) and return (status, stdout, stderr); a missing binary is status 127.
runCapture :: [String] -> IO (Int, String, String)
runCapture [] = pure (127, "", "empty argv")
runCapture (cmd : args) = do
  r <- try (readProcessWithExitCode cmd args "") :: IO (Either IOException (ExitCode, String, String))
  pure $ case r of
    Left e -> (127, "", show e)
    Right (ExitSuccess, o, e) -> (0, o, e)
    Right (ExitFailure n, o, e) -> (n, o, e)

runStatus :: [String] -> IO Int
runStatus argv = (\(c, _, _) -> c) <$> runCapture argv

lookupEnvDefault :: String -> String -> IO String
lookupEnvDefault k d = maybe d id <$> lookupEnv k
