-- | herdr-jump: move to a Herdr address typed from the keyboard (tmux `prefix+:`).
--
--   herdr-jump              prompt for an address (how the popup keybind runs it)
--   herdr-jump w22:t4       focus tab 4 of workspace 22 (switches workspace too)
--   herdr-jump w23:p7       focus pane 7 of workspace 23 (any pane, agent or shell)
--   herdr-jump w22          focus workspace 22
--
-- Herdr has no action that takes an address (docs/herdr-jump.md), so this wraps the three server-side
-- focus calls that do: `herdr tab focus <id>`, `herdr workspace focus <id>`, and the socket method
-- `pane.focus`, which the CLI does not expose. The socket call goes through `nc -U`, as the shell
-- original does.
module Main (main) where

import Ade.Prelude (runCapture, warn)
import Control.Concurrent (threadDelay)
import Control.Exception (IOException, try)
import Data.Char (isDigit, isSpace, toUpper)
import Data.List (isInfixOf, isPrefixOf, tails)
import System.Directory (getHomeDirectory)
import System.Environment (getArgs, lookupEnv, setEnv)
import System.Exit (ExitCode (..), exitSuccess, exitWith)
import System.IO (hFlush, hGetLine, hIsTerminalDevice, isEOF, putStr, stdin, stdout)
import System.Posix.Files (FileStatus, getFileStatus, isSocket)
import System.Process (readProcessWithExitCode)

-- | Print the message to stderr and exit 1, pausing first when stdin is a terminal (a popup pane).
fail' :: String -> IO a
fail' msg = do
  warn msg
  tty <- hIsTerminalDevice stdin
  if tty then threadDelay 1500000 else pure ()
  exitWith (ExitFailure 1)

-- | `gsed -E 's/.*"message":"([^"]*)".*/\1/'` applied line by line: when a line holds a
-- `"message":"..."` field the greedy match takes the last one; otherwise the line is kept as is.
messageOf :: String -> String
messageOf = unlines' . map oneLine . lines
  where
    key = "\"message\":\""
    oneLine line =
      case [rest | rest <- tails line, key `isPrefixOf` rest] of
        [] -> line
        found -> let body = drop (length key) (last found)
                 in if '"' `elem` body then takeWhile (/= '"') body else line
    unlines' [] = ""
    unlines' xs = foldr1 (\a b -> a ++ "\n" ++ b) xs

-- | Lower-case tails of the address and the marker letters: the `gtr` normalisation of the original.
normalise :: String -> String
normalise = stripW
  where
    stripW (c : cs) | c `elem` "wW" = cs
    stripW s = s

upperHex :: String -> String
upperHex = map (\c -> if c >= 'a' && c <= 'f' then toUpper c else c)

lowerMarkers :: String -> String
lowerMarkers = map (\c -> case c of { 'T' -> 't'; 'P' -> 'p'; _ -> c })

isWorkspaceStart :: String -> Bool
isWorkspaceStart ('w' : c : _) = isDigit c || (c >= 'A' && c <= 'F')
isWorkspaceStart _ = False

main :: IO ()
main = do
  home <- getHomeDirectory
  hb <- maybe "herdr" id <$> lookupEnv "HERDR_BIN_PATH"
  sock <- maybe (home ++ "/.config/herdr/herdr.sock") id <$> lookupEnv "HERDR_SOCKET_PATH"
  oldPath <- maybe "" id <$> lookupEnv "PATH"
  setEnv "PATH" ("/opt/homebrew/bin:" ++ oldPath)
  argv <- getArgs
  raw <- case argv of
    (a : _) -> pure a
    [] -> do
      putStr "go to (w22 / w22:t4 / w23:p7): "
      hFlush stdout
      eof <- isEOF
      if eof then exitWith (ExitFailure 1) else hGetLine stdin
  let trimmed = filter (not . isSpace) raw
  if null trimmed then exitSuccess else pure ()
  let body = normalise trimmed
      (wsPart, restPart) = break (== ':') body
      addr = "w" ++ upperHex wsPart ++ lowerMarkers restPart
  if not (isWorkspaceStart addr)
    then fail' ("bad address: " ++ addr ++ " (want w22, w22:t4 or w23:p7)")
    else pure ()
  if ":p" `isInfixOf` addr && "w" `isPrefixOf` addr
    then paneJump sock addr
    else if ":t" `isInfixOf` addr && "w" `isPrefixOf` addr
      then cliFocus hb "tab" addr
      else cliFocus hb "workspace" addr

-- | Pane focus over the socket: `nc -U -w 2 SOCK`, one JSON request line.
paneJump :: FilePath -> String -> IO ()
paneJump sock addr = do
  let validChar c = isDigit c || (c >= 'A' && c <= 'F') || c `elem` "wp:"
  if not (all validChar addr) || count ':' addr >= 2
    then fail' ("bad pane id: " ++ addr)
    else pure ()
  isSock <- socketAt sock
  if not isSock then fail' ("no herdr socket at " ++ sock) else pure ()
  let req = "{\"id\":\"jump\",\"method\":\"pane.focus\",\"params\":{\"pane_id\":\"" ++ addr ++ "\"}}\n"
  r <- try (readProcessWithExitCode "nc" ["-U", "-w", "2", sock] req) :: IO (Either IOException (ExitCode, String, String))
  resp <- case r of
    Right (ExitSuccess, o, _) -> pure o
    _ -> fail' "socket call failed"
  if "\"error\"" `isInfixOf` resp
    then fail' ("herdr: " ++ messageOf resp)
    else if "\"result\"" `isInfixOf` resp
      then exitSuccess
      else fail' "no reply from herdr"
  where
    count c = length . filter (== c)

socketAt :: FilePath -> IO Bool
socketAt p = do
  r <- try (getFileStatus p) :: IO (Either IOException FileStatus)
  pure $ case r of
    Right st -> isSocket st
    Left _ -> False

-- | `herdr tab focus ADDR` or `herdr workspace focus ADDR`, stdout and stderr together as `2>&1` does.
cliFocus :: FilePath -> String -> String -> IO ()
cliFocus hb kind addr = do
  (rc, out, err) <- runCapture [hb, kind, "focus", addr]
  let combined = out ++ err
  if rc /= 0 then fail' (messageOf combined) else pure ()
  exitSuccess
