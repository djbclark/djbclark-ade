-- | seat-name: one ever-increasing base-36 name for every Paseo seat, so no two are ever alike.
--
-- Naming scheme: `<role> <base36>` counting from 1, using 0-9 then a-z (seat 1 -> "Dann 1",
-- seat 10 -> "Dann a", seat 36 -> "Dann 10"). Workspaces draw from the same counter and render as
-- `<slug>-<n>-pw`. State lives in ~/.local/state/ade/seat-sequence.json:
-- {"next": N, "issued": {"<name>": {"at": ts, "n": N, "kind": K, "id": agent}}}.
--
--   seat-name next [--role dann] [--count N] [--agent ID]            allocate seat name(s)
--   seat-name next --kind workspace --slug <slug> [--count N]        allocate workspace name(s)
--   seat-name peek [--role dann] [--count N]                         the next name(s), no consume
--   seat-name issued [--limit N] [--json]                            what has been handed out
--   seat-name check                                                  self-test: base-36, atomic, monotonic
--
-- Exit: 0 ok; 1 error; 2 usage.
--
-- Port notes: the Python original serialised with fcntl.flock. Only boot packages are used, and
-- `unix` has no flock, so the lock here is an O_EXCL lock file beside the state file, taken with
-- retries and removed on release. A process that dies while holding it leaves the lock file behind;
-- remove SEAT_NAME_STATE's ".lock" file by hand in that case. The self-test runs its concurrent
-- allocators as threads rather than processes; the lock is a file, so it holds across processes too.
module Main (main) where

import Ade.JsonLite (Json (..), objLookup, objSet, parseJson, renderWith)
import Control.Concurrent (forkIO, threadDelay)
import Control.Concurrent.MVar (newEmptyMVar, putMVar, takeMVar)
import Control.Exception (IOException, bracket_, throwIO, try)
import Control.Monad (forM, forM_, when)
import Data.Char (isAlphaNum, isAscii, isDigit, toLower)
import Data.IORef (IORef, modifyIORef, newIORef, readIORef)
import Data.List (intercalate, sortOn)
import Data.Time (defaultTimeLocale, formatTime, getZonedTime)
import System.Directory (createDirectoryIfMissing, doesFileExist, getHomeDirectory, getTemporaryDirectory, removeFile)
import System.Environment (getArgs, lookupEnv)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath (takeDirectory, (</>))
import System.IO (IOMode (..), hGetContents, hPutStr, hPutStrLn, hSetEncoding, stderr, stdout, utf8, withFile)
import System.IO.Error (isAlreadyExistsError)
import System.Posix.Files (rename)
import System.Posix.IO (OpenFileFlags (..), OpenMode (..), closeFd, defaultFileFlags, openFd)

-- | The state file, with the next number and the audit map.
data State = State { stNext :: Integer, stIssued :: [(String, Json)] }

digits36 :: String
digits36 = "0123456789abcdefghijklmnopqrstuvwxyz"

-- | `n` (1-based) in base 36 using 0-9 then a-z. 1 -> "1", 10 -> "a", 36 -> "10".
toBase36 :: Integer -> String
toBase36 n
  | n < 1 = error "seat numbers start at 1"
  | otherwise = go n ""
  where
    go 0 acc = acc
    go k acc = let (q, r) = k `divMod` 36 in go q (digits36 !! fromIntegral r : acc)

-- | Workspace slug from free text: lower case, hyphen-joined whole words, number-only words dropped,
-- at most 34 characters (the same transformation as autorename's title_slug).
slugSlug :: String -> String
slugSlug title = if null out then "session" else out
  where
    cleaned = map (\c -> if isAscii c && isAlphaNum c then toLower c else ' ') title
    words' = [w | w <- words cleaned, not (all isDigit w)]
    out = build "" words'
    build acc [] = acc
    build acc (w : ws) =
      let cand = if null acc then w else acc ++ "-" ++ w
      in if length cand > 34 then acc else build cand ws

nameFor :: String -> Maybe String -> Maybe String -> Integer -> Either String String
nameFor kind role slug n
  | kind == "workspace" = case slug of
      Nothing -> Left "workspace names need --slug"
      Just s -> Right (slugSlug s ++ "-" ++ toBase36 n ++ "-pw")
  | otherwise = Right (maybe "Dann" id role ++ " " ++ toBase36 n)

-- | Where the state lives, and the lock beside it.
statePath :: IO FilePath
statePath = do
  home <- getHomeDirectory
  maybe (home </> ".local" </> "state" </> "ade" </> "seat-sequence.json") id <$> lookupEnv "SEAT_NAME_STATE"

-- | Run an action holding the exclusive lock file (O_EXCL create, retried until it is free).
withLock :: FilePath -> IO a -> IO a
withLock st act = bracket_ acquire release act
  where
    lockPath = replaceSuffix st ".lock"
    acquire = createDirectoryIfMissing True (takeDirectory st) >> go (0 :: Int)
    go n = do
      r <- try (openFd lockPath WriteOnly (defaultFileFlags { exclusive = True, creat = Just 0o644 }) >>= closeFd)
             :: IO (Either IOException ())
      case r of
        Right () -> pure ()
        Left e
          | isAlreadyExistsError e && n < 60000 -> threadDelay 1000 >> go (n + 1)
          | isAlreadyExistsError e -> throwIO e
          | otherwise -> throwIO e
    release = removeFile lockPath

replaceSuffix :: FilePath -> String -> FilePath
replaceSuffix p suf = (reverse . drop 1 . dropWhile (/= '.') . reverse) p ++ suf

loadState :: FilePath -> IO State
loadState p = do
  ok <- doesFileExist p
  if not ok then pure (State 1 []) else do
    r <- try (readUtf8 p) :: IO (Either IOException String)
    pure $ case r of
      Left _ -> State 1 []
      Right t -> case parseJson t of
        Right (JObj kvs) ->
          let nxt = case lookup "next" kvs of
                Just (JNum n) | all isDigit n, not (null n) -> read n
                _ -> 1
              iss = case lookup "issued" kvs of
                Just (JObj xs) -> xs
                _ -> []
          in State nxt iss
        _ -> State 1 []

saveState :: FilePath -> State -> IO ()
saveState p st = do
  createDirectoryIfMissing True (takeDirectory p)
  let tmp = replaceSuffix p ".json.tmp"
      obj = JObj [ ("next", JNum (show (stNext st)))
                 , ("issued", JObj (sortOn fst (stIssued st))) ]
  writeUtf8 tmp (renderSorted obj ++ "\n")
  rename tmp p

-- | json.dumps(d, indent=1, sort_keys=True), recursively.
renderSorted :: Json -> String
renderSorted = renderWith 1 . sortKeys
  where
    sortKeys (JObj kvs) = JObj (sortOn fst [(k, sortKeys v) | (k, v) <- kvs])
    sortKeys (JArr xs) = JArr (map sortKeys xs)
    sortKeys other = other

-- | Take `count` names from the sequence in one locked read-modify-write.
allocate :: FilePath -> String -> Int -> Maybe String -> Maybe String -> Maybe String -> IO (Either String [String])
allocate p kind count role slug agent = withLock p $ do
  st <- loadState p
  let go _ [] acc = Right (reverse acc)
      go n (_ : rest) acc = case nameFor kind role slug n of
        Left e -> Left e
        Right name -> go (n + 1) rest ((name, n) : acc)
  case go (stNext st) [1 .. count] [] of
    Left e -> pure (Left e)
    Right items -> do
      ts <- timestamp
      let issued' = stIssued st ++
            [ (name, JObj [ ("at", JStr ts), ("n", JNum (show n)), ("kind", JStr kind), ("id", JStr (maybe "" id agent)) ])
            | (name, n) <- items ]
      saveState p (State (stNext st + fromIntegral count) issued')
      pure (Right (map fst items))

-- | The next names without consuming them, under a shared-style lock.
peekNames :: FilePath -> String -> Int -> Maybe String -> Maybe String -> IO (Either String [String])
peekNames p kind count role slug = withLock p $ do
  st <- loadState p
  pure (mapM (\i -> nameFor kind role slug (stNext st + i)) [0 .. fromIntegral count - 1])

timestamp :: IO String
timestamp = formatTime defaultTimeLocale "%Y-%m-%dT%H:%M:%S%z" <$> getZonedTime

readUtf8 :: FilePath -> IO String
readUtf8 p = withFile p ReadMode $ \h -> do
  hSetEncoding h utf8
  s <- hGetContents h
  length s `seq` pure s

writeUtf8 :: FilePath -> String -> IO ()
writeUtf8 p s = withFile p WriteMode $ \h -> hSetEncoding h utf8 >> hPutStr h s

-- | Argument parsing for the subcommands.
data Cmd
  = Next Opts
  | Peek Opts
  | Issued Int Bool
  | Check

data Opts = Opts
  { oRole :: Maybe String, oKind :: String, oSlug :: Maybe String
  , oCount :: Int, oAgent :: Maybe String }

defaultOpts :: Opts
defaultOpts = Opts Nothing "seat" Nothing 1 Nothing

usageLine :: String
usageLine = "usage: seat-name {next,peek,issued,check} ..."

parseCmd :: [String] -> Either String Cmd
parseCmd [] = Left "the following arguments are required: command"
parseCmd ("next" : rest) = Next <$> parseOpts True rest defaultOpts
parseCmd ("peek" : rest) = Peek <$> parseOpts False rest defaultOpts
parseCmd ("issued" : rest) = parseIssued rest 20 False
parseCmd ["check"] = Right Check
parseCmd (c : _) = Left ("invalid choice: " ++ c)

parseOpts :: Bool -> [String] -> Opts -> Either String Opts
parseOpts _ [] o = Right o
parseOpts allowAgent ("--role" : v : r) o = parseOpts allowAgent r o { oRole = Just v }
parseOpts allowAgent ("--kind" : v : r) o
  | v `elem` ["seat", "workspace"] = parseOpts allowAgent r o { oKind = v }
  | otherwise = Left ("argument --kind: invalid choice: " ++ v)
parseOpts allowAgent ("--slug" : v : r) o = parseOpts allowAgent r o { oSlug = Just v }
parseOpts allowAgent ("--count" : v : r) o
  | all isDigit v, not (null v) = parseOpts allowAgent r o { oCount = read v }
  | otherwise = Left ("argument --count: invalid int value: " ++ show v)
parseOpts True ("--agent" : v : r) o = parseOpts True r o { oAgent = Just v }
parseOpts _ (a : _) _ = Left ("unrecognized arguments: " ++ a)

parseIssued :: [String] -> Int -> Bool -> Either String Cmd
parseIssued [] lim js = Right (Issued lim js)
parseIssued ("--limit" : v : r) _ js
  | all isDigit v, not (null v) = parseIssued r (read v) js
  | otherwise = Left ("argument --limit: invalid int value: " ++ show v)
parseIssued ("--json" : r) lim _ = parseIssued r lim True
parseIssued (a : _) _ _ = Left ("unrecognized arguments: " ++ a)

main :: IO ()
main = do
  hSetEncoding stdout utf8
  hSetEncoding stderr utf8
  args <- getArgs
  roleDefault <- lookupEnv "SEAT_NAME_ROLE"
  case parseCmd args of
    Left err -> do
      hPutStrLn stderr (usageLine ++ "\nseat-name: error: " ++ err)
      exitWith (ExitFailure 2)
    Right cmd -> do
      p <- statePath
      rc <- dispatch p roleDefault cmd
      exitWith (if rc == 0 then ExitSuccess else ExitFailure rc)

dispatch :: FilePath -> Maybe String -> Cmd -> IO Int
dispatch p roleDefault cmd = case cmd of
  Next o -> do
    let role = maybe roleDefault Just (oRole o)
    r <- allocate p (oKind o) (oCount o) role (oSlug o) (oAgent o)
    either (\e -> hPutStrLn stderr ("seat-name: " ++ e) >> pure 1) (\ns -> mapM_ putStrLn ns >> pure 0) r
  Peek o -> do
    let role = maybe roleDefault Just (oRole o)
    r <- peekNames p (oKind o) (oCount o) role (oSlug o)
    either (\e -> hPutStrLn stderr ("seat-name: " ++ e) >> pure 1) (\ns -> mapM_ putStrLn ns >> pure 0) r
  Issued lim js -> do
    st <- loadState p
    let rows = take lim (sortOn (negate . metaN . snd) (stIssued st))
    if js
      then putStrLn (renderWith 1 (JArr [JObj (("name", JStr k) : kvs) | (k, JObj kvs) <- rows])) >> pure 0
      else do
        forM_ rows $ \(name, meta) ->
          putStrLn (padRight 20 name ++ " " ++ strOf "at" meta ++ "  " ++ strOf "id" meta)
        pure 0
  Check -> selfTest

metaN :: Json -> Integer
metaN m = case objLookup "n" m of
  Just (JNum n) | all isDigit n, not (null n) -> read n
  _ -> 0

strOf :: String -> Json -> String
strOf k m = case objLookup k m of
  Just (JStr s) -> s
  _ -> "?"

padRight :: Int -> String -> String
padRight n s = s ++ replicate (n - length s) ' '

-- | Prove the two properties that matter: monotonic (no reuse) and atomic under concurrency.
selfTest :: IO Int
selfTest = do
  tmpDir <- ((</> "seat-name-check") <$> getTemporaryDirectory)
  let p = tmpDir </> "seq.json"
  createDirectoryIfMissing True tmpDir
  exists <- doesFileExist p
  when exists (removeFile p)
  problems <- newIORef []
  -- base 36 and the documented rollovers
  forM_ [(1, "1"), (9, "9"), (10, "a"), (35, "z"), (36, "10"), (71, "1z"), (1296, "100")] $ \(n, want) ->
    when (toBase36 n /= want) $ addProblem problems ("base36 " ++ show n ++ "=" ++ toBase36 n ++ " want " ++ want)
  first <- allocate p "seat" 3 (Just "Test") Nothing Nothing
  second <- allocate p "seat" 3 (Just "Test") Nothing Nothing
  case (first, second) of
    (Right a, Right b) -> do
      when (a /= ["Test 1", "Test 2", "Test 3"]) $ addProblem problems ("unexpected first three: " ++ show a)
      when (length (uniq (a ++ b)) /= 6) $ addProblem problems ("names repeated: " ++ show (a ++ b))
    _ -> addProblem problems "seat allocation failed"
  ws <- allocate p "workspace" 2 Nothing (Just "Dann Home") Nothing
  when (ws /= Right ["dann-home-7-pw", "dann-home-8-pw"]) $ addProblem problems ("unexpected workspace names: " ++ show ws)
  -- atomic: six concurrent allocators, ten names each, every one distinct
  dones <- forM [1 .. 6 :: Int] $ \_ -> do
    mv <- newEmptyMVar
    _ <- forkIO (allocate p "seat" 10 (Just "Conc") Nothing Nothing >>= putMVar mv)
    pure mv
  results <- mapM takeMVar dones
  let names = concat [ns | Right ns <- results]
  when (length names /= 60) $ addProblem problems ("expected 60 names, got " ++ show (length names))
  when (length (uniq names) /= length names) $
    addProblem problems "CONCURRENT DUPLICATES (the bug this prevents)"
  probs <- readProblems problems
  putStrLn "seat-name self-test"
  let verdict = if null probs then "ok" else "PROBLEM"
  putStrLn ("1. base-36 rendering: " ++ verdict)
  putStrLn ("2. monotonic, no reuse: " ++ verdict)
  putStrLn ("3. atomic under 6 concurrent allocators: " ++ verdict)
  if null probs
    then putStrLn "self-test: PASS" >> pure 0
    else putStrLn ("self-test: FAILED: " ++ intercalate "; " probs) >> pure 1
  where
    uniq = foldr (\x acc -> if x `elem` acc then acc else x : acc) []

addProblem :: IORef [String] -> String -> IO ()
addProblem ref msg = modifyIORef ref (++ [msg])

readProblems :: IORef [String] -> IO [String]
readProblems = readIORef
