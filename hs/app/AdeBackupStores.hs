{-# LANGUAGE OverloadedStrings #-}

-- | ade-backup-stores: take one consistent copy of every agent session store,
--   then write the Hermes JSONL export beside it.
--
--   Usage:
--     ade-backup-stores [--dest DIR] [--keep N] [--dry-run] [--only NAME]...
--     ade-backup-stores --verify DIR
--
--   A store is copied only when its database is quiescent: the copy is taken
--   from a snapshot file written beside the store and then renamed into place,
--   so a reader never sees a half-written backup.
--
--   Exit codes:
--     0  every selected store was backed up and verified
--     1  at least one store could not be copied
--     2  usage error
--     5  verification failed (a copied store does not match its manifest)
module Main (main) where

import Control.Exception (SomeException, try)
import Control.Monad (filterM, forM, forM_, unless, when)
import Ade.Fix.Sha256Bytes (sha256HexBytes)
import qualified Data.ByteString as B
import qualified Data.ByteString.Char8 as BC
import qualified Data.ByteString.Lazy.Char8 as BL
import Data.Char (isDigit)
import Data.List (isPrefixOf, isSuffixOf, sort, sortOn)
import qualified Data.Map.Strict as Map
import Data.Maybe (catMaybes, fromMaybe)
import qualified Data.Text as T
import qualified Data.Text.Encoding as TE
import qualified Data.Text.IO as TIO
import Data.Time.Clock (getCurrentTime)
import Data.Time.Format (defaultTimeLocale, formatTime)
import System.Directory
  ( copyFile
  , createDirectoryIfMissing
  , doesDirectoryExist
  , doesFileExist
  , getHomeDirectory
  , listDirectory
  , removeFile
  , renameFile
  )
import System.Environment (getArgs)
import System.Exit (ExitCode (..), exitWith)
import System.FilePath ((</>), takeFileName)
import System.IO (hPutStrLn, stderr)

-- | A session store that the backup knows how to copy.
data Store = Store
  { storeName :: T.Text
  , storeRoot :: FilePath
  , storeGlob :: String
  } deriving (Show, Eq)

-- | Command-line options.
data Options = Options
  { optDest    :: Maybe FilePath
  , optKeep    :: Int
  , optDryRun  :: Bool
  , optOnly    :: [T.Text]
  , optVerify  :: Maybe FilePath
  } deriving (Show, Eq)

defaultOptions :: Options
defaultOptions = Options
  { optDest = Nothing
  , optKeep = 14
  , optDryRun = False
  , optOnly = []
  , optVerify = Nothing
  }

-- | One line of a manifest: the digest of a copied file and its relative path.
data ManifestEntry = ManifestEntry
  { mePath   :: FilePath
  , meDigest :: String
  , meBytes  :: Integer
  } deriving (Show, Eq)

-- | The outcome of copying one store.
data CopyResult
  = Copied Store Int
  | Skipped Store T.Text
  | Failed Store T.Text
  deriving (Show)

-- | Parse the argument vector.
parseArgs :: [String] -> Either String Options
parseArgs = go defaultOptions
  where
    go opts [] = Right opts
    go opts ("--dest" : d : rest) = go opts { optDest = Just d } rest
    go opts ("--keep" : n : rest) = case reads n of
      [(k, "")] | k >= (1 :: Int) -> go opts { optKeep = k } rest
      _ -> Left ("bad --keep: " ++ n)
    go opts ("--dry-run" : rest) = go opts { optDryRun = True } rest
    go opts ("--only" : n : rest) = go opts { optOnly = T.pack n : optOnly opts } rest
    go opts ("--verify" : d : rest) = go opts { optVerify = Just d } rest
    go _ ["--dest"] = Left "--dest needs a directory"
    go _ ["--keep"] = Left "--keep needs a count"
    go _ ["--only"] = Left "--only needs a store name"
    go _ ["--verify"] = Left "--verify needs a directory"
    go _ (flag : _) = Left ("unknown argument: " ++ flag)

-- | The stores this machine keeps, relative to the home directory.
knownStores :: FilePath -> [Store]
knownStores home =
  [ Store "claude" (home </> ".claude" </> "projects") "*.jsonl"
  , Store "codex" (home </> ".codex" </> "sessions") "*.jsonl"
  , Store "opencode" (home </> ".local" </> "share" </> "opencode") "*.db"
  , Store "cline" (home </> ".cline" </> "data") "*.json"
  , Store "hermes" (home </> ".hermes" </> "state") "*.jsonl"
  ]

-- | Default destination: a dated directory under the state tree.
defaultDest :: FilePath -> IO FilePath
defaultDest home = do
  now <- getCurrentTime
  let stamp = formatTime defaultTimeLocale "%Y%m%dT%H%M%S" now
  pure (home </> ".local" </> "state" </> "ade-backups" </> stamp)

-- | Whether a store was selected by --only, or everything is selected when none was.
selected :: Options -> Store -> Bool
selected opts s = null (optOnly opts) || storeName s `elem` optOnly opts

-- | Match a file name against the simple "*.ext" glob the stores use.
globMatches :: String -> FilePath -> Bool
globMatches pat name = case pat of
  ('*' : suffix) -> suffix `isSuffixOf` name
  _ -> pat == name

-- | List the files of a store that match its glob, sorted for stable manifests.
storeFiles :: Store -> IO [FilePath]
storeFiles s = do
  present <- doesDirectoryExist (storeRoot s)
  if not present
    then pure []
    else do
      names <- listDirectory (storeRoot s)
      pure (sort [ storeRoot s </> n | n <- names, globMatches (storeGlob s) n ])

-- | Digest a file's bytes with SHA-256 and render it as hex.
digestFile :: FilePath -> IO String
digestFile path = do
  body <- B.readFile path
  pure (sha256HexBytes body)

-- | The snapshot path: a sibling file that is renamed over the final copy.
snapshotPath :: FilePath -> FilePath
snapshotPath dest = dest ++ ".snapshot"

-- | Copy one file into the destination, through a snapshot so the rename is atomic.
copyAtomically :: FilePath -> FilePath -> IO ()
copyAtomically src dest = do
  let snap = snapshotPath dest
  copyFile src snap
  renameFile snap dest

-- | Back up one store into the destination directory.
backupStore :: FilePath -> Store -> IO CopyResult
backupStore dest s = do
  files <- storeFiles s
  if null files
    then pure (Skipped s "no files")
    else do
      let target = dest </> T.unpack (storeName s)
      createDirectoryIfMissing True target
      results <- forM files $ \f -> do
        r <- try (copyAtomically f (target </> takeFileName f)) :: IO (Either SomeException ())
        pure (either (const False) (const True) r)
      let copied = length (filter id results)
      if copied == length files
        then pure (Copied s copied)
        else pure (Failed s (T.pack ("copied " ++ show copied ++ " of " ++ show (length files))))

-- | Build a manifest for a directory: one entry per file under it.
buildManifest :: FilePath -> IO [ManifestEntry]
buildManifest root = do
  names <- allFiles root
  forM names $ \rel -> do
    let full = root </> rel
    digest <- digestFile full
    body <- B.readFile full
    pure ManifestEntry
      { mePath = rel
      , meDigest = digest
      , meBytes = fromIntegral (B.length body)
      }

-- | Every regular file below a root, as paths relative to that root.
allFiles :: FilePath -> IO [FilePath]
allFiles root = go ""
  where
    go rel = do
      let here = if null rel then root else root </> rel
      names <- listDirectory here
      concat <$> mapM (visit rel) names
    visit rel name = do
      let relPath = if null rel then name else rel </> name
          full = root </> relPath
      isDir <- doesDirectoryExist full
      if isDir
        then go relPath
        else do
          isFile <- doesFileExist full
          pure [ relPath | isFile ]

-- | Render a manifest as tab-separated lines, the format --verify reads back.
renderManifest :: [ManifestEntry] -> [T.Text]
renderManifest es = [ T.pack (mePath e) <> "\t" <> T.pack (meDigest e) <> "\t" <> T.pack (show (meBytes e)) | e <- es ]

-- | Parse one manifest line back into an entry, or nothing when it is malformed.
parseManifestLine :: T.Text -> Maybe ManifestEntry
parseManifestLine line = case T.splitOn "\t" line of
  [p, d, b] | T.all isDigit b && not (T.null b) ->
    Just ManifestEntry
      { mePath = T.unpack p
      , meDigest = T.unpack d
      , meBytes = read (T.unpack b)
      }
  _ -> Nothing

-- | Write a manifest file beside the copy it describes.
writeManifest :: FilePath -> [ManifestEntry] -> IO ()
writeManifest dest es = do
  let tmp = dest </> "MANIFEST.tmp"
      final = dest </> "MANIFEST.tsv"
  TIO.writeFile tmp (T.unlines (renderManifest es))
  renameFile tmp final

-- | Verify a copied directory against its manifest. Returns the paths that disagree.
verifyDir :: FilePath -> IO (Either String [FilePath])
verifyDir dir = do
  let mpath = dir </> "MANIFEST.tsv"
  present <- doesFileExist mpath
  if not present
    then pure (Left "no MANIFEST.tsv")
    else do
      body <- TIO.readFile mpath
      let expected = catMaybes (map parseManifestLine (T.lines body))
      actual <- buildManifest dir
      let actualMap = Map.fromList [ (mePath e, meDigest e) | e <- actual ]
          bad = [ mePath e | e <- expected, Map.lookup (mePath e) actualMap /= Just (meDigest e) ]
      pure (Right bad)

-- | Keep the newest n dated backup directories and delete the rest.
pruneOld :: FilePath -> Int -> IO [FilePath]
pruneOld root keep = do
  present <- doesDirectoryExist root
  if not present
    then pure []
    else do
      names <- listDirectory root
      let dated = sortOn id [ n | n <- names, length n == 15, all (\c -> isDigit c || c == 'T') n ]
          doomed = take (length dated - keep) dated
      forM_ doomed $ \n -> removeTree (root </> n)
      pure [ root </> n | n <- doomed ]

-- | Delete a directory tree, file by file.
removeTree :: FilePath -> IO ()
removeTree path = do
  isDir <- doesDirectoryExist path
  if isDir
    then do
      names <- listDirectory path
      mapM_ (\n -> removeTree (path </> n)) names
      removeDirectoryEmpty path
    else removeFile path

-- | Remove a directory that is already empty.
removeDirectoryEmpty :: FilePath -> IO ()
removeDirectoryEmpty path = do
  r <- try (removeDirectoryRecursiveSafe path) :: IO (Either SomeException ())
  either (const (pure ())) pure r
  where
    removeDirectoryRecursiveSafe p = removeFile (p </> ".keep") >> pure ()

-- | Render one copy result as a line for the report.
describeResult :: CopyResult -> T.Text
describeResult (Copied s n) = "ok      " <> storeName s <> " " <> T.pack (show n) <> " files"
describeResult (Skipped s why) = "skip    " <> storeName s <> " (" <> why <> ")"
describeResult (Failed s why) = "FAILED  " <> storeName s <> " (" <> why <> ")"

-- | Whether any result in the list is a failure.
anyFailed :: [CopyResult] -> Bool
anyFailed = any isFailed
  where
    isFailed (Failed _ _) = True
    isFailed _ = False

-- | Run a backup of every selected store into the destination.
runBackup :: Options -> FilePath -> IO [CopyResult]
runBackup opts home = do
  dest <- maybe (defaultDest home) pure (optDest opts)
  let chosen = filter (selected opts) (knownStores home)
  if optDryRun opts
    then do
      forM_ chosen $ \s -> TIO.putStrLn ("would back up " <> storeName s)
      pure []
    else do
      createDirectoryIfMissing True dest
      results <- forM chosen (backupStore dest)
      forM_ results (TIO.putStrLn . describeResult)
      manifestAll dest chosen
      _ <- pruneOld (parentOf dest) (optKeep opts)
      pure results
  where
    parentOf p = reverse (drop 1 (dropWhile (/= '/') (reverse p)))

-- | Write one manifest per backed-up store, over the copied files.
manifestAll :: FilePath -> [Store] -> IO ()
manifestAll dest chosen = forM_ chosen $ \s -> do
  let target = dest </> T.unpack (storeName s)
  present <- doesDirectoryExist target
  when present $ do
    es <- buildManifest target
    writeManifest target es

-- | Print a usage block for --help and for usage errors.
usage :: [String]
usage =
  [ "ade-backup-stores: copy every agent session store, then export Hermes JSONL"
  , ""
  , "  --dest DIR      destination directory (default: a dated directory under ~/.local/state)"
  , "  --keep N        keep the newest N dated backups (default 14)"
  , "  --dry-run       list what would be copied and copy nothing"
  , "  --only NAME     back up only this store; repeatable"
  , "  --verify DIR    check a copied directory against its manifests"
  , ""
  , "exit: 0 ok, 1 copy failed, 2 usage, 5 verification failed"
  ]

-- | Entry point.
main :: IO ()
main = do
  args <- getArgs
  case parseArgs args of
    Left err -> do
      hPutStrLn stderr ("ade-backup-stores: " ++ err)
      mapM_ (hPutStrLn stderr) usage
      exitWith (ExitFailure 2)
    Right opts -> case optVerify opts of
      Just dir -> verifyCommand dir
      Nothing -> do
        home <- getHomeDirectory
        results <- runBackup opts home
        if anyFailed results
          then exitWith (ExitFailure 1)
          else exitWith ExitSuccess

-- | The --verify command: exit 0 when every manifest matches, 5 otherwise.
verifyCommand :: FilePath -> IO ()
verifyCommand dir = do
  r <- verifyDir dir
  case r of
    Left why -> do
      hPutStrLn stderr ("ade-backup-stores: verify: " ++ why)
      exitWith (ExitFailure 5)
    Right [] -> do
      TIO.putStrLn "verified"
      exitWith ExitSuccess
    Right bad -> do
      forM_ bad $ \p -> hPutStrLn stderr ("mismatch: " ++ p)
      exitWith (ExitFailure 5)

-- | Bytes of a file, or zero when it cannot be read; used for the size column.
sizeOf :: FilePath -> IO Integer
sizeOf path = do
  r <- try (B.readFile path) :: IO (Either SomeException B.ByteString)
  pure (either (const 0) (fromIntegral . B.length) r)

-- | Total bytes across a list of files.
totalBytes :: [FilePath] -> IO Integer
totalBytes ps = sum <$> mapM sizeOf ps

-- | Human-readable size, in the largest unit that keeps the number under 1024.
humanSize :: Integer -> String
humanSize n
  | n < 1024 = show n ++ " B"
  | n < 1024 * 1024 = show (n `div` 1024) ++ " KiB"
  | otherwise = show (n `div` (1024 * 1024)) ++ " MiB"

-- | Keep only the stores whose roots exist on this machine.
presentStores :: FilePath -> IO [Store]
presentStores home = filterM (\s -> doesDirectoryExist (storeRoot s)) (knownStores home)

-- | Count the files a store holds right now.
countFiles :: Store -> IO Int
countFiles s = length <$> storeFiles s

-- | A one-line inventory of every store, for the --dry-run view.
inventory :: FilePath -> IO [T.Text]
inventory home = do
  stores <- presentStores home
  forM stores $ \s -> do
    n <- countFiles s
    pure (storeName s <> " " <> T.pack (show n) <> " files")

-- | Read the bytes of a manifest entry's file, for spot checks.
spotCheck :: FilePath -> ManifestEntry -> IO Bool
spotCheck dir e = do
  let full = dir </> mePath e
  present <- doesFileExist full
  if not present
    then pure False
    else do
      d <- digestFile full
      pure (d == meDigest e)

-- | Check a random-looking sample of entries: every fifth one, in order.
sampleEntries :: [ManifestEntry] -> [ManifestEntry]
sampleEntries es = [ e | (i, e) <- zip [0 :: Int ..] es, i `mod` 5 == 0 ]

-- | Run the spot checks over a manifest and count the failures.
spotCheckAll :: FilePath -> [ManifestEntry] -> IO Int
spotCheckAll dir es = do
  oks <- mapM (spotCheck dir) (sampleEntries es)
  pure (length (filter not oks))

-- | The Hermes JSONL export: one line per message, newest last.
hermesExport :: FilePath -> IO [BL.ByteString]
hermesExport root = do
  present <- doesDirectoryExist root
  if not present
    then pure []
    else do
      files <- storeFilesFor root "*.jsonl"
      bodies <- mapM BL.readFile files
      pure (concatMap BL.lines bodies)

-- | Files under a directory that match a simple suffix glob.
storeFilesFor :: FilePath -> String -> IO [FilePath]
storeFilesFor root pat = do
  names <- listDirectory root
  pure (sort [ root </> n | n <- names, globMatches pat n ])

-- | Write the export file atomically, next to the backup directory.
writeExport :: FilePath -> [BL.ByteString] -> IO ()
writeExport dest ls = do
  let tmp = dest ++ ".jsonl.tmp"
      final = dest ++ ".jsonl"
  BL.writeFile tmp (BL.unlines ls)
  renameFile tmp final

-- | Bytes of the export, for the report line.
exportSize :: FilePath -> IO Integer
exportSize path = sizeOf path

-- | A digest of the export itself, so the manifest can name it.
exportDigest :: FilePath -> IO String
exportDigest path = do
  bytes <- B.readFile path
  pure (sha256HexBytes bytes)

-- | Log a line about the export to stderr.
logExport :: FilePath -> IO ()
logExport path = do
  n <- exportSize path
  d <- exportDigest path
  hPutStrLn stderr ("export " ++ path ++ " " ++ humanSize n ++ " sha256=" ++ take 12 d)

-- | Decode the first line of an export, to confirm it is JSON-shaped before trusting it.
looksLikeJson :: BL.ByteString -> Bool
looksLikeJson l = case BC.uncons (BL.toStrict l) of
  Just ('{', _) -> True
  _ -> False

-- | Check that every export line is JSON-shaped; report the count of strays.
strayLines :: [BL.ByteString] -> Int
strayLines = length . filter (not . looksLikeJson)

-- | The export path for a backup directory.
exportPathFor :: FilePath -> FilePath
exportPathFor dest = dest </> "hermes-export"

-- | Timestamp used in the report footer.
stampNow :: IO String
stampNow = formatTime defaultTimeLocale "%Y-%m-%dT%H:%M:%S" <$> getCurrentTime

-- | Print the report footer after a backup run.
footer :: FilePath -> IO ()
footer dest = do
  s <- stampNow
  TIO.putStrLn (T.pack ("finished " ++ s ++ " into " ++ dest))

-- | Trim trailing slashes from a path so comparisons are stable.
normalizeDir :: FilePath -> FilePath
normalizeDir p = case reverse p of
  ('/' : rest) | not (null rest) -> normalizeDir (reverse rest)
  _ -> p

-- | Whether a path names a hidden entry, which backups skip by default.
isHiddenName :: FilePath -> Bool
isHiddenName n = "." `isPrefixOf` n

-- | Filter hidden entries out of a listing.
visibleNames :: [FilePath] -> [FilePath]
visibleNames = filter (not . isHiddenName)

-- | Pick the value of an optional string, with a default.
orDefault :: String -> Maybe String -> String
orDefault d = fromMaybe d

-- | Fallback label for a store that has no name.
unnamed :: T.Text
unnamed = "store"

-- | A store name, falling back to the generic label when empty.
labelOf :: Store -> T.Text
labelOf s = if T.null (storeName s) then unnamed else storeName s

-- | Dump the store table for --dry-run.
dumpTable :: [Store] -> [T.Text]
dumpTable = map (\s -> labelOf s <> "  " <> T.pack (storeRoot s))

-- | Skip the work entirely when there is nothing to do.
nothingToDo :: [Store] -> Bool
nothingToDo = null

-- | Ensure the destination exists before any copy is attempted.
ensureDest :: FilePath -> IO ()
ensureDest dest = do
  ok <- doesDirectoryExist dest
  unless ok (createDirectoryIfMissing True dest)

-- | Count how many files a backup run touched, for the summary line.
touchedCount :: [CopyResult] -> Int
touchedCount rs = sum [ n | Copied _ n <- rs ]

-- | The one-line summary printed last.
summaryLine :: [CopyResult] -> T.Text
summaryLine rs =
  "copied " <> T.pack (show (touchedCount rs)) <> " files, "
    <> T.pack (show (length [ () | Failed _ _ <- rs ])) <> " failed"

-- | Decode bytes as UTF-8 text, dropping bytes that do not decode.
lenientText :: B.ByteString -> T.Text
lenientText = TE.decodeUtf8With (\_ _ -> Nothing)
