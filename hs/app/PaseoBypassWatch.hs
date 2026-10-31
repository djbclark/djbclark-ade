{-# LANGUAGE ForeignFunctionInterface #-}
-- | paseo-bypass-watch: put freshly created Paseo Claude agents that start in `default` or `auto` into
-- bypassPermissions. No model.
--
--   paseo-bypass-watch [--once | --loop SECONDS] [--dry-run] [--state PATH] [--max-age SECONDS] [--json]
--
-- Why (home rule 16: every agent runs yolo): Paseo has no default-mode setting and no create-time hook, so a
-- Claude seat opened from the Paseo UI or by a hand-typed `paseo agent run` starts in `default` and prompts.
-- `bin/paseo-new-seat` covers seats opened by us; this watcher covers the rest by setting the mode shortly
-- after creation.
--
-- One pass: (0) `agent ls --json`, read first so that a label written at create time is seen; (1)
-- `agent ls --label perm=ask --json`, whose ids are exempt, read on every pass and fail-closed; (2) for each
-- claude agent that is not closed, exempt or already handled, `agent inspect --json`; (3) an agent that is not
-- archived, whose mode is `default` or `auto`, and younger than --max-age (default 120 s), gets
-- `agent mode ID bypassPermissions`, a re-inspect and a check, and one stdout line `set ID name`; (4) any other
-- claude agent is only recorded. A failing set is retried on later passes, 5 attempts in all, then recorded
-- as failed.
--
-- One pass at a time: a pass holds flock(LOCK_EX|LOCK_NB) on `<state>.lock` from loading the state to saving
-- it. A busy lock makes `--once` print one line and exit 0; `--loop` skips that pass. --dry-run takes no lock
-- and writes nothing.
--
-- State: JSON at --state (default ~/.local/state/paseo-bypass-watch.json), written to a temp file beside it and
-- renamed into place: {"version": 1, "handled": {ID: {"result": "set|recorded|failed", "at": ISO}}, "attempts":
-- {ID: N}}. A state file of the wrong shape is an error (exit 1).
--
-- Exit: --once 0 (also when nothing to do or the lock is busy), 1 on an unexpected error, 2 on usage.
-- --loop N passes every N seconds until SIGTERM or SIGINT, then exits 0.
--
-- Port of bin/paseo-bypass-watch (HEAD). The Python flock call is the same flock(2) through the C library.
-- The state write does not fsync; it is a temp-file write and a rename. Unknown top-level keys in a state
-- file are dropped on the next save.
module Main (main) where

import Control.Concurrent (threadDelay)
import Control.Exception (Exception, IOException, SomeException, catch, fromException, throwIO, try)
import Control.Monad (forM_, unless, when)
import Data.Char (isSpace)
import Data.IORef (IORef, newIORef, readIORef, writeIORef)
import Data.List (intercalate, sortOn)
import qualified Data.Map.Strict as M
import Data.Maybe (fromMaybe)
import Data.Time.Clock (UTCTime, diffUTCTime, getCurrentTime)
import Data.Time.Format (defaultTimeLocale, formatTime)
import Data.Time.Format.ISO8601 (iso8601ParseM)
import Foreign.C.Types (CInt (..))
import System.Directory (createDirectoryIfMissing, doesFileExist, renameFile)
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (takeDirectory, (</>))
import System.IO (IOMode (WriteMode), hFlush, hPutStr, hPutStrLn, stderr, stdout, withFile)
import System.Posix.IO (OpenFileFlags (..), OpenMode (ReadWrite), closeFd, defaultFileFlags, openFd)
import System.Posix.Types (Fd (..))
import System.Posix.Signals (Handler (Catch), installHandler, sigINT, sigTERM)
import System.Process (proc, readCreateProcessWithExitCode)
import System.Timeout (timeout)
import Text.Read (readMaybe)
import Ade.Json

foreign import ccall unsafe "flock" c_flock :: CInt -> CInt -> IO CInt

lockEx, lockNb :: CInt
lockEx = 2
lockNb = 4

-- | A failure that aborts the pass (the Python RuntimeError).
newtype WatchError = WatchError String deriving (Show)

instance Exception WatchError

failWith :: String -> IO a
failWith = throwIO . WatchError

targetMode :: String
targetMode = "bypassPermissions"

actOnModes :: [String]
actOnModes = ["default", "auto"]

maxAttempts :: Int
maxAttempts = 5

callTimeoutSeconds :: Int
callTimeoutSeconds = 60

minLoop :: Double
minLoop = 1.0

lockBusyMsg :: String
lockBusyMsg = "another pass holds the state lock; nothing done"

defaultCli :: FilePath
defaultCli = "/Applications/Paseo.app/Contents/Resources/bin/paseo"

eprint :: String -> IO ()
eprint msg = hPutStrLn stderr ("paseo-bypass-watch: " ++ msg) >> hFlush stderr

-- | Run the paseo CLI with argv; stdout on success, WatchError otherwise.
paseo :: [String] -> IO String
paseo args = do
  cliOverride <- lookupEnv "PASEO_CLI"
  let cli = case cliOverride of
        Just c | not (null c) -> c
        _ -> defaultCli
  r <- try (timeout (callTimeoutSeconds * 1000000) (readCreateProcessWithExitCode (proc cli args) ""))
    :: IO (Either IOException (Maybe (ExitCode, String, String)))
  let label = unwords args
  case r of
    Left e -> failWith ("cannot run paseo " ++ label ++ ": " ++ show e)
    Right Nothing -> failWith ("cannot run paseo " ++ label ++ ": timed out")
    Right (Just (ExitSuccess, out, _)) -> pure out
    Right (Just (ExitFailure n, out, err)) ->
      failWith ("paseo " ++ label ++ " exited " ++ show n ++ ": " ++ take 200 (trim (if null (trim err) then out else err)))

paseoJson :: [String] -> IO Value
paseoJson args = do
  out <- paseo args
  case parseJson out of
    Just v -> pure v
    Nothing -> failWith ("paseo " ++ unwords args ++ ": output is not JSON")

trim :: String -> String
trim = dropWhile isSpace . reverse . dropWhile isSpace . reverse

-- | Case-insensitive key lookup (ls prints `status`, inspect prints `Status`).
pick :: Value -> [String] -> Maybe Value
pick (VObj kvs) names = case [v | n <- names, (k, v) <- kvs, lower k == lower n] of
  (v : _) -> Just v
  [] -> Nothing
  where
    lower = map toLowerAscii
    toLowerAscii c = if c >= 'A' && c <= 'Z' then toEnum (fromEnum c + 32) else c
pick _ _ = Nothing

pickStr :: Value -> [String] -> String
pickStr v names = fromMaybe "" (asStr (pick v names))

providerOf :: Value -> String
providerOf v = takeWhile (/= '/') (pickStr v ["provider"])

agentId :: Value -> Maybe String
agentId v = case asStr (field "id" v) of
  Just i | not (null i) -> Just i
  _ -> Nothing

listAgents :: IO [Value]
listAgents = do
  v <- paseoJson ["agent", "ls", "--json"]
  case v of
    VArr xs -> pure [x | x@(VObj _) <- xs, Just _ <- [agentId x]]
    _ -> failWith "paseo agent ls --json: expected a JSON array"

inspectAgent :: String -> IO Value
inspectAgent aid = do
  v <- paseoJson ["agent", "inspect", aid, "--json"]
  case v of
    VObj _ -> pure v
    _ -> failWith ("paseo agent inspect " ++ aid ++ ": expected a JSON object")

-- | Ids of agents carrying perm=ask. Any failure or odd shape raises: never read a failed call as empty.
exemptIds :: IO [String]
exemptIds = do
  v <- paseoJson ["agent", "ls", "--label", "perm=ask", "--json"]
  case v of
    VArr xs | all (\x -> case x of VObj _ -> agentId x /= Nothing; _ -> False) xs ->
      pure [i | x <- xs, Just i <- [agentId x]]
    _ -> failWith "paseo agent ls --label perm=ask --json: expected an array of agents with ids"

-- | Seconds since an ISO time string (a naive time is read as UTC), or Nothing.
ageSeconds :: Maybe Value -> UTCTime -> Maybe Double
ageSeconds (Just (VStr s)) now =
  case iso8601ParseM (fixZ s) :: Maybe UTCTime of
    Just t -> Just (realToFrac (diffUTCTime now t))
    Nothing -> Nothing
  where
    fixZ x = if not (null x) && last x == 'Z' then init x ++ "+00:00" else x
ageSeconds _ _ = Nothing

-- | The state: handled records, attempt counts.
data Handled = Handled { hResult :: String, hAt :: String }

data State = State
  { stHandled :: M.Map String Handled
  , stAttempts :: M.Map String Int
  }

statePathDefault :: IO FilePath
statePathDefault = do
  home <- fromMaybe "" <$> lookupEnv "HOME"
  pure (home </> ".local/state/paseo-bypass-watch.json")

loadState :: FilePath -> IO State
loadState path = do
  exists <- doesFileExist path
  if not exists
    then pure (State M.empty M.empty)
    else do
      text <- readFile path
      length text `seq` pure ()
      case parseJson text of
        Just (VObj kvs) -> do
          handled <- case lookup "handled" kvs of
            Nothing -> pure M.empty
            Just (VObj hs) -> M.fromList <$> mapM (\(k, v) -> case v of
              VObj _ -> pure (k, Handled (fromMaybe "" (asStr (field "result" v))) (fromMaybe "" (asStr (field "at" v))))
              _ -> failWith ("state file " ++ path ++ " has an unexpected shape")) hs
            Just _ -> failWith ("state file " ++ path ++ " has an unexpected shape")
          attempts <- case lookup "attempts" kvs of
            Nothing -> pure M.empty
            Just (VObj as) -> M.fromList <$> mapM (\(k, v) -> case asInteger (Just v) of
              Just n | isIntLit v -> pure (k, fromIntegral n)
              _ -> failWith ("state file " ++ path ++ " has an unexpected shape")) as
            Just _ -> failWith ("state file " ++ path ++ " has an unexpected shape")
          pure (State handled attempts)
        _ -> failWith ("state file " ++ path ++ " has an unexpected shape")
  where
    isIntLit (VNum t) = all (`elem` "0123456789-") t
    isIntLit _ = False

-- | Atomic save: temp file beside the state, then rename. Keys sorted, indent 1, as json.dumps does.
saveState :: FilePath -> State -> IO ()
saveState path st = do
  createDirectoryIfMissing True (takeDirectory path)
  let tmp = path ++ ".tmp"
      handledOut = OObj [ (k, OObj [("at", OStr (hAt h)), ("result", OStr (hResult h))])
                        | (k, h) <- M.toAscList (stHandled st) ]
      attemptsOut = OObj [ (k, OInt (fromIntegral n)) | (k, n) <- M.toAscList (stAttempts st) ]
      doc = OObj [("attempts", attemptsOut), ("handled", handledOut), ("version", OInt 1)]
  withFile tmp WriteMode $ \h -> hPutStr h (encodeIndent1 doc) >> hFlush h
  renameFile tmp path

-- | flock the sibling lock file for the duration of the action; the action gets False when the lock is busy.
withPassLock :: FilePath -> (Bool -> IO a) -> IO a
withPassLock statePath action = do
  createDirectoryIfMissing True (takeDirectory statePath)
  fd <- openFd (statePath ++ ".lock") ReadWrite defaultFileFlags { creat = Just 0o600 }
  rc <- c_flock (fromIntegral (fdNum fd)) (lockEx + lockNb)
  if rc /= 0
    then closeFd fd >> action False
    else do
      r <- action True `catch` (\e -> closeFd fd >> throwIO (e :: SomeException))
      closeFd fd
      pure r

fdNum :: Fd -> CInt
fdNum (Fd n) = n

-- | Records one agent: handled with a result and a timestamp, its attempt count cleared.
record :: State -> String -> String -> String -> State
record st aid result at =
  st { stHandled = M.insert aid (Handled result at) (stHandled st)
     , stAttempts = M.delete aid (stAttempts st) }

data Report = Report
  { rSet :: [String], rRecorded :: [String], rFailed :: [String], rWouldSet :: [String], rErrors :: [String] }

emptyReport :: Report
emptyReport = Report [] [] [] [] []

-- | One pass: mutates the state in an IORef; raises before touching any agent when a list cannot be read.
onePass :: IORef State -> Double -> Bool -> IO Report
onePass stRef maxAge dryRun = do
  now <- getCurrentTime
  let stamp = formatTime defaultTimeLocale "%Y-%m-%dT%H:%M:%S+00:00" now
  agents <- listAgents
  exempt <- exemptIds
  repRef <- newIORef emptyReport
  let modify f = modifyRef repRef f
  forM_ agents $ \agent -> do
    let aid = fromMaybe "" (agentId agent)
        name = pickStr agent ["name"]
    st0 <- readIORef stRef
    unless (providerOf agent /= "claude" || M.member aid (stHandled st0)) $
      if aid `elem` exempt || pickStr agent ["status"] == "closed"
        then do
          unless dryRun $ writeIORef stRef (record st0 aid "recorded" stamp)
          modify (\r -> r { rRecorded = rRecorded r ++ [aid] })
        else do
          infoR <- try (inspectAgent aid) :: IO (Either WatchError Value)
          case infoR of
            Left (WatchError e) -> do
              modify (\r -> r { rErrors = rErrors r ++ [e] })
              eprint e
            Right info -> do
              let age = ageSeconds (pick info ["createdAt", "created"]) now
                  retrying = M.member aid (stAttempts st0)
                  archived = pick info ["archived"] == Just (VBool True)
                  mode = pickStr info ["mode"]
                  modeOk = mode `elem` actOnModes && pick info ["mode"] /= Nothing
                  young = case age of
                    Just a -> a < maxAge
                    Nothing -> False
                  skip = archived || not modeOk || (not retrying && not young)
              if skip
                then do
                  unless dryRun $ writeIORef stRef (record st0 aid "recorded" stamp)
                  modify (\r -> r { rRecorded = rRecorded r ++ [aid] })
                else if dryRun
                  then do
                    putStrLn ("would set " ++ aid ++ " " ++ name)
                    modify (\r -> r { rWouldSet = rWouldSet r ++ [aid] })
                  else do
                    setR <- try (do
                      _ <- paseo ["agent", "mode", aid, targetMode]
                      after <- inspectAgent aid
                      let now' = pickStr after ["mode"]
                      unless (now' == targetMode) $
                        failWith ("agent " ++ aid ++ " reads mode " ++ show now' ++ " after the set")) :: IO (Either WatchError ())
                    case setR of
                      Left (WatchError e) -> do
                        st1 <- readIORef stRef
                        let n = M.findWithDefault 0 aid (stAttempts st1) + 1
                            st2 = st1 { stAttempts = M.insert aid n (stAttempts st1) }
                        writeIORef stRef st2
                        eprint ("set " ++ aid ++ " failed (attempt " ++ show n ++ "/" ++ show maxAttempts ++ "): " ++ e)
                        modify (\r -> r { rErrors = rErrors r ++ [e] })
                        when (n >= maxAttempts) $ do
                          st3 <- readIORef stRef
                          writeIORef stRef (record st3 aid "failed" stamp)
                          modify (\r -> r { rFailed = rFailed r ++ [aid] })
                      Right () -> do
                        st1 <- readIORef stRef
                        writeIORef stRef (record st1 aid "set" stamp)
                        modify (\r -> r { rSet = rSet r ++ [aid] })
                        putStrLn ("set " ++ aid ++ " " ++ name)
  readIORef repRef
  where
    modifyRef ref f = readIORef ref >>= writeIORef ref . f

-- | Compact JSON as Python's json.dumps writes it by default (", " and ": " separators, keys sorted).
compactJson :: [(String, [String])] -> String
compactJson kvs = "{" ++ intercalate ", " [show' k ++ ": [" ++ intercalate ", " (map show' vs) ++ "]" | (k, vs) <- sortOn fst kvs] ++ "}"
  where
    show' s = encodeIndent1 (OStr s)

runPass :: FilePath -> Double -> Bool -> Bool -> IO Bool
runPass path maxAge dryRun asJson = do
  let body got = if not got then pure False else do
        st <- loadState path >>= newIORef
        r <- try (onePass st maxAge dryRun) :: IO (Either SomeException Report)
        unless dryRun $ readIORef st >>= saveState path
        case r of
          Left e -> throwIO e
          Right rep -> do
            when asJson $ putStrLn (compactJson
              [ ("errors", rErrors rep), ("failed", rFailed rep), ("recorded", rRecorded rep)
              , ("set", rSet rep), ("would_set", rWouldSet rep) ])
            hFlush stdout
            pure True
  if dryRun then body True else withPassLock path body

data Args = Args { aOnce :: Bool, aLoop :: Maybe Double, aDry :: Bool, aState :: Maybe FilePath, aMaxAge :: Double, aJson :: Bool }

parseArgs :: [String] -> IO Args
parseArgs = go (Args False Nothing False Nothing 120 False)
  where
    go a [] = finish a
    go a ("--once" : r) = go a { aOnce = True } r
    go a ("--dry-run" : r) = go a { aDry = True } r
    go a ("--json" : r) = go a { aJson = True } r
    go a ("--loop" : v : r) = case readMaybe (fixLead v) of
      Just x -> go a { aLoop = Just x } r
      Nothing -> argErr ("argument --loop: invalid float value: " ++ show v)
    go a ("--state" : v : r) = go a { aState = Just v } r
    go a ("--max-age" : v : r) = case readMaybe (fixLead v) of
      Just x -> go a { aMaxAge = x } r
      Nothing -> argErr ("argument --max-age: invalid float value: " ++ show v)
    go _ (x : _) = argErr ("unrecognized arguments: " ++ x)
    finish a
      | aOnce a && aLoop a /= Nothing = argErr "argument --loop: not allowed with argument --once"
      | Just l <- aLoop a, isBad l = argErr ("--loop SECONDS must be a finite number of at least " ++ show minLoop)
      | isBad' (aMaxAge a) = argErr "--max-age must be a finite number of seconds greater than 0"
      | otherwise = pure a
    isBad l = isNaN l || isInfinite l || l < minLoop
    isBad' m = isNaN m || isInfinite m || m <= 0
    fixLead x = if take 1 x == "." then '0' : x else x
    argErr msg = do
      hPutStrLn stderr "usage: paseo-bypass-watch [-h] [--once | --loop LOOP] [--dry-run] [--state STATE] [--max-age MAX_AGE] [--json]"
      hPutStrLn stderr ("paseo-bypass-watch: error: " ++ msg)
      exitWith (ExitFailure 2)

main :: IO ()
main = do
  argv <- getArgs
  a <- parseArgs argv
  path <- maybe statePathDefault pure (aState a)
  case aLoop a of
    Nothing -> do
      r <- try (runPass path (aMaxAge a) (aDry a) (aJson a)) :: IO (Either SomeException Bool)
      case r of
        Left e -> do
          eprint ("error: " ++ errText e)
          exitWith (ExitFailure 1)
        Right False -> eprint lockBusyMsg >> exitWith ExitSuccess
        Right True -> exitWith ExitSuccess
    Just interval -> do
      stopRef <- newIORef False
      let stop = writeIORef stopRef True
      _ <- installHandler sigTERM (Catch stop) Nothing
      _ <- installHandler sigINT (Catch stop) Nothing
      let loop = do
            stopped <- readIORef stopRef
            unless stopped $ do
              r <- try (runPass path (aMaxAge a) (aDry a) (aJson a)) :: IO (Either SomeException Bool)
              case r of
                Right False -> eprint lockBusyMsg
                Right True -> pure ()
                Left e -> eprint ("pass failed: " ++ errText e)
              waitFor stopRef (interval * 1000000)
              loop
      loop
      exitWith ExitSuccess
  where
    waitFor ref micros = do
      stopped <- readIORef ref
      unless (stopped || micros <= 0) $ do
        let step = min micros 200000
        threadDelay (round step)
        waitFor ref (micros - step)
    errText e = case fromException e of
      Just (WatchError m) -> m
      Nothing -> show e
