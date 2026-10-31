-- | herdr-server-run: what the dev.herdr.server LaunchAgent runs instead of `herdr server` (2026-10-25).
--
-- After a live server handoff (`herdr server --handoff-import ...`) the new server is a child of launchd's init,
-- not of this job. launchd sees its own process exit and relaunches `herdr server`, which prints
-- "error: herdr server is already running" and exits 1: 24 restarts in 4 minutes, and load-watch's job guard
-- booted the job out (2026-10-25). Here that exact case ("already running", exit 1) is a clean exit 0; any other
-- result is passed through unchanged. The wrapper never signals, stops or probes the running server: it only runs
-- `herdr server` as before, so the TUIs inside herdr are untouched.
--
-- The plist pairs this with KeepAlive {SuccessfulExit: false}: a clean exit (handoff, already running) is not
-- restarted; a crash (non-zero) is. HERDR_BIN overrides the binary (tests).
--
-- Port of bin/herdr-server-run (HEAD). The server's stdout and stderr are merged and read through a pipe;
-- the text is echoed to this process's stdout once the server exits, and kept in memory for the "already
-- running" check (the original tee'd into a temp file as it went). TERM, INT and
-- HUP are forwarded to the server; a status of 129, 130 or 143 (the server killed by one of them) is
-- re-waited, as the original does. A status killed by a signal is reported as 128 + signal, as a shell does.
module Main (main) where

import Control.Concurrent (forkIO)
import Control.Concurrent.MVar (newEmptyMVar, putMVar, takeMVar)
import Control.Exception (IOException, try)
import Control.Monad (void)
import Data.List (isInfixOf)
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath ((</>))
import System.IO (hClose, hFlush, hGetContents, hPutStr, hPutStrLn, stderr, stdout)
import System.Posix.IO (createPipe, fdToHandle)
import System.Posix.Signals (Handler (Catch), installHandler, sigHUP, sigINT, sigTERM)
import System.Process
  ( CreateProcess (..)
  , ProcessHandle
  , StdStream (..)
  , createProcess
  , terminateProcess
  , proc
  , waitForProcess
  )

-- | A shell's status for a child: the exit code, or 128 + the signal number when it was killed.
shellStatus :: ExitCode -> Int
shellStatus ExitSuccess = 0
shellStatus (ExitFailure n)
  | n < 0 = 128 - n
  | otherwise = n

main :: IO ()
main = do
  herdrOverride <- lookupEnv "HERDR_BIN"
  home <- lookupEnv "HOME"
  let herdr = case herdrOverride of
        Just p | not (null p) -> p
        _ -> maybe "" (</> ".local/bin/herdr") home
  args <- getArgs
  (readEnd, writeEnd) <- createPipe
  readH <- fdToHandle readEnd
  writeH <- fdToHandle writeEnd
  (_, _, _, ph) <- createProcess (proc herdr ("server" : args))
    { std_out = UseHandle writeH
    , std_err = UseHandle writeH
    }
  hClose writeH
  let forward = void (try (terminateProcess ph) :: IO (Either IOException ()))
  mapM_ (\s -> installHandler s (Catch forward) Nothing) [sigTERM, sigINT, sigHUP]
  -- The reader drains the pipe while the server runs, so a full pipe never blocks the server.
  outVar <- newEmptyMVar
  _ <- forkIO $ do
    text <- hGetContents readH
    length text `seq` putMVar outVar text
  code0 <- waitForProcess ph
  let rc0 = shellStatus code0
  rc <-
    if rc0 `elem` [143, 130, 129]
      then shellStatus <$> waitForProcess ph
      else pure rc0
  out <- takeMVar outVar
  hPutStr stdout out
  hFlush stdout
  if rc == 1 && "herdr server is already running" `isInfixOf` out
    then do
      hPutStrLn stderr "herdr-server-run: a herdr server is already running (handed off); exiting 0 so launchd does not loop"
      exitWith ExitSuccess
    else exitWith (if rc == 0 then ExitSuccess else ExitFailure rc)
