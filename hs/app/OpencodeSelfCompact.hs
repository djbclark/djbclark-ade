-- | opencode-self-compact: ask the native Go plugin's single admission guard to compact this session.
--
-- Usage: opencode-self-compact [--dry-run]
-- Exit: 2 invalid scope/options, 7 guard refusal, 11 RPC failure.
-- No direct compact POST, separate cooldown store, parent target or retry.
--
-- The session id and directory come from ADE_OPENCODE_SESSION_ID and ADE_OPENCODE_DIRECTORY, as
-- before. The RPC body is parsed with Ade.Json (boot packages only).
module Main (main) where

import Ade.JsonLite (Json (..), objLookup, parseJson)
import Control.Exception (IOException, try)
import Data.Char (intToDigit, isAlphaNum, isAscii, ord)
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (isAbsolute)
import System.IO (hPutStrLn, stderr)
import System.Process (readCreateProcessWithExitCode, proc)
import System.Timeout (timeout)

main :: IO ()
main = do
  args <- getArgs
  sid <- maybe "" id <$> lookupEnv "ADE_OPENCODE_SESSION_ID"
  directory <- maybe "" id <$> lookupEnv "ADE_OPENCODE_DIRECTORY"
  let scopeOk = validSession sid && not (null directory) && isAbsolute directory
  if not (args `elem` [[], ["--dry-run"]]) || not scopeOk
    then failWith 2 "self-slash: native compact needs tool-scoped session and directory"
    else if args == ["--dry-run"]
      then do
        putStrLn ("self-slash: would ask native Go guard to compact " ++ sid ++ "; no API call made")
        exitWith ExitSuccess
      else compact sid directory

-- | Equivalent of re.fullmatch(r"ses_[A-Za-z0-9]+", sid).
validSession :: String -> Bool
validSession s = case s of
  's' : 'e' : 's' : '_' : rest@(_ : _) -> all (\c -> isAscii c && isAlphaNum c) rest
  _ -> False

compact :: String -> String -> IO ()
compact sid directory = do
  let route = "/api/rpc/ade.go-context/compact?" ++ urlEncode [("location[directory]", directory)]
      body = "{\"input\": {\"sessionID\": " ++ jsonString sid ++ "}}"
  r <- try (timeout (45 * 1000000) (readCreateProcessWithExitCode
              (proc "opencode" ["api", "post", route, "--data", body]) "")) :: IO (Either IOException (Maybe (ExitCode, String, String)))
  case r of
    Left _ -> uncertain "OSError"
    Right Nothing -> uncertain "TimeoutExpired"
    Right (Just (ExitFailure _, _, _)) ->
      failWith 11 "self-slash: native Go guard unavailable or request uncertain; do not retry blindly"
    Right (Just (ExitSuccess, out, _)) ->
      case parseJson out of
        Left _ -> uncertain "ValueError"
        Right value -> do
          -- Native RPC returns {output: ...}; the guard's boolean is not HTTP acceptance.
          let accepted = case objLookup "output" value of
                Just o@(JObj _) -> objLookup "accepted" o == Just (JBool True)
                _ -> False
          if not accepted
            then failWith 7 "self-slash: native guard refused compaction; inspect pending state, cooldown or baseline"
            else do
              putStrLn ("self-slash: native compaction accepted for " ++ sid ++ "; completion is not yet verified")
              exitWith ExitSuccess
  where
    uncertain kind = failWith 11 ("self-slash: native Go guard call failed or is uncertain (" ++ kind ++ "); no automatic retry")

failWith :: Int -> String -> IO a
failWith code msg = hPutStrLn stderr msg >> exitWith (ExitFailure code)

-- | Python's urlencode (quote_plus, safe="").
urlEncode :: [(String, String)] -> String
urlEncode kvs = intercalate' "&" [enc k ++ "=" ++ enc v | (k, v) <- kvs]
  where
    intercalate' _ [] = ""
    intercalate' sep (x : xs) = x ++ concatMap (sep ++) xs
    enc = concatMap encChar
    encChar ' ' = "+"
    encChar c
      | isAscii c && (isAlphaNum c || c `elem` "-_.~") = [c]
      | otherwise = concatMap pct (utf8 c)
    pct b = ['%', hexDigit (b `div` 16), hexDigit (b `mod` 16)]
    hexDigit d = if d < 10 then intToDigit d else toEnum (fromEnum 'A' + d - 10)

-- | UTF-8 bytes of one character.
utf8 :: Char -> [Int]
utf8 c
  | n < 0x80 = [n]
  | n < 0x800 = [0xC0 + n `div` 64, 0x80 + n `mod` 64]
  | n < 0x10000 = [0xE0 + n `div` 4096, 0x80 + (n `div` 64) `mod` 64, 0x80 + n `mod` 64]
  | otherwise = [0xF0 + n `div` 262144, 0x80 + (n `div` 4096) `mod` 64, 0x80 + (n `div` 64) `mod` 64, 0x80 + n `mod` 64]
  where n = ord c

-- | A JSON string literal for a value already known to be plain (session ids are alphanumeric).
jsonString :: String -> String
jsonString s = "\"" ++ s ++ "\""
