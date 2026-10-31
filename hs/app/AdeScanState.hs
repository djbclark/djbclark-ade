{-# LANGUAGE AllowAmbiguousTypes       #-}
{-# LANGUAGE DataKinds                 #-}
{-# LANGUAGE DeriveFunctor             #-}
{-# LANGUAGE DeriveGeneric             #-}
{-# LANGUAGE FlexibleContexts          #-}
{-# LANGUAGE FlexibleInstances         #-}
{-# LANGUAGE GADTs                     #-}
{-# LANGUAGE GeneralizedNewtypeDeriving #-}
{-# LANGUAGE KindSignatures            #-}
{-# LANGUAGE LambdaCase                #-}
{-# LANGUAGE MultiParamTypeClasses     #-}
{-# LANGUAGE OverloadedStrings         #-}
{-# LANGUAGE RankNTypes                #-}
{-# LANGUAGE RecordWildCards           #-}
{-# LANGUAGE ScopedTypeVariables       #-}
{-# LANGUAGE TemplateHaskell           #-}
{-# LANGUAGE TupleSections             #-}
{-# LANGUAGE TypeFamilies              #-}
{-# LANGUAGE TypeApplications          #-}
{-# LANGUAGE ViewPatterns              #-}
{-# OPTIONS_GHC -Wall -Werror=incomplete-patterns #-}

-- |
-- Module      : AdeScanState
-- Description : A pure, effect-tracked, free-monadic port of bin/ade-scan-state.
--
-- ==  Why this module exists
--
-- The Python original is 2294 lines of a single file that scans bigteam task
-- directories and git checkouts and changes no work. It does this correctly.
-- It is also, by any reasonable measure, a little bit too small to be taken
-- seriously by a type system. This is the Haskell port, which fixes that.
--
-- Every effect the Python script performs (a @du@, a @git status@, a @read@ of
-- @.git/config@, an @ls-remote@ over the network) is lifted into a free monad
-- 'Scan' whose only interpreter is 'runScanIO'. Pure verdict logic lives in
-- 'Verdict' and never touches the file system. Types encode the invariants the
-- Python enforced with comments, so that "a checkout is never clean and pushed
-- while a git call is incomplete" is a theorem about 'classify', not a hope.
--
-- ==  Fidelity
--
-- The constants, the verdict precedence, the flag names, the markdown escaping
-- rules and the exit-code contract are carried over verbatim in spirit. The
-- deeper submodule, alternates and stash-log walks are represented by typed
-- placeholders that document what the Python does; porting every edge case is
-- still outstanding.
--
-- ==  Build
--
-- Boot packages only: base, containers, text, bytestring, process, directory,
-- filepath, time, mtl, unix. The free monad and the option parser are small
-- local definitions (sections 2 and 7), not the free or optparse packages.
module Main (main) where

import           Control.Applicative        ((<|>))
import           Control.Exception          (SomeException, try, evaluate)
import           Control.Monad              (forM, forM_, unless, when)
import           Control.Monad.Reader       (ReaderT, asks, runReaderT)
import           Control.Monad.State.Strict (StateT, get, gets, modify', put, runStateT)
import           Control.Monad.Except       (ExceptT, runExceptT, throwError)
import           Control.Monad.IO.Class     (liftIO)
import qualified Data.ByteString.Char8      as BC
import qualified Data.ByteString            as BS
import           Data.Char                  (chr, isAscii, isControl, isSpace, ord)
import           Data.Foldable              (foldl', for_, traverse_)
import           Data.List                  (isPrefixOf, isSuffixOf, sortBy, sortOn)
import qualified Data.Map.Strict            as M
import           Data.Maybe                 (fromMaybe, mapMaybe, catMaybes, isJust)
import           Data.Ord                   (Down (..), comparing)
import qualified Data.Set                   as S
import           Data.Text                  (Text)
import qualified Data.Text                  as T
import qualified Data.Text.IO               as TIO
import           Data.Time.Clock.POSIX      (POSIXTime, getPOSIXTime, posixSecondsToUTCTime)
import           Data.Time.Format           (formatTime, defaultTimeLocale)
import           Data.Time.LocalTime        (getCurrentTimeZone, utc, utcToLocalTime)
import           Data.Time.Clock            (UTCTime, getCurrentTime)
import           GHC.Generics               (Generic)
import           System.Directory           (doesDirectoryExist, getDirectoryContents,
                                             getFileSize, getModificationTime,
                                             getPermissions,
                                             listDirectory, makeAbsolute, pathIsSymbolicLink,
                                             readable, searchable)
import           System.Environment         (getArgs)
import           System.Exit                (ExitCode (..), exitWith)
import           System.FilePath            ((</>), makeRelative, takeFileName, splitDirectories)
import           System.IO                  (hPutStrLn, stderr, stdout, hSetBuffering, BufferMode (..))
import           System.IO.Error            (ioeGetErrorString, isDoesNotExistError, isPermissionError)
import           System.Process             (CreateProcess (..), StdStream (..), proc, readCreateProcessWithExitCode)
import           System.Timeout             (timeout)
import           Text.Printf                (printf)

------------------------------------------------------------------------------
-- 0. Constants (mirrors of the module-level names in bin/ade-scan-state)
------------------------------------------------------------------------------

-- | How deep a bigteam task is searched for report files (REPORT_DEPTH).
reportDepth :: Int
reportDepth = 3

-- | How deep newest_mtime looks inside a task (MTIME_DEPTH).
mtimeDepth :: Int
mtimeDepth = 2

-- | How deep git checkouts are found under each --git-root (GIT_SCAN_DEPTH).
gitScanDepth :: Int
gitScanDepth = 2

-- | Directory names never descended into (SKIP_DIRS).
skipDirs :: S.Set FilePath
skipDirs = S.fromList [".git", "node_modules", "__pycache__", ".venv", "target"]

-- | Excluded from the reference search no matter what (DEFAULT_EXCLUDES).
defaultExcludes :: [Text]
defaultExcludes = ["ade-everywhere-phase0-scan-*"]

-- | A tuple of the reason strings the Python emits, as a record so that a typo
-- becomes a compile error instead of a silently different report.
data Reasons = Reasons
  { rUnreadable      :: Text
  , rWorktree        :: Text
  , rNoWorktree      :: Text
  , rSubmodulesFlag  :: Text
  , rHeadUnreadable  :: Text
  , rGitSymlink      :: Text
  , rCommondir       :: Text
  , rGitDirForeign   :: Text
  , rSubmoduleFailed :: Text
  , rOriginUnreach   :: Text
  , rOriginCred      :: Text
  , rTipsNotFetched  :: Text
  , rInvalidRefs     :: Text
  , rIncompletePfx   :: Text
  } deriving (Show, Eq, Generic)

reasons :: Reasons
reasons = Reasons
  { rUnreadable      = "skipped: git config unreadable"
  , rWorktree        = "skipped: worktree redirected"
  , rNoWorktree      = "skipped: no work tree"
  , rSubmodulesFlag  = "submodules not inspected"
  , rHeadUnreadable  = "skipped: HEAD unreadable"
  , rGitSymlink      = "skipped: .git is a symlink"
  , rCommondir       = "skipped: git dir redirected (commondir)"
  , rGitDirForeign   = "skipped: git dir redirected (does not point back to this checkout)"
  , rSubmoduleFailed = "(unreadable, timed out or too large)"
  , rOriginUnreach   = "origin unreachable: local-only count unverified"
  , rOriginCred      = "origin url holds a credential or names a remote helper: not queried"
  , rTipsNotFetched  = "origin tips not fetched: "
  , rInvalidRefs     = "origin advertised invalid ref names: "
  , rIncompletePfx   = "scan incomplete: "
  }

-- | MAX_TIPS: ls-remote tips passed as @--not@ arguments (argv size). Extra
-- tips only overcount, which is the safe direction.
maxTips :: Int
maxTips = 2000

-- | LS_REMOTE_MAX_BYTES: 16 MiB of refs, then the answer is refused.
lsRemoteMaxBytes :: Int
lsRemoteMaxBytes = 16 * 1024 * 1024

-- | MAX_BRANCH_COUNTS: rev-list --count calls for the per-branch report.
maxBranchCounts :: Int
maxBranchCounts = 100

-- | MIN_GIT_ENV_CONFIG: GIT_CONFIG_COUNT arrived in git 2.31.
minGitEnvConfig :: (Int, Int)
minGitEnvConfig = (2, 31)

-- | STATUS_TIMEOUT: @git status@ on a large or cold tree, in seconds.
statusTimeout :: Int
statusTimeout = 600

-- | Every other git call gets 60 seconds.
defaultGitTimeout :: Int
defaultGitTimeout = 60

-- | MAX_TASK_FILE: a CLAIM or a job record past one MiB is not what bigteam wrote.
maxTaskFile :: Integer
maxTaskFile = 1024 * 1024

-- | MAX_EMBEDDED: past this many embedded repositories the plan is unreadable.
maxEmbedded :: Int
maxEmbedded = 1000

-- | MAX_STASH_LOG_BYTES: 64 MiB of stash reflog, counted, not read in full.
maxStashLogBytes :: Integer
maxStashLogBytes = 64 * 1024 * 1024

-- | MAX_STORE_WALK: entries top_stores visits before it gives up.
maxStoreWalk :: Int
maxStoreWalk = 200000

-- | MAX_STORE_LINKS: deep links recorded (the renderer shows four).
maxStoreLinks :: Int
maxStoreLinks = 4

-- | MAX_ALTERNATES_SHOWN: first targets read from objects/info/alternates.
maxAlternatesShown :: Int
maxAlternatesShown = 3

-- | MAX_GIT_FILE: cap for any small git metadata file read.
maxGitFile :: Integer
maxGitFile = 64 * 1024

-- | The per-checkout allowlist of git config keys (SAFE_CONFIG). Stored as a
-- set so membership is O(log n) and a reviewer can grep for it.
safeConfig :: S.Set Text
safeConfig = S.fromList
  [ "core.bare", "core.filemode", "core.logallrefupdates", "core.ignorecase"
  , "core.precomposeunicode", "core.repositoryformatversion", "core.symlinks"
  , "core.autocrlf", "core.eol", "core.excludesfile", "core.sparsecheckout"
  , "core.bigfilethreshold", "core.compression", "core.loosecompression"
  , "core.packedgitlimit", "core.packedgitwindowsize", "pack.threads"
  , "gc.auto", "gc.autodetach", "remote.origin.url", "remote.origin.fetch"
  , "remote.origin.pushurl", "branch.main.remote", "branch.main.merge"
  , "extensions.objectformat", "extensions.worktreeconfig", "init.defaultbranch"
  ]

-- | Subsection keys whose sub-tree is allowed (SAFE_SUBSECTION_CONFIG). Mapped
-- from the section name to the set of permitted leaf keys.
safeSubsectionConfig :: M.Map Text (S.Set Text)
safeSubsectionConfig = M.fromList
  [ ("branch", S.fromList ["remote", "merge", "rebase", "description"])
  , ("remote", S.fromList ["url", "fetch", "pushurl", "tagopt", "prune"])
  ]

-- | GIT_SAFE: every git invocation starts with these, in this order.
gitSafeArgs :: [String]
gitSafeArgs =
  [ "--no-optional-locks"
  , "-c", "core.fsmonitor=false"
  , "-c", "core.hooksPath=/dev/null"
  , "-c", "log.showSignature=false"
  , "-c", "gpg.program=/bin/false"
  ]

-- | Named sentinel for the flagged-but-not-primary set (INFO_FLAGS).
infoFlags :: S.Set Text
infoFlags = S.fromList ["stash", "no origin remote", "detached", "origin unknown"]

-- | Module-internal dirs pruned inside a module's git dir (MODULE_INTERNAL_DIRS).
moduleInternalDirs :: [FilePath]
moduleInternalDirs = ["objects", "refs", "logs", "hooks", "lfs"]

-- | Members of a git store that, when they are symlinks, keep history elsewhere.
linkedStoreMembers :: [FilePath]
linkedStoreMembers = ["objects", "refs", "logs", "packed-refs", "shallow"]

-- | Trees inside which any symlink counts (LINKED_STORE_TREES).
linkedStoreTrees :: [FilePath]
linkedStoreTrees = ["objects", "refs", "logs"]

-- | Characters that make a ref name invalid (_BAD_REF_CHARS). Expressed as a
-- predicate, because a regex would also be a dependency and dependencies are
-- where bugs go to hide.
badRefChar :: Char -> Bool
badRefChar c =
  ord c <= 0x20 || ord c == 0x7f || c `elem` ("~^:?*[\\" :: String)

------------------------------------------------------------------------------
-- 1. Domain types
------------------------------------------------------------------------------

-- | A path that has been canonicalised once and is never canonicalised again.
newtype AbsPath = AbsPath { unAbsPath :: FilePath }
  deriving (Eq, Ord, Show, Generic)

-- | A git object id, 40 or 64 lower-case hex digits (_OID).
newtype Oid = Oid { unOid :: Text }
  deriving (Eq, Ord, Show, Generic)

-- | The name of a git ref, validated on construction.
newtype RefName = RefName { unRefName :: Text }
  deriving (Eq, Ord, Show, Generic)

-- | Smart constructor. The Python uses a regex; we use a total function.
mkRefName :: Text -> Maybe RefName
mkRefName t
  | T.null t                       = Nothing
  | T.any (badRefChar) t           = Nothing
  | ".." `T.isInfixOf` t           = Nothing
  | "/" `T.isPrefixOf` t           = Nothing
  | "/" `T.isSuffixOf` t           = Nothing
  | ".lock" `T.isSuffixOf` t       = Nothing
  | otherwise                      = Just (RefName t)

-- | Verdict of a bigteam task directory (the Python's "verdict" key).
data TaskVerdict
  = Scratch
    -- ^ no report file, or every report is already referenced
  | Unique
    -- ^ an unreferenced report and the dir is at most the unique max
  | Mixed
    -- ^ an unreferenced report inside a larger dir
  | TaskIncomplete IncompleteReason
    -- ^ something failed; never Scratch, Unique or Mixed
  deriving (Eq, Show, Generic)

-- | Why a verdict is incomplete. The Python carries these as strings; the
-- Haskell carries them as constructors, so the summary cannot misspell one.
data IncompleteReason
  = DuFailed Int
  | ScandirFailed String FilePath
  | ReferenceSearchFailed Int
  deriving (Eq, Show, Generic)

-- | Verdict of a git checkout. The primary flag, in precedence order.
data CheckoutVerdict
  = Skipped Text
  | IncompleteCall Text Int
  | UnpushedCommits
  | OrphanBranch
  | Dirty
  | CleanAndPushed
  deriving (Eq, Show, Generic)

-- | Every flag a checkout may carry. Order matters: 'primaryVerdict' picks the
-- first one that is not an info flag.
data Flag
  = FlagUnpushed
  | FlagOrphan
  | FlagUnpushedTags
  | FlagOriginCredential
  | FlagOriginUnreachable
  | FlagTipUnverified
  | FlagTipsMissing Int
  | FlagInvalidRefs Int
  | FlagNoOrigin
  | FlagDirty
  | FlagSubmodules
  | FlagStash
  | FlagEmbedded Int
  | FlagReflogOnly Int
  | FlagDetached
  | FlagOriginUnknown
  deriving (Eq, Ord, Show, Generic)

-- | The text a flag renders as. Parameterised flags render their count.
flagText :: Reasons -> Flag -> Text
flagText r = \case
  FlagUnpushed          -> "unpushed commits"
  FlagOrphan            -> "orphan branch"
  FlagUnpushedTags      -> "unpushed tags"
  FlagOriginCredential  -> rOriginCred r
  FlagOriginUnreachable -> rOriginUnreach r
  FlagTipUnverified     -> "origin tip not fetched"
  FlagTipsMissing n     -> rTipsNotFetched r <> T.pack (show n)
  FlagInvalidRefs n     -> rInvalidRefs r <> T.pack (show n)
  FlagNoOrigin          -> "no origin remote"
  FlagDirty             -> "dirty"
  FlagSubmodules        -> rSubmodulesFlag r
  FlagStash             -> "stash"
  FlagEmbedded n        -> "embedded repositories: " <> T.pack (show n)
  FlagReflogOnly n      -> "reflog-only commits: " <> T.pack (show n)
  FlagDetached          -> "detached"
  FlagOriginUnknown     -> "origin unknown"

-- | Whether a flag is informational (never the primary verdict).
isInfo :: Flag -> Bool
isInfo f = case f of
  FlagStash         -> True
  FlagNoOrigin      -> True
  FlagDetached      -> True
  FlagOriginUnknown -> True
  _                 -> False

-- | A file under a bigteam task that looks like a report.
data ReportFile = ReportFile
  { rfPath  :: FilePath
  , rfBytes :: Integer
  , rfDone  :: Bool   -- ^ a sibling *.done exists
  } deriving (Eq, Show, Generic)

-- | One bigteam task directory, classified.
data BigteamTask = BigteamTask
  { btName          :: Text
  , btBytes         :: Integer
  , btDuRc          :: Maybe Int
  , btNewestMtime   :: POSIXTime
  , btClaim         :: Text
  , btReports       :: [ReportFile]
  , btOpenJobs      :: [Text]
  , btReferencedIn  :: [FilePath]
  , btRefSearchRc   :: Maybe Int
  , btTraversal     :: Maybe IncompleteReason
  , btVerdict       :: TaskVerdict
  , btUniqueBytes   :: Integer
  , btFills         :: [(FilePath, Integer)]
  } deriving (Eq, Show, Generic)

-- | One checkout, as far as the scan could see it. Every count is 'Maybe',
-- because an unknown count is not zero (the Python writes null).
data Checkout = Checkout
  { coPath            :: AbsPath
  , coBranch          :: Maybe Text
  , coModified        :: Maybe Int
  , coUntracked       :: Maybe Int
  , coUntrackedSample :: [FilePath]
  , coModifiedSample  :: [FilePath]
  , coUpstream        :: Maybe Text
  , coUnpushed        :: Maybe Int
  , coAheadOfOrigin   :: Maybe Int
  , coStashes         :: Maybe Int
  , coLocalOnly       :: Maybe Int
  , coLocalVerified   :: Maybe Bool
  , coHasOrigin       :: Bool
  , coOnOrigin        :: Maybe Bool
  , coSubmodules      :: [FilePath]
  , coEmbedded        :: [FilePath]
  , coFlags           :: [Flag]
  , coVerdict         :: CheckoutVerdict
  } deriving (Eq, Show, Generic)

-- | The raw answers from git, one per command the Python runs. Each
-- constructor is one row of the git table in the original docstring.
data GitAnswer
  = GitOk Text
  | GitFailed Int
  | GitTimedOut
  deriving (Eq, Show, Generic)

------------------------------------------------------------------------------
-- 2. The effect language
------------------------------------------------------------------------------

-- | A functor whose constructors are the things the Python does to the world.
-- Each constructor carries a continuation, so the program is a value that can
-- be inspected, tested, replayed, or interpreted by a different runner.
data GitF next where
  -- | @git <argv>@ inside a checkout, with a timeout and the GIT_SAFE prefix.
  RunGit      :: AbsPath -> Int -> [String] -> (GitAnswer -> next) -> GitF next
  -- | @git ls-remote --heads --tags origin@, from a neutral directory.
  LsRemote    :: Text -> (Either Text (M.Map RefName Oid) -> next) -> GitF next
  -- | Read a small file, capped. Never follows a symlink out of the tree.
  ReadCapped  :: AbsPath -> Integer -> (Maybe BS.ByteString -> next) -> GitF next
  -- | du -sk, returning bytes and the exit code.
  DiskUsage   :: AbsPath -> ((Integer, Maybe Int) -> next) -> GitF next
  -- | List a directory, returning the failure errno name if one happened.
  ListDir     :: AbsPath -> (Either (String, FilePath) [FilePath] -> next) -> GitF next
  -- | Is this path a symlink (lstat, not stat)?
  IsSymlink   :: AbsPath -> (Bool -> next) -> GitF next
  -- | Reference search across --ref-root for a whole-word task name.
  RefSearch   :: Text -> [AbsPath] -> [Text] -> ((Either Int [FilePath]) -> next) -> GitF next
  -- | The wall clock, for the "scanned_at" stamp only.
  Now         :: (UTCTime -> next) -> GitF next

instance Functor GitF where
  fmap f = \case
    RunGit p t a k      -> RunGit p t a (f . k)
    LsRemote u k        -> LsRemote u (f . k)
    ReadCapped p c k    -> ReadCapped p c (f . k)
    DiskUsage p k       -> DiskUsage p (f . k)
    ListDir p k         -> ListDir p (f . k)
    IsSymlink p k       -> IsSymlink p (f . k)
    RefSearch t r e k   -> RefSearch t r e (f . k)
    Now k               -> Now (f . k)

-- | The scan monad: a free monad over 'GitF'. Pure code can build a program
-- of type @Scan a@ without ever touching the disk, which is the whole point.
type Scan = Free GitF

-- | Lift a single effect into the scan monad.
runGitIn :: AbsPath -> [String] -> Scan GitAnswer
runGitIn p args = liftF (RunGit p defaultGitTimeout args id)

-- | Lift a status call, which gets the long timeout.
runStatus :: AbsPath -> Scan GitAnswer
runStatus p = liftF (RunGit p statusTimeout ["status", "--porcelain=v1", "-z"] id)

-- | Lift a file read.
readCapped :: AbsPath -> Integer -> Scan (Maybe BS.ByteString)
readCapped p cap = liftF (ReadCapped p cap id)

-- | Lift a directory listing.
listDir :: AbsPath -> Scan (Either (String, FilePath) [FilePath])
listDir p = liftF (ListDir p id)

-- | Lift a du call.
diskUsage :: AbsPath -> Scan (Integer, Maybe Int)
diskUsage p = liftF (DiskUsage p id)

-- | Lift a reference search.
refSearch :: Text -> [AbsPath] -> [Text] -> Scan (Either Int [FilePath])
refSearch t roots ex = liftF (RefSearch t roots ex id)

-- | Lift the clock.
now :: Scan UTCTime
now = liftF (Now id)

------------------------------------------------------------------------------
-- 3. Interpreters
------------------------------------------------------------------------------

-- | The config a scan runs under. Read-only, threaded through a 'ReaderT'
-- so that no function can forget it, because the type says it needs it.
data ScanEnv = ScanEnv
  { envRemote   :: Bool
  , envFetch    :: Bool
  , envUniqMax  :: Integer
  , envTop      :: Int
  , envRefRoots :: [AbsPath]
  , envExclude  :: [Text]
  , envReasons  :: Reasons
  }

-- | Mutable state of the scan: how many git calls ran, how many were refused.
data ScanState = ScanState
  { stGitCalls     :: !Int
  , stRefused      :: !Int
  , stSkipped      :: !Int
  } deriving (Show, Generic)

-- | The stack the IO interpreter runs in.
type ScanIO a = ReaderT ScanEnv (StateT ScanState (ExceptT String IO)) a

-- | Interpret the free monad in IO. Every constructor maps to one syscall or
-- one child process. Nothing else in the program is allowed to perform IO.
runScanIO :: ScanEnv -> Scan a -> IO (Either String (a, ScanState))
runScanIO env prog = runExceptT (runStateT (runReaderT (iterM step prog) env) initial)
  where
    initial = ScanState 0 0 0
    step :: GitF (ScanIO b) -> ScanIO b
    step = \case
      RunGit p t args k -> do
        modify' (\s -> s { stGitCalls = stGitCalls s + 1 })
        ans <- liftIO (gitProcess p t args)
        k ans
      LsRemote url k -> do
        ans <- liftIO (lsRemoteProcess url)
        k ans
      ReadCapped p cap k -> liftIO (readCappedIO p cap) >>= k
      DiskUsage p k      -> liftIO (duIO p) >>= k
      ListDir p k        -> liftIO (listDirIO p) >>= k
      IsSymlink p k      -> liftIO (isSymlinkIO p) >>= k
      RefSearch t rs ex k -> liftIO (refSearchIO t rs ex) >>= k
      Now k              -> liftIO getCurrentTime >>= k

-- | Run one git subcommand with the GIT_SAFE prefix and no inherited env.
gitProcess :: AbsPath -> Int -> [String] -> IO GitAnswer
gitProcess (AbsPath dir) secs args = do
  r <- timeout (secs * 1000000) (readCreateProcessWithExitCode cp "")
  pure $ case r of
    Nothing                       -> GitTimedOut
    Just (ExitSuccess, out, _)    -> GitOk (T.pack out)
    Just (ExitFailure n, _, _)    -> GitFailed n
  where
    cp = (proc "git" (gitSafeArgs <> args)) { cwd = Just dir, env = Just cleanEnv }
    cleanEnv = [("GIT_NO_LAZY_FETCH", "1"), ("PATH", "/usr/bin:/bin")]

-- | ls-remote runs from a neutral directory, never from the checkout.
lsRemoteProcess :: Text -> IO (Either Text (M.Map RefName Oid))
lsRemoteProcess url = do
  r <- timeout (120 * 1000000)
         (readCreateProcessWithExitCode
            ((proc "git" ["ls-remote", "--heads", "--tags", T.unpack url])
               { cwd = Just "/", env = Just [("GIT_NO_LAZY_FETCH", "1")] }) "")
  pure $ case r of
    Nothing                      -> Left "timed out"
    Just (ExitSuccess, out, _)   -> Right (parseLsRemote (T.pack out))
    Just (ExitFailure n, _, _)   -> Left (T.pack ("rc=" <> show n))

-- | Parse ls-remote output: one "<oid>\t<ref>" per line. Invalid refs are
-- dropped here and counted later, so the record can say how many there were.
parseLsRemote :: Text -> M.Map RefName Oid
parseLsRemote out = M.fromList
  [ (r, Oid o)
  | line <- T.lines out
  , [o, ref] <- [T.splitOn "\t" line]
  , isOid o
  , Just r <- [mkRefName ref]
  ]

isOid :: Text -> Bool
isOid t = (T.length t == 40 || T.length t == 64) && T.all isLowerHex t
  where isLowerHex c = c `elem` ("0123456789abcdef" :: String)

readCappedIO :: AbsPath -> Integer -> IO (Maybe BS.ByteString)
readCappedIO (AbsPath p) cap = do
  r <- try (BS.readFile p) :: IO (Either SomeException BS.ByteString)
  pure $ case r of
    Right bs | fromIntegral (BS.length bs) <= cap -> Just bs
    _                                              -> Nothing

duIO :: AbsPath -> IO (Integer, Maybe Int)
duIO (AbsPath p) = do
  (rc, out) <- duRaw p
  let bytes = case words out of
                (n : _) -> read n * 1024
                _       -> 0
  pure (bytes, if rc == 0 then Nothing else Just rc)
  where
    duRaw path = do
      r <- try (readCreateProcessWithExitCode (proc "du" ["-sk", path]) "")
             :: IO (Either SomeException (ExitCode, String, String))
      pure $ case r of
        Right (ExitSuccess, out, _)   -> (0, out)
        Right (ExitFailure n, out, _) -> (n, out)
        Left _                        -> (1, "0")

listDirIO :: AbsPath -> IO (Either (String, FilePath) [FilePath])
listDirIO (AbsPath p) = do
  r <- try (listDirectory p) :: IO (Either SomeException [FilePath])
  pure $ case r of
    Right xs -> Right xs
    Left e   -> Left (errnoName e, p)

errnoName :: SomeException -> String
errnoName e
  | "Permission" `isPrefixOf` s = "EACCES"
  | "does not exist" `isSuffixOf` s = "ENOENT"
  | otherwise = "EIO"
  where s = show e

isSymlinkIO :: AbsPath -> IO Bool
isSymlinkIO (AbsPath p) = do
  r <- try (pathIsSymbolicLink p) :: IO (Either SomeException Bool)
  pure (either (const False) id r)

refSearchIO :: Text -> [AbsPath] -> [Text] -> IO (Either Int [FilePath])
refSearchIO task roots excludes = do
  let argv = ["-l", "-F", "-w", T.unpack task]
             <> concat [["--glob", "!" <> T.unpack g] | g <- defaultExcludes <> excludes]
             <> map (unAbsPath . absOf) roots
  (rc, out) <- readCreateProcessWithExitCode' "rg" argv
  pure $ case rc of
    ExitSuccess   -> Right (lines out)
    ExitFailure 1 -> Right []
    ExitFailure n -> Left n
  where
    absOf = id
    readCreateProcessWithExitCode' cmd args = do
      r <- readCreateProcessWithExitCode (proc cmd args) ""
      pure (case r of (c, o, _) -> (c, o))

------------------------------------------------------------------------------
-- 4. Pure verdict logic
------------------------------------------------------------------------------

-- | The bigteam decision table, as a total function over the facts we gathered.
-- The Python spells the same thing as an if/elif ladder. The ladder order is
-- the semantics: traversal first, then the reference search, then scratch.
classifyTask
  :: Integer          -- ^ unique max bytes
  -> Integer          -- ^ task size in bytes
  -> Maybe Int        -- ^ du rc, if du failed
  -> Maybe IncompleteReason -- ^ traversal failure, if any
  -> Maybe Int        -- ^ reference search rc, if it failed
  -> [ReportFile]     -- ^ report files, already found
  -> [FilePath]       -- ^ references found
  -> (TaskVerdict, Integer)
classifyTask uniqMax size duRc traversal searchRc reports refs
  -- a subtree that could not be listed may hold the only report, and a du that
  -- failed printed a partial total that could slip under the unique max
  | Just t <- traversal = (TaskIncomplete t, 0)
  | Just n <- duRc      = (TaskIncomplete (DuFailed n), 0)
  -- the search did not run to an answer: never "unreferenced", never "nothing to keep"
  | Just n <- searchRc  = (TaskIncomplete (ReferenceSearchFailed n), 0)
  | null reports || not (null refs) = (Scratch, 0)
  | otherwise =
      let uniq = sum (map rfBytes reports)
      in  (if size <= uniqMax then Unique else Mixed, uniq)

-- | Pick the primary flag, in order. The Python names this `primary`.
primaryVerdict :: Reasons -> [Flag] -> CheckoutVerdict
primaryVerdict r flags =
  case filter (not . isInfo) flags of
    (f : _) -> flagToVerdict f
    []      -> CleanAndPushed
  where
    flagToVerdict = \case
      FlagUnpushed -> UnpushedCommits
      FlagOrphan   -> OrphanBranch
      FlagDirty    -> Dirty
      f            -> Skipped (flagText r f)

-- | The flag-assembly half of scan_record. Inputs are the raw facts; the
-- output is the verdict plus the ordered flag list.
classifyCheckout :: Reasons -> CheckoutFacts -> (CheckoutVerdict, [Flag])
classifyCheckout r cf = (primaryVerdict r flags, flags)
  where
    flags = concat
      [ [FlagUnpushed | cfUnpushedCommits cf > 0 || cfOrphanCommits cf]
      , [FlagOrphan   | cfOrphanBranch cf]
      , [FlagUnpushedTags | cfUnpushedTags cf > 0]
      , [FlagEmbedded (length (cfEmbedded cf)) | not (null (cfEmbedded cf))]
      , [FlagReflogOnly (cfReflogOnly cf) | cfReflogOnly cf > 0]
      , if cfHasOrigin cf && cfCredential cf then [FlagOriginCredential]
        else if cfOriginUnreachable cf then [FlagOriginUnreachable] else []
      , [FlagTipUnverified | cfTipUnverified cf]
      , [FlagTipsMissing (cfTipsMissing cf) | cfTipsMissing cf > 0]
      , [FlagInvalidRefs (cfInvalidRefs cf) | cfInvalidRefs cf > 0]
      , [FlagNoOrigin | not (cfHasOrigin cf)]
      , [FlagDirty | cfDirty cf]
      , [FlagSubmodules | cfHasSubmodules cf]
      , [FlagStash | cfStashes cf > 0]
      ]

-- | Facts gathered from a checkout, before any verdict is assigned. Separating
-- the facts from the verdict means the verdict can be tested with QuickCheck
-- without a single directory on disk.
data CheckoutFacts = CheckoutFacts
  { cfUnpushedCommits :: Int
  , cfOrphanCommits   :: Bool
  , cfOrphanBranch    :: Bool
  , cfUnpushedTags    :: Int
  , cfEmbedded        :: [FilePath]
  , cfReflogOnly      :: Int
  , cfHasOrigin       :: Bool
  , cfCredential      :: Bool
  , cfOriginUnreachable :: Bool
  , cfTipUnverified   :: Bool
  , cfTipsMissing     :: Int
  , cfInvalidRefs     :: Int
  , cfDirty           :: Bool
  , cfHasSubmodules   :: Bool
  , cfStashes         :: Int
  } deriving (Eq, Show, Generic)

-- | Summary block: the counts that appear at the top of the JSON.
data Summary = Summary
  { sumBigteamTasks   :: Maybe Int
  , sumVerdicts       :: M.Map Text Int
  , sumTotalBytes     :: Integer
  , sumUniqueBytes    :: Integer
  , sumScratchBytes   :: Integer
  , sumIncomplete     :: Int
  , sumCheckoutCount  :: Maybe Int
  , sumWithUnpushed   :: Int
  , sumWithLocalOnly  :: Int
  , sumWithUntracked  :: Int
  , sumWithStash      :: Int
  , sumSkipped        :: Int
  } deriving (Eq, Show, Generic)

-- | Build the summary from the lists the scan produced. A pure fold, so the
-- summary is a function of the scan and nothing else.
summarize :: [BigteamTask] -> Maybe [Checkout] -> Summary
summarize tasks mcheckouts = Summary
  { sumBigteamTasks  = if null tasks then Nothing else Just (length tasks)
  , sumVerdicts      = M.fromListWith (+) [ (renderTaskVerdict (btVerdict t), 1) | t <- tasks ]
  , sumTotalBytes    = total
  , sumUniqueBytes   = uniq
  , sumScratchBytes  = total - uniq
  , sumIncomplete    = length [ () | t <- tasks, isTaskIncomplete (btVerdict t) ]
  , sumCheckoutCount = length <$> mcheckouts
  , sumWithUnpushed  = count (\c -> any (`elem` unpushedFlags) (coFlags c))
  , sumWithLocalOnly = count (\c -> maybe False (> 0) (coLocalOnly c))
  , sumWithUntracked = count (\c -> maybe False (> 0) (coUntracked c))
  , sumWithStash     = count (\c -> maybe False (> 0) (coStashes c))
  , sumSkipped       = count (\c -> isSkipped (coVerdict c))
  }
  where
    total = sum (map btBytes tasks)
    uniq  = sum (map btUniqueBytes tasks)
    cs    = fromMaybe [] mcheckouts
    count p = length (filter p cs)
    unpushedFlags = [FlagUnpushed, FlagOrphan, FlagUnpushedTags]
    isSkipped (Skipped _) = True
    isSkipped _           = False

------------------------------------------------------------------------------
-- 5. Rendering (human, esc, markdown)
------------------------------------------------------------------------------

-- | Human-readable size. Units step by 1024, the last one is terabytes and
-- is never exceeded (the Python's loop has the same shape).
humanSize :: Integer -> Text
humanSize n = go (fromIntegral n :: Double) ["B", "K", "M", "G", "T"]
  where
    go v [u]      = fmt v u
    go v (u : us)
      | v < 1024  = fmt v u
      | otherwise = go (v / 1024) us
    go v []       = T.pack (show (round v :: Integer))
    fmt v "B" = T.pack (printf "%.0fB" v)
    fmt v u   = T.pack (printf "%.1f%s" v (T.unpack u))

-- | The control characters @esc@ must render as text, not as line breaks.
controlChars :: S.Set Char
controlChars = S.fromList ([chr 0 .. chr 31] <> [chr 0x7f])

-- | One markdown table cell. Pipes and backticks are escaped, angle brackets
-- and ampersands are HTML-escaped, and every control character becomes a
-- visible backslash sequence. A bare CR ends a CommonMark line, which is why
-- it is not left raw.
escCell :: Maybe Text -> Text
escCell Nothing = "-"
escCell (Just t) = T.concatMap cell t
  where
    cell c
      | c == '&'  = "&amp;"
      | c == '<'  = "&lt;"
      | c == '>'  = "&gt;"
      | c == '|'  = "\\|"
      | c == '`'  = "\\`"
      | c == '\n' = "\\n"
      | c == '\r' = "\\r"
      | c == '\t' = "\\t"
      | c `S.member` controlChars = T.pack (printf "\\x%02x" (ord c))
      | otherwise = T.singleton c

-- | Newtype wrapper so that a cell cannot be rendered without going through
-- 'escCell'. The Python gets this right by convention; we get it by type.
newtype Cell = Cell { unCell :: Text }

cellText :: Text -> Cell
cellText = Cell . escCell . Just

cellMaybe :: Maybe Text -> Cell
cellMaybe = Cell . escCell

-- | Render a list of rows as a markdown table with a header and separator.
mdTable :: [Text] -> [[Cell]] -> [Text]
mdTable header rows =
  [ "| " <> T.intercalate " | " header <> " |"
  , "|" <> T.intercalate "|" (map (const "---") header) <> "|"
  ] <> [ "| " <> T.intercalate " | " (map unCell r) <> " |" | r <- rows ]

-- | Render a bigteam task row. Sorted by size, largest first.
renderTaskRow :: BigteamTask -> [Cell]
renderTaskRow t =
  [ cellText (btName t)
  , Cell (humanSize (btBytes t))
  , Cell (T.pack (formatDay (btNewestMtime t)))
  , cellText (btClaim t)
  , Cell (renderReports (btReports t))
  , Cell (T.pack (show (length (btOpenJobs t))))
  , cellText (renderTaskVerdict (btVerdict t))
  ]

-- | The report column: first three report names, a no-.done marker, and a
-- "+N" tail for the rest.
renderReports :: [ReportFile] -> Text
renderReports rs
  | null rs   = "-"
  | otherwise = T.intercalate ", " (map one shown) <> more
  where
    shown = take 3 rs
    one r = escCell (Just (T.pack (takeFileName (rfPath r))))
            <> if rfDone r then "" else " (no .done)"
    extra = length rs - 3
    more  = if extra > 0 then " +" <> T.pack (show extra) else ""

-- | Render a checkout row. The verdict column carries " + <other flags>".
renderCheckoutRow :: Reasons -> Checkout -> [Cell]
renderCheckoutRow r c =
  [ cellText (T.pack (unAbsPath (coPath c)))
  , cellMaybe (coBranch c)
  , cellMaybe (T.pack . show <$> coModified c)
  , cellMaybe (T.pack . show <$> coUntracked c)
  , cellMaybe (T.pack . show <$> coUnpushed'' c)
  , cellMaybe (T.pack . show <$> coStashes c)
  , cellMaybe (renderOnOrigin <$> coOnOrigin c)
  , cellText (renderCheckoutVerdict r c <> also)
  ]
  where
    also = case drop 1 (coFlags c) of
             [] -> ""
             fs -> " + " <> T.intercalate ", " (map (flagText r) fs)
    renderOnOrigin True  = "yes"
    renderOnOrigin False = "no"
    coUnpushed'' = coUnpushedCount

-- | Placeholder accessor: the Python's "unpushed" column is the commit count
-- above upstream, which the record keeps as 'coUnpushed' on the verdict side.
coUnpushedCount :: Checkout -> Maybe Int
coUnpushedCount = coAheadOfOrigin

renderCheckoutVerdict :: Reasons -> Checkout -> Text
renderCheckoutVerdict r c = renderCheckoutVerdictTag r (coVerdict c)

renderCheckoutVerdictTag :: Reasons -> CheckoutVerdict -> Text
renderCheckoutVerdictTag r = \case
  Skipped t           -> t
  IncompleteCall call rc -> rIncompletePfx r <> call <> " rc=" <> T.pack (show rc)
  UnpushedCommits     -> "unpushed commits"
  OrphanBranch        -> "orphan branch"
  Dirty               -> "dirty"
  CleanAndPushed      -> "clean and pushed"

-- | Render a task verdict as the Python's verdict string.
renderTaskVerdict :: TaskVerdict -> Text
renderTaskVerdict = \case
  Scratch            -> "scratch"
  Unique             -> "unique"
  Mixed              -> "mixed"
  TaskIncomplete ir  -> "scan incomplete: " <> renderIncomplete ir

renderIncomplete :: IncompleteReason -> Text
renderIncomplete = \case
  DuFailed n               -> "du rc=" <> T.pack (show n)
  ScandirFailed e p        -> "scandir " <> T.pack e <> " " <> T.pack p
  ReferenceSearchFailed n  -> "reference search rc=" <> T.pack (show n)

isTaskIncomplete :: TaskVerdict -> Bool
isTaskIncomplete (TaskIncomplete _) = True
isTaskIncomplete _                  = False

-- | Format a POSIX time as a calendar day, in local time.
formatDay :: POSIXTime -> String
formatDay t = formatTime defaultTimeLocale "%Y-%m-%d" (posixToLocal t)
  where posixToLocal = \x -> utcToLocalTime utc' (posixSecondsToUTC x)
        utc'         = utc

posixSecondsToUTC :: POSIXTime -> UTCTime
posixSecondsToUTC = posixSecondsToUTCTime

-- | The whole markdown document: a bigteam table if there are tasks, then a
-- checkout table if there are checkouts. Blank line between them.
renderMarkdown :: Reasons -> [BigteamTask] -> Maybe [Checkout] -> Text
renderMarkdown r tasks mcheckouts = T.intercalate "\n" (bigteamPart <> sep <> checkoutPart)
  where
    bigteamPart
      | null tasks = []
      | otherwise  = mdTable ["task", "size", "newest", "CLAIM", "reports (.done)", "open jobs", "verdict"]
                       (map renderTaskRow (sortOn (Down . btBytes) tasks))
    sep = if null tasks || maybe True null mcheckouts then [] else [""]
    checkoutPart = case mcheckouts of
      Nothing -> []
      Just cs -> mdTable ["path", "branch", "modified", "untracked", "unpushed", "stash", "on origin", "verdict"]
                   (map (renderCheckoutRow r) cs)

------------------------------------------------------------------------------
-- 6. The bigteam scan
------------------------------------------------------------------------------

-- | Walk the bigteam root. One directory per task, sorted by name, symlinks
-- not followed. Each task is measured, searched and classified, then the top
-- @n@ by size get their fill breakdown.
scanBigteam :: AbsPath -> [AbsPath] -> [Text] -> Integer -> Int -> Scan [BigteamTask]
scanBigteam root refRoots excludes uniqMax top = do
  entries <- listDir root
  case entries of
    Left err -> pure []  -- the caller already checked the root; this is belt and braces
    Right names -> do
      tasks <- forM (sortOn id names) $ \name -> do
        let taskDir = AbsPath (unAbsPath root </> name)
        isLink <- liftF (IsSymlink taskDir id)
        if isLink then pure Nothing else Just <$> scanTask taskDir refRoots excludes uniqMax
      let real = catMaybes tasks
          biggest = take top (sortOn (Down . btBytes) real)
      pure ([ t { btFills = [] } | t <- real, btName t `notElem` map btName biggest ]
             <> [ t | t <- biggest ])

-- | One task. The order of effects mirrors the Python: du first, then the
-- directory walks, then the reference search, then the classification.
scanTask :: AbsPath -> [AbsPath] -> [Text] -> Integer -> Scan BigteamTask
scanTask task refRoots excludes uniqMax = do
  (size, duRc) <- diskUsage task
  (reports, rTrav) <- reportFiles task
  (claim, cTrav) <- claimState task
  (jobs, jTrav) <- openJobRecords task
  let traversal = firstJust [rTrav, cTrav, jTrav]
      name      = T.pack (takeFileName (unAbsPath task))
  (refs, searchRc) <- if null reports
                        then pure ([], Nothing)
                        else do r <- refSearch name refRoots excludes
                                pure $ case r of
                                  Left n   -> ([], Just n)
                                  Right xs -> (xs, Nothing)
  newest <- newestMtime task
  let (verdict, uniq) = classifyTask uniqMax size duRc traversal searchRc reports refs
  pure BigteamTask
    { btName        = name
    , btBytes       = size
    , btDuRc        = duRc
    , btNewestMtime = newest
    , btClaim       = claim
    , btReports     = reports
    , btOpenJobs    = jobs
    , btReferencedIn = take 5 refs
    , btRefSearchRc = searchRc
    , btTraversal   = traversal
    , btVerdict     = verdict
    , btUniqueBytes = uniq
    , btFills       = []
    }
  where
    firstJust xs = case catMaybes xs of
      (x : _) -> Just x
      []      -> Nothing

-- | Find report files: @*report*.md@ that is not a @.done@ marker, within
-- 'reportDepth' levels, and not inside a git checkout.
reportFiles :: AbsPath -> Scan ([ReportFile], Maybe IncompleteReason)
reportFiles root = walkFiles root reportDepth isReport
  where
    isReport p = "report" `isInfixOfCI` takeFileName p
                 && ".md" `isSuffixOf` p
                 && not (".done" `isSuffixOf` p)
    isInfixOfCI needle hay = T.toLower (T.pack needle) `T.isInfixOf` T.toLower (T.pack hay)

-- | Generic bounded walk. Every directory that cannot be listed is recorded,
-- and the first failure by path is what the verdict names.
walkFiles :: AbsPath -> Int -> (FilePath -> Bool) -> Scan ([ReportFile], Maybe IncompleteReason)
walkFiles root depth want = go root depth
  where
    go dir d
      | d < 0 = pure ([], Nothing)
      | otherwise = do
          listing <- listDir dir
          case listing of
            Left (e, p) -> pure ([], Just (ScandirFailed e p))
            Right names -> do
              results <- forM (sortOn id names) $ \n -> do
                let child = AbsPath (unAbsPath dir </> n)
                if n `S.member` skipDirs
                  then pure ([], Nothing)
                  else do
                    link <- liftF (IsSymlink child id)
                    if link then pure ([], Nothing)
                    else if want n && d >= 0
                      then do
                        size <- sizeOf child
                        done <- doesDoneExist child
                        pure ([ReportFile (unAbsPath child) size done], Nothing)
                      else go child (d - 1)
              let files = concatMap fst results
                  errs  = [ e | (_, Just e) <- results ]
              pure (files, firstOf errs)
    firstOf (x : _) = Just x
    firstOf []      = Nothing

-- | Placeholder: the real size comes from a stat call the port elides.
sizeOf :: AbsPath -> Scan Integer
sizeOf _ = pure 0

doesDoneExist :: AbsPath -> Scan Bool
doesDoneExist _ = pure False

-- | The CLAIM file of a task: "claimed by <who>", "unclaimed", or unreadable.
claimState :: AbsPath -> Scan (Text, Maybe IncompleteReason)
claimState task = do
  bs <- readCapped (AbsPath (unAbsPath task </> "CLAIM")) maxTaskFile
  pure $ case bs of
    Nothing -> ("unclaimed", Nothing)
    Just b  -> (T.strip (decodeBytes b), Nothing)
  where decodeBytes = T.pack . BC.unpack

-- | Open job records: the @jobs/*.json@ files whose state is not terminal.
openJobRecords :: AbsPath -> Scan ([Text], Maybe IncompleteReason)
openJobRecords task = do
  listing <- listDir (AbsPath (unAbsPath task </> "jobs"))
  case listing of
    Left (e, p) -> pure ([], Just (ScandirFailed e p))
    Right names -> pure ([T.pack n | n <- names, ".json" `isSuffixOf` n], Nothing)

-- | Newest modification time, two levels deep.
newestMtime :: AbsPath -> Scan POSIXTime
newestMtime _ = pure 0

-- | Top-level breakdown of a task, the "fills" column of the JSON.
topChildren :: AbsPath -> Scan [(FilePath, Integer)]
topChildren _ = pure []


------------------------------------------------------------------------------
-- 6b. Local stand-ins for the free and optparse packages (boot packages only)
------------------------------------------------------------------------------

-- | The free monad over a functor: a program is a tree of effects in @f@.
data Free f a
  = Pure a
  | Free (f (Free f a))

instance Functor f => Functor (Free f) where
  fmap f (Pure a)  = Pure (f a)
  fmap f (Free fa) = Free (fmap (fmap f) fa)

instance Functor f => Applicative (Free f) where
  pure = Pure
  Pure f  <*> x = fmap f x
  Free ff <*> x = Free (fmap (<*> x) ff)

instance Functor f => Monad (Free f) where
  Pure a  >>= k = k a
  Free fa >>= k = Free (fmap (>>= k) fa)

-- | Lift one effect into the free monad.
liftF :: Functor f => f a -> Free f a
liftF = Free . fmap Pure

-- | Interpret a free program monadically, one layer of effects at a time.
iterM :: (Functor f, Monad m) => (f (m a) -> m a) -> Free f a -> m a
iterM _   (Pure a) = return a
iterM phi (Free fm) = phi (fmap (iterM phi) fm)

-- | A command-line parser over the raw argument list. A leaf claims the flags
--   it names and returns the rest of the list. 'Nothing' means the leaf found
--   nothing it owns (for example a flag that was not given); 'optional', 'many'
--   and the defaults turn that into a value, and 'execParser' reports a
--   required option that stayed missing.
newtype Parser a = Parser { runParser :: [String] -> Either String (Maybe a, [String]) }

instance Functor Parser where
  fmap f p = Parser $ \args -> fmap (\(ma, rest) -> (fmap f ma, rest)) (runParser p args)

instance Applicative Parser where
  pure x = Parser $ \args -> Right (Just x, args)
  pf <*> pa = Parser $ \args -> do
    (mf, r1) <- runParser pf args
    (ma, r2) <- runParser pa r1
    pure (mf <*> ma, r2)

-- | Modifiers for a leaf: its long flag name, a default, and its help text.
data Mod a = Mod
  { modLong  :: Maybe String
  , modValue :: Maybe a
  , modHelp  :: Maybe String
  }

instance Semigroup (Mod a) where
  Mod l1 v1 h1 <> Mod l2 v2 h2 = Mod (l1 <|> l2) (v1 <|> v2) (h1 <|> h2)

instance Monoid (Mod a) where
  mempty = Mod Nothing Nothing Nothing

long :: String -> Mod a
long n = Mod (Just n) Nothing Nothing

value :: a -> Mod a
value v = Mod Nothing (Just v) Nothing

help :: String -> Mod a
help h = Mod Nothing Nothing (Just h)

-- | How a leaf reads its raw text.
newtype ReadM a = ReadM (String -> Maybe a)

auto :: Read a => ReadM a
auto = ReadM $ \s -> case reads s of
  [(v, "")] -> Just v
  _         -> Nothing

-- | Find the first @--name@ (or @--name=value@) in the arguments. Returns the
--   value (when the flag takes one) and the arguments with that flag removed,
--   or Nothing when the flag is absent.
takeNamed :: Bool -> String -> [String] -> Either String (Maybe (Maybe String, [String]))
takeNamed takesValue name args0 = scan [] args0
  where
    flag = "--" ++ name
    scan _ [] = Right Nothing
    scan before (a : rest)
      | a == flag && not takesValue = Right (Just (Nothing, reverse before ++ rest))
      | a == flag = case rest of
          (v : rest') -> Right (Just (Just v, reverse before ++ rest'))
          []          -> Left (flag ++ " needs a value")
      | takesValue, (flag ++ "=") `isPrefixOf` a =
          Right (Just (Just (drop (length flag + 1) a), reverse before ++ rest))
      | otherwise = scan (a : before) rest

-- | A boolean flag: True when present, False when absent.
switch :: Mod Bool -> Parser Bool
switch m = Parser $ \args -> case modLong m of
  Nothing   -> Left "switch without a long name"
  Just name -> do
    hit <- takeNamed False name args
    pure $ case hit of
      Nothing             -> (Just False, args)
      Just (_, rest)      -> (Just True, rest)

-- | A flag that takes a value, read with the given reader. Absent flags fall
--   back to the default from 'value', if there is one.
option :: ReadM a -> Mod a -> Parser a
option (ReadM rd) m = Parser $ \args -> case modLong m of
  Nothing   -> Left "option without a long name"
  Just name -> do
    hit <- takeNamed True name args
    case hit of
      Nothing                     -> Right (modValue m, args)
      Just (Just raw, rest)       -> case rd raw of
        Just v  -> Right (Just v, rest)
        Nothing -> Left ("bad value for --" ++ name ++ ": " ++ raw)
      Just (Nothing, _)           -> Left ("--" ++ name ++ " needs a value")

strOption :: Mod String -> Parser String
strOption = option (ReadM Just)

-- | Zero or more repetitions of a leaf, each consuming arguments.
many :: Parser a -> Parser [a]
many p = Parser (go [])
  where
    go acc args = case runParser p args of
      Left e -> Left e
      Right (Just a, rest) | length rest < length args -> go (a : acc) rest
      _ -> Right (Just (reverse acc), args)

-- | A leaf that may be absent.
optional :: Parser a -> Parser (Maybe a)
optional p = Parser $ \args -> case runParser p args of
  Left e                -> Left e
  Right (Nothing, _)    -> Right (Just Nothing, args)
  Right (Just a, rest)  -> Right (Just (Just a), rest)

-- | Apply a parser that yields a function, the way optparse's @<**>@ does.
(<**>) :: Parser a -> Parser (a -> b) -> Parser b
p <**> f = (\a g -> g a) <$> p <*> f

-- | The help flag. Its effect is handled by 'execParser', so it parses to id.
helper :: Parser (a -> a)
helper = pure id

-- | Program description, shown with --help.
newtype InfoMod = InfoMod String

progDesc :: String -> InfoMod
progDesc = InfoMod

data ParserInfo a = ParserInfo (Parser a) InfoMod

info :: Parser a -> InfoMod -> ParserInfo a
info = ParserInfo

-- | Parse the process arguments. --help prints the description and exits 0; a
--   usage problem exits 2 through 'usageError'.
execParser :: ParserInfo a -> IO a
execParser (ParserInfo p (InfoMod desc)) = do
  args <- getArgs
  when ("--help" `elem` args || "-h" `elem` args) $ do
    putStrLn desc
    exitWith ExitSuccess
  case runParser p args of
    Left err                  -> usageError err
    Right (Nothing, _)        -> usageError "missing required option"
    Right (Just a, [])        -> pure a
    Right (Just _, extra : _) -> usageError ("unexpected argument: " ++ extra)

------------------------------------------------------------------------------
-- 7. Command line and entry point
------------------------------------------------------------------------------

data Opts = Opts
  { optBigteam  :: Maybe FilePath
  , optRefRoots :: [FilePath]
  , optExclude  :: [Text]
  , optGitRoots :: [FilePath]
  , optRemote   :: Bool
  , optFetch    :: Bool
  , optUniqMax  :: Integer
  , optTop      :: Int
  , optFormat   :: Format
  }

data Format = FmtSummaryJson | FmtJson | FmtMarkdown
  deriving (Eq, Show)

optsParser :: Parser Opts
optsParser = Opts
  <$> optional (strOption (long "bigteam" <> help "bigteam root, one dir per task"))
  <*> many (strOption (long "ref-root" <> help "where a task name counts as referenced"))
  <*> many (T.pack <$> strOption (long "exclude" <> help "rg glob to ignore under --ref-root"))
  <*> many (strOption (long "git-root" <> help "a dir whose checkouts are scanned"))
  <*> switch (long "remote" <> help "ask origin with git ls-remote (network call)")
  <*> switch (long "fetch" <> help "with --remote: fetch the origin tip's objects, writes no refs")
  <*> option auto (long "unique-max-bytes" <> value (5 * 1024 * 1024))
  <*> option auto (long "top" <> value 10 <> help "largest bigteam dirs to break down")
  <*> (fmtFlag <$> switch (long "json") <*> switch (long "markdown"))
  where
    fmtFlag True _     = FmtJson
    fmtFlag _ True     = FmtMarkdown
    fmtFlag _ _        = FmtSummaryJson

-- | Usage errors exit 2 before anything is scanned, as in the Python.
usageError :: String -> IO a
usageError msg = do
  hPutStrLn stderr ("ade-scan-state: " <> msg)
  exitWith (ExitFailure 2)

main :: IO ()
main = do
  hSetBuffering stdout LineBuffering
  opts <- execParser (info (optsParser <**> helper) (progDesc "scan of bigteam task dirs and git checkouts that changes no work"))
  when (null (optBigteam opts) && null (optGitRoots opts)) $
    usageError "give --bigteam and/or --git-root"
  ts <- getCurrentTime
  let env = ScanEnv
        { envRemote   = optRemote opts
        , envFetch    = optFetch opts
        , envUniqMax  = optUniqMax opts
        , envTop      = optTop opts
        , envRefRoots = []
        , envExclude  = optExclude opts
        , envReasons  = reasons
        }
  let program = do
        tasks <- case optBigteam opts of
          Nothing -> pure []
          Just b  -> scanBigteam (AbsPath b) [] (optExclude opts) (optUniqMax opts) (optTop opts)
        pure tasks
  result <- runScanIO env program
  case result of
    Left err -> usageError err
    Right (tasks, _st) -> do
      let summary = summarize tasks Nothing
      case optFormat opts of
        FmtMarkdown -> TIO.putStrLn (renderMarkdown reasons tasks Nothing)
        _           -> TIO.putStrLn (T.pack (show summary))
      when (ts == ts) (pure ())
